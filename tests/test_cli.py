from __future__ import annotations

import json

import pytest

from foam_verify import cli

CELIK = [
    "--values", "6.063", "5.972", "5.863", "--cells", "18000", "8000", "4500", "--dim", "2",
    "--refined", "mesh",
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
    assert "p = 1.534 (fixed_point" in out
    assert "GCI_fine = 2.175%" in out
    assert "method: gci" in out


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
        ]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "oscillatory_convergence (not a clean pass)" in out
    assert "reference only" in out
    assert "method: spread_bound" in out


def test_gci_two_grid(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["gci", "--values", "1.005", "1.02", "--h", "1", "2", "--refined", "mesh"]) == 1
    out = capsys.readouterr().out
    assert "assumed formal order" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["gci", "--values", "1", "2", "3", "--cells", "8", "4", "2", "--refined", "mesh"],
        ["gci", "--values", "1", "2", "3", "--h", "1", "2", "--refined", "mesh"],
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
            "--formal-order",
            "0",
        ],
        ["gci", "--values", "1", "2", "3", "--h", "1", "2", "4"],
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
        ],
    ],
)
def test_gci_bad_input_exits_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_gci_core_scope_subtracts_layer_cells(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["gci", "--values", "1.0", "1.04", "1.2", "--cells", "8100", "1100", "225"]
    argv += ["--dim", "3", "--refined", "core", "--layer-cells", "100", "--json"]
    cli.main(argv)
    data = json.loads(capsys.readouterr().out)
    assert data["scope"] == "core"
    assert data["r21"] == pytest.approx(2.0)
    assert data["r32"] == pytest.approx(2.0)
