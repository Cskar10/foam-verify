from __future__ import annotations

import json
from pathlib import Path

import pytest

from foam_verify import cli

STUDIES = Path(__file__).resolve().parent.parent / "studies"

SEQ = ["--grid-sequence", "structured"]
CELIK = [
    "--values", "6.063", "5.972", "5.863", "--cells", "18000", "8000", "4500", "--dim", "2",
    "--refined", "mesh", *SEQ,
]  # fmt: skip


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("foam-verify ")


def test_gci_text_clean_pass(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["gci", *CELIK]) == 0
    out = capsys.readouterr().out
    assert "verdict: monotonic_convergence (clean pass)" in out
    assert "refined: mesh" in out
    assert "grid sequence: structured" in out
    assert "p = 1.534 (fixed_point" in out
    assert "GCI_fine = 2.175%" in out
    assert "method: gci" in out


def test_gci_unstructured_sequence_uses_fs_3(capsys: pytest.CaptureFixture[str]) -> None:
    # ASME V&V 20, para. 2-4.1: Fs = 3 for unstructured refinement, so the GCI is 3/1.25 times
    # Celik's 2.175%. The order and the verdict do not change.
    argv = ["gci", *CELIK[: CELIK.index("--grid-sequence")], "--grid-sequence", "unstructured"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "grid sequence: unstructured" in out
    assert "p = 1.534 (fixed_point" in out
    assert "Fs = 3" in out
    assert "GCI_fine = 5.22%" in out


def test_gci_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["gci", *CELIK, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["verdict"] == "monotonic_convergence"
    assert data["clean_pass"] is True
    assert data["richardson"]["p"] == pytest.approx(1.534, abs=5e-4)


def test_gci_not_clean_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        [
            "gci",
            "--values",
            "6.0042",
            "5.9624",
            "6.0909",
            "--h",
            "1",
            "2",
            "4.286",
            "--refined",
            "mesh",
            *SEQ,
        ]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "oscillatory_convergence (not a clean pass)" in out
    assert "reference only" in out
    assert "method: spread_bound" in out


def test_gci_two_grid(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["gci", "--values", "1.005", "1.02", "--h", "1", "2", "--refined", "mesh", *SEQ]
    assert cli.main(argv) == 1
    out = capsys.readouterr().out
    assert "assumed formal order" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["gci", "--values", "1", "2", "3", "--cells", "8", "4", "2", "--refined", "mesh", *SEQ],
        ["gci", "--values", "1", "2", "3", "--h", "1", "2", "--refined", "mesh", *SEQ],
        [
            "gci",
            "--values",
            "1",
            "2",
            "3",
            "--h",
            "1",
            "2",
            "4",
            "--refined",
            "mesh",
            *SEQ,
            "--formal-order",
            "0",
        ],
        ["gci", "--values", "1", "2", "3", "--h", "1", "2", "4", *SEQ],
        ["gci", "--values", "1", "2", "3", "--h", "1", "2", "4", "--refined", "mesh"],
        [
            "gci",
            "--values",
            "1",
            "2",
            "3",
            "--h",
            "1",
            "2",
            "4",
            "--refined",
            "mesh",
            "--grid-sequence",
            "blocky",
        ],
        [
            "gci",
            "--values",
            "1",
            "2",
            "3",
            "--cells",
            "8",
            "4",
            "2",
            "--dim",
            "1",
            "--refined",
            "boundary-layer",
            *SEQ,
        ],
    ],
)
def test_gci_bad_input_exits_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_report_prints_markdown(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["report", str(STUDIES / "duct")]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Verification report: square-duct\n")
    assert "**Clean pass.** 1 of 1 quantity of interest is a clean pass." in out
    assert "## Reference comparison" in out


def test_report_json_from_the_manifest_path(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["report", str(STUDIES / "duct" / "study.toml"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["clean_pass"] is True
    assert [q["name"] for q in data["qois"]] == ["fRe"]


def test_report_output_writes_both_forms_and_exits_1_when_not_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "new" / "folder"
    assert cli.main(["report", str(STUDIES / "pitzDaily"), "--output", str(out)]) == 1
    printed = capsys.readouterr().out
    assert printed.startswith("pitzDaily: not a clean pass; 0 of 3 quantities of interest")
    assert (out / "report.md").read_text().startswith("# Verification report: pitzDaily\n")
    assert json.loads((out / "report.json").read_text())["clean_pass"] is False
    assert b"\r\n" not in (out / "report.md").read_bytes()


@pytest.mark.parametrize(
    "argv",
    [
        ["report", "no-such-study"],
        ["report", "no-such-study", "--json", "--output", "out"],
        ["report"],
    ],
)
def test_report_bad_input_exits_2(
    argv: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_gci_core_scope_subtracts_layer_cells(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["gci", "--values", "1.0", "1.04", "1.2", "--cells", "8100", "1100", "225"]
    argv += ["--dim", "3", "--refined", "core", *SEQ, "--layer-cells", "100", "--json"]
    cli.main(argv)
    data = json.loads(capsys.readouterr().out)
    assert data["scope"] == "core"
    assert data["r21"] == pytest.approx(2.0)
    assert data["r32"] == pytest.approx(2.0)


DUCT = ["--simulation", "56.899724578704", "--uncertainty", "0.010770340967144163"]


def test_compare_exact_reference_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["compare", *DUCT, "--reference", "56.90830753911475", "--kind", "exact"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert out.startswith("outcome: within_uncertainty (exact reference)\n")
    assert "|E| = 0.797 U_num" in out
    assert "code-verification check" in out


def test_compare_experiment_json_exits_1_when_not_within(
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = ["compare", "--simulation", "12", "--uncertainty", "0.6", "--reference", "7"]
    argv += ["--kind", "experiment", "--reference-uncertainty", "0.8", "--json"]
    assert cli.main(argv) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["case"] == "3a" and data["outcome"] == "outside_uncertainty"
    assert data["standard"]["divisor"] == 1.15


def test_compare_text_for_case_1(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["compare", "--simulation", "30", "--uncertainty", "0.6", "--reference", "7"]
    argv += ["--kind", "experiment", "--reference-uncertainty", "0.8", "--c", "7"]
    assert cli.main(argv) == 1
    out = capsys.readouterr().out
    assert "outcome: model_error (experiment reference)" in out
    assert "case 1 (C = 7): model error = E = 23" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["compare", *DUCT, "--reference", "1", "--kind", "experiment"],
        ["compare", *DUCT, "--reference", "1", "--kind", "exact", "--reference-uncertainty", "0.1"],
        ["compare", *DUCT, "--reference", "1"],
        ["compare", *DUCT, "--reference", "1", "--kind", "code", "--input-uncertainty", "0.1"],
        ["compare", *DUCT, "--reference", "1", "--kind", "code", "--method", "none"],
    ],
)
def test_compare_bad_input_exits_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err
