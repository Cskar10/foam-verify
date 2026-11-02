"""The MCP server through the SDK's in-memory client: every tool, and the roots it keeps to.

Each test starts a server over its roots, connects a client in memory and calls the tools as
an MCP client would. The first part checks that every tool gives what the library gives. The
second checks that no argument and no study can make a tool read outside the roots or a file
above the size cap, and that no tool writes, starts a process or opens a connection.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from foam_verify import access, cli
from foam_verify import server as server_module
from foam_verify.report import render_json, render_markdown, verification_report
from foam_verify.server import DEFAULT_MAX_BYTES, create_server
from foam_verify.study import assess_study, compare_references, load_study

STUDIES = Path(__file__).resolve().parent.parent / "studies"
TOOLS = [
    "list_studies",
    "study_summary",
    "grid_convergence",
    "iterative_convergence",
    "settings_consistency",
    "compare_reference",
    "verification_report",
]
STUDY_TOOLS = TOOLS[1:]  # every tool that takes a study
QOI_TOOLS = ["grid_convergence", "iterative_convergence", "compare_reference"]


def copy_study(name: str, dest: Path) -> Path:
    """A committed study copied to dest, without its uncommitted build/ folder."""
    shutil.copytree(STUDIES / name, dest, ignore=shutil.ignore_patterns("build"))
    return dest


def normal(value: Any) -> Any:
    """value as JSON gives it back: tuples as lists, enums as their strings."""
    return json.loads(json.dumps(value))


def run(
    roots: Sequence[Path],
    body: Callable[[ClientSession], Awaitable[Any]],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Any:
    """body(client) against a server over roots, connected in memory."""

    async def main() -> Any:
        server = create_server(roots, max_bytes=max_bytes)
        async with create_connected_server_and_client_session(server) as client:
            return await body(client)

    return anyio.run(main)


async def call(client: ClientSession, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    assert not result.isError, result.content
    assert result.structuredContent is not None
    return result.structuredContent


async def refused(client: ClientSession, tool: str, **arguments: Any) -> str:
    result = await client.call_tool(tool, arguments)
    assert result.isError, f"{tool}({arguments}) was not refused"
    text = result.content[0]
    assert text.type == "text"
    return text.text


def call_once(
    tool: str,
    roots: Sequence[Path] = (STUDIES,),
    max_bytes: int = DEFAULT_MAX_BYTES,
    **arguments: Any,
) -> dict[str, Any]:
    async def body(client: ClientSession) -> dict[str, Any]:
        return await call(client, tool, **arguments)

    return run(roots, body, max_bytes=max_bytes)


def refuse_once(
    tool: str,
    roots: Sequence[Path] = (STUDIES,),
    max_bytes: int = DEFAULT_MAX_BYTES,
    **arguments: Any,
) -> str:
    async def body(client: ClientSession) -> str:
        return await refused(client, tool, **arguments)

    return run(roots, body, max_bytes=max_bytes)


# --- every tool -------------------------------------------------------------------------


def test_seven_read_only_tools_and_their_inputs() -> None:
    async def body(client: ClientSession) -> Any:
        return (await client.list_tools()).tools

    listed = run([STUDIES], body)
    assert [t.name for t in listed] == TOOLS
    for tool in listed:
        hints = tool.annotations
        assert hints is not None and hints.readOnlyHint and hints.idempotentHint, tool.name
        assert hints.destructiveHint is False and hints.openWorldHint is False, tool.name
        assert tool.description, tool.name
    schemas = {t.name: t.inputSchema for t in listed}
    assert schemas["list_studies"].get("required", []) == []
    for name in STUDY_TOOLS:
        assert schemas[name]["required"] == ["study"], name
    for name in QOI_TOOLS:
        assert set(schemas[name]["properties"]) == {"study", "qoi"}, name
    assert schemas["verification_report"]["properties"]["format"]["enum"] == ["json", "markdown"]


def test_list_studies_finds_the_committed_studies() -> None:
    found = call_once("list_studies")
    assert found["roots"] == [str(STUDIES)] and not found["truncated"]
    by_name = {s["name"]: s for s in found["studies"]}
    assert set(by_name) == {"square-duct", "lid-driven-cavity-re100", "pitzDaily"}
    assert by_name["square-duct"] == {
        "path": str(STUDIES / "duct"),
        "name": "square-duct",
        "levels": ["160x160", "80x80", "40x40", "20x20"],
        "qois": ["fRe"],
        "references": 1,
    }
    assert by_name["lid-driven-cavity-re100"]["references"] == 7


def test_list_studies_shows_a_broken_study_and_skips_hidden_and_deep_folders(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    copy_study("duct", root / "a" / "duct")
    for folder in ("broken", ".hidden/study", "1/2/3/4", "1/2/3/4/5"):
        (root / folder).mkdir(parents=True)
        (root / folder / "study.toml").write_text("name = \n")  # not TOML
    found = call_once("list_studies", roots=[root])
    by_path = {Path(s["path"]).relative_to(root).as_posix(): s for s in found["studies"]}
    # Four folders down is the limit: 1/2/3/4 is listed, 1/2/3/4/5 is not.
    assert sorted(by_path) == ["1/2/3/4", "a/duct", "broken"]
    assert by_path["a/duct"]["name"] == "square-duct"
    assert set(by_path["broken"]) == {"path", "error"}


def test_list_studies_stops_at_its_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "MAX_STUDIES", 2)
    found = call_once("list_studies")
    assert len(found["studies"]) == 2 and found["truncated"]


def test_a_relative_study_goes_to_the_first_root_that_has_it(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    copy_study("duct", root / "duct")
    assert call_once("study_summary", roots=[root, STUDIES], study="duct")["path"] == str(
        root / "duct"
    )
    assert call_once("study_summary", roots=[STUDIES, root], study="duct")["path"] == str(
        STUDIES / "duct"
    )
    # Only the second root has the cavity.
    assert call_once("study_summary", roots=[root, STUDIES], study="cavity")["path"] == str(
        STUDIES / "cavity"
    )
    found = call_once("list_studies", roots=[STUDIES, root])
    assert found["roots"] == [str(STUDIES), str(root)]
    assert [s["name"] for s in found["studies"]].count("square-duct") == 2


@pytest.mark.parametrize("given", ["duct", "duct/study.toml", "./duct/", str(STUDIES / "duct")])
def test_a_study_by_its_folder_its_manifest_or_an_absolute_path(given: str) -> None:
    assert call_once("study_summary", study=given)["path"] == str(STUDIES / "duct")


@pytest.mark.parametrize("given", ["", "duct/n160", "duct/README.md", "nothing"])
def test_a_folder_without_a_study_is_refused(given: str) -> None:
    assert f"no study at {given!r}" in refuse_once("study_summary", study=given)


def test_study_summary_is_the_manifest_with_the_cell_counts() -> None:
    s = load_study(STUDIES / "duct")
    assert call_once("study_summary", study="duct") == {
        "path": str(STUDIES / "duct"),
        "name": "square-duct",
        "dim": 2,
        "formal_order": 2.0,
        "refined": "mesh",
        "grid_sequence": "structured",
        "layer_cells": None,
        "levels": [
            {"name": f"{n}x{n}", "path": f"n{n}", "cells": n * n, "first_layer_height": None}
            for n in (160, 80, 40, 20)
        ],
        "qois": normal([asdict(q) for q in s.qois]),
        "references": normal([asdict(r) for r in s.references]),
    }


def test_grid_convergence_gives_the_library_result_for_every_qoi() -> None:
    result = assess_study(load_study(STUDIES / "cavity"))
    assert call_once("grid_convergence", study="cavity") == {
        "path": str(STUDIES / "cavity"),
        "name": result.name,
        "levels": [{"name": lv.name, "cells": lv.cells} for lv in result.levels],
        "qois": normal(
            [
                {
                    "name": q.name,
                    "values": list(q.values),
                    "notes": list(q.notes),
                    "gci": q.gci.to_dict(),
                }
                for q in result.qois
            ]
        ),
    }


def test_grid_convergence_of_one_qoi_and_of_one_that_does_not_converge() -> None:
    one = call_once("grid_convergence", study="cavity", qoi="v_min")
    assert [q["name"] for q in one["qois"]] == ["v_min"]
    assert one["qois"][0]["gci"]["verdict"] == "monotonic_convergence"
    (xr,) = call_once("grid_convergence", study="pitzDaily", qoi="xR/H")["qois"]
    assert xr["gci"]["verdict"] != "monotonic_convergence"
    assert xr["gci"]["uncertainty"] is None and xr["gci"]["reasons"]


@pytest.mark.parametrize("tool", QOI_TOOLS)
def test_an_unknown_qoi_is_refused_with_the_study_s_qois(tool: str) -> None:
    message = refuse_once(tool, study="duct", qoi="fre")
    assert "no qoi 'fre' in study square-duct; its qois: fRe" in message


def test_iterative_convergence_gives_every_level_and_the_contamination_check() -> None:
    result = assess_study(load_study(STUDIES / "duct"))
    (q,) = result.qois
    assert q.contamination is not None
    (got,) = call_once("iterative_convergence", study="duct")["qois"]
    assert got == normal(
        {
            "name": "fRe",
            "levels": [
                {"level": lv.name, **it.to_dict()}
                for lv, it in zip(result.levels, q.iterative, strict=True)
            ],
            "contamination": q.contamination.to_dict(),
        }
    )
    assert [lv["verdict"] for lv in got["levels"]] == ["converged"] * 4


def test_settings_consistency_gives_the_library_result() -> None:
    consistency = assess_study(load_study(STUDIES / "cavity")).consistency
    assert consistency is not None
    data = call_once("settings_consistency", study="cavity")
    assert data["consistency"] == normal(consistency.to_dict())
    assert data["consistency"]["clean_pass"] is True
    assert [d["key"] for d in data["consistency"]["differences"]] == ["deltaT"]


def test_compare_reference_for_every_qoi_or_one() -> None:
    s = load_study(STUDIES / "cavity")
    expected = [
        {"qoi": c.qoi, "label": c.label, "comparison": c.comparison.to_dict()}
        for c in compare_references(s, assess_study(s))
    ]
    assert call_once("compare_reference", study="cavity")["comparisons"] == normal(expected)
    one = call_once("compare_reference", study="cavity", qoi="u(y=0.5)")["comparisons"]
    assert [(c["label"], c["comparison"]["outcome"]) for c in one] == [
        ("Ghia et al. (1982)", "outside_uncertainty"),
        ("Marchi et al. (2009)", "within_uncertainty"),
    ]
    assert call_once("compare_reference", study="pitzDaily")["comparisons"] == []


@pytest.mark.parametrize("name", ["duct", "cavity", "pitzDaily"])
def test_the_report_in_both_forms_is_the_library_report(name: str) -> None:
    async def body(client: ClientSession) -> tuple[dict[str, Any], dict[str, Any]]:
        return (
            await call(client, "verification_report", study=name),
            await call(client, "verification_report", study=name, format="markdown"),
        )

    data, md = run([STUDIES], body)
    report = verification_report(STUDIES / name)
    assert data.pop("path") == str(STUDIES / name)
    assert data == json.loads(render_json(report))
    assert md == {"path": str(STUDIES / name), "markdown": render_markdown(report)}


def test_a_bad_format_is_refused() -> None:
    assert "format" in refuse_once("verification_report", study="duct", format="pdf")


def test_the_text_content_is_the_structured_content_as_json() -> None:
    async def body(client: ClientSession) -> Any:
        return await client.call_tool("grid_convergence", {"study": "duct"})

    result = run([STUDIES], body)
    text = result.content[0]
    assert text.type == "text" and result.structuredContent is not None
    assert json.loads(text.text) == result.structuredContent


def test_the_server_keeps_serving_after_an_error() -> None:
    async def body(client: ClientSession) -> dict[str, Any]:
        await refused(client, "study_summary", study="bad\x00path")
        await refused(client, "grid_convergence", study="duct", qoi="nope")
        return await call(client, "study_summary", study="duct")

    assert run([STUDIES], body)["name"] == "square-duct"


# --- the sandbox ------------------------------------------------------------------------

ESCAPES = ["../..", "/etc", "~", "duct/../../src", str(STUDIES.parent)]


@pytest.mark.parametrize("study", ESCAPES)
@pytest.mark.parametrize("tool", STUDY_TOOLS)
def test_no_argument_reaches_outside_the_roots(tool: str, study: str) -> None:
    assert f"study {study!r} is outside the allowed roots" in refuse_once(tool, study=study)


@pytest.mark.parametrize("tool", STUDY_TOOLS)
def test_a_symlinked_study_that_leads_outside_is_refused(tool: str, tmp_path: Path) -> None:
    (tmp_path / "duct").symlink_to(STUDIES / "duct", target_is_directory=True)
    message = refuse_once(tool, roots=[tmp_path], study="duct")
    assert "is outside the allowed roots" in message
    assert call_once("list_studies", roots=[tmp_path])["studies"] == []  # not followed


SECRET = "never-in-a-result-7c1e"


@pytest.fixture
def jail(tmp_path: Path) -> tuple[Path, Path]:
    """root/duct, a copy of the duct study, and outside/, beside root, holding a secret."""
    study, outside = tmp_path / "root" / "duct", tmp_path / "outside"
    copy_study("duct", study)
    outside.mkdir()
    (outside / "secret").write_text(f"{SECRET} 1;\n")
    return study, outside


def move_out(path: Path, target: Path) -> None:
    """Move path to target, outside the roots, and leave a symlink to it in its place."""
    shutil.move(path, target)
    path.symlink_to(target, target_is_directory=target.is_dir())


def manifest_edit(study: Path, old: str, new: str) -> None:
    manifest = study / "study.toml"
    text = manifest.read_text()
    assert old in text
    manifest.write_text(text.replace(old, new))


QOI_FILE = 'file = "postProcessing/wallStress/*/surfaceFieldValue.dat"'


def link_manifest(study: Path, outside: Path) -> None:
    move_out(study / "study.toml", outside / "study.toml")


def link_case(study: Path, outside: Path) -> None:
    move_out(study / "n160", outside / "n160")


def link_mesh_header(study: Path, outside: Path) -> None:
    move_out(study / "n160/constant/polyMesh/owner", outside / "owner")


def link_settings_folder(study: Path, outside: Path) -> None:
    move_out(study / "n160/constant", outside / "constant")


def link_qoi_table(study: Path, outside: Path) -> None:
    move_out(study / "n160/postProcessing/wallStress/0/surfaceFieldValue.dat", outside / "t.dat")


def link_post_processing(study: Path, outside: Path) -> None:
    move_out(study / "n160/postProcessing", outside / "postProcessing")


def level_path_outside(study: Path, outside: Path) -> None:
    shutil.copytree(study / "n160", outside / "n160")
    manifest_edit(study, 'path = "n160"', 'path = "../../outside/n160"')


def qoi_pattern_outside(study: Path, outside: Path) -> None:
    manifest_edit(study, QOI_FILE, 'file = "../../../outside/secret"')


def qoi_pattern_absolute(study: Path, outside: Path) -> None:
    manifest_edit(study, QOI_FILE, f'file = "{outside / "secret"}"')


# Each turns the duct copy into a study that reaches outside the roots one way, and the message
# that refuses it: the sandbox's, or the study reader's own when it catches the escape first.
ESCAPING_STUDIES: list[tuple[Callable[[Path, Path], None], str]] = [
    (link_manifest, "is outside the allowed roots"),
    (link_case, "is outside"),
    (link_mesh_header, "is outside the allowed roots"),
    (link_settings_folder, "is outside the allowed roots"),
    (link_qoi_table, "is outside"),
    (link_post_processing, "is outside"),
    (level_path_outside, "is outside"),
    (qoi_pattern_outside, "is outside"),
    (qoi_pattern_absolute, "relative to each case folder"),
]


@pytest.mark.parametrize(
    ("make", "message"), ESCAPING_STUDIES, ids=[make.__name__ for make, _ in ESCAPING_STUDIES]
)
def test_a_study_that_reaches_outside_is_refused(
    make: Callable[[Path, Path], None], message: str, jail: tuple[Path, Path]
) -> None:
    study, outside = jail
    make(study, outside)
    for tool in ("verification_report", "grid_convergence"):
        text = refuse_once(tool, roots=[study.parent], study="duct")
        assert message in text, (tool, text)
        assert SECRET not in text


def test_a_settings_file_that_links_outside_is_not_read(jail: tuple[Path, Path]) -> None:
    study, outside = jail
    schemes = study / "n160/system/fvSchemes"
    schemes.unlink()
    schemes.symlink_to(outside / "secret")
    data = call_once("verification_report", roots=[study.parent], study="duct")
    assert SECRET not in json.dumps(data)
    assert not data["clean_pass"]
    assert any("system/fvSchemes on 160x160: links outside" in b for b in data["blocking"])


def test_an_include_that_leads_outside_is_not_followed(jail: tuple[Path, Path]) -> None:
    study, outside = jail
    schemes = study / "n160/system/fvSchemes"
    schemes.write_text(schemes.read_text() + f'\n#include "{outside / "secret"}"\n')
    data = call_once("verification_report", roots=[study.parent], study="duct")
    assert SECRET not in json.dumps(data)
    assert not data["clean_pass"]  # the directive is a difference between the levels


def test_a_file_above_the_cap_is_refused_whole() -> None:
    # The duct's study.toml is 1.4 kB, its wall-stress tables 65 kB.
    message = refuse_once("verification_report", max_bytes=10_000, study="duct")
    assert "surfaceFieldValue.dat: larger than 10000 bytes" in message
    assert call_once("study_summary", max_bytes=10_000, study="duct")["name"] == "square-duct"


def snapshot(root: Path) -> dict[str, str]:
    """Every folder and file under root, with each file's sha256."""
    tree: dict[str, str] = {}
    for folder, _, files in os.walk(root):
        here = Path(folder)
        tree[here.relative_to(root).as_posix() + "/"] = ""
        for name in files:
            tree[(here / name).relative_to(root).as_posix()] = hashlib.sha256(
                (here / name).read_bytes()
            ).hexdigest()
    return tree


def test_the_tools_write_nothing_start_no_process_and_open_no_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy_study("cavity", tmp_path / "cavity")
    before = snapshot(tmp_path)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a tool tried to start a process or open a connection")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)

    async def body(client: ClientSession) -> None:
        await call(client, "list_studies")
        for tool in STUDY_TOOLS:
            await call(client, tool, study="cavity")
        await call(client, "verification_report", study="cavity", format="markdown")

    run([tmp_path], body)
    assert snapshot(tmp_path) == before
    assert access.current() is None  # the sandbox ends with each call


# --- the command ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["mcp"], "--root"),
        (["mcp", "--root", "/no/such/folder"], "is not a folder"),
        (["mcp", "--root", ".", "--max-file-mb", "0"], "must be positive"),
    ],
)
def test_mcp_bad_input_exits_2(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)
    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err
