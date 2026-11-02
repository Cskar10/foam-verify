"""The MCP server, through the SDK's in-memory client: the tools, and the roots they keep to."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from foam_verify import cli
from foam_verify.report import render_json, verification_report
from foam_verify.server import create_server

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


def run(roots: list[Path], body: Callable[[ClientSession], Awaitable[Any]]) -> Any:
    """body(client) against a server over roots, connected in memory."""

    async def main() -> Any:
        server = create_server(roots)
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
    assert result.isError
    text = result.content[0]
    assert text.type == "text"
    return text.text


def test_seven_read_only_tools() -> None:
    async def body(client: ClientSession) -> None:
        listed = (await client.list_tools()).tools
        assert [t.name for t in listed] == TOOLS
        for tool in listed:
            assert tool.annotations is not None and tool.annotations.readOnlyHint, tool.name
            assert tool.annotations.destructiveHint is False, tool.name
            assert tool.description, tool.name

    run([STUDIES], body)


def test_list_studies_finds_the_committed_studies() -> None:
    async def body(client: ClientSession) -> dict[str, Any]:
        return await call(client, "list_studies")

    found = run([STUDIES], body)
    assert found["roots"] == [str(STUDIES)] and not found["truncated"]
    by_name = {s["name"]: s for s in found["studies"]}
    assert set(by_name) == {"square-duct", "lid-driven-cavity-re100", "pitzDaily"}
    assert by_name["square-duct"]["path"] == str(STUDIES / "duct")
    assert by_name["square-duct"]["levels"] == ["160x160", "80x80", "40x40", "20x20"]
    assert by_name["lid-driven-cavity-re100"]["references"] == 7


def test_the_report_tool_gives_the_library_report() -> None:
    async def body(client: ClientSession) -> dict[str, Any]:
        return await call(client, "verification_report", study="duct")

    data = run([STUDIES], body)
    expected = json.loads(render_json(verification_report(STUDIES / "duct")))
    assert data.pop("path") == str(STUDIES / "duct")
    assert data == expected


@pytest.mark.parametrize("study", ["../..", "/etc", "duct/../../src", str(STUDIES.parent)])
def test_paths_outside_the_roots_are_refused(study: str) -> None:
    async def body(client: ClientSession) -> str:
        return await refused(client, "study_summary", study=study)

    assert "is outside the allowed roots" in run([STUDIES], body)


def test_a_symlink_out_of_the_roots_is_refused(tmp_path: Path) -> None:
    (tmp_path / "duct").symlink_to(STUDIES / "duct", target_is_directory=True)

    async def body(client: ClientSession) -> tuple[str, dict[str, Any]]:
        return (
            await refused(client, "verification_report", study="duct"),
            await call(client, "list_studies"),
        )

    message, found = run([tmp_path], body)
    assert "is outside the allowed roots" in message
    assert found["studies"] == []  # list_studies does not follow symlinked folders


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
