"""The verification report: one verdict per QoI, the checks behind it, JSON and Markdown."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from foam_verify.compare import Outcome
from foam_verify.gci import Verdict
from foam_verify.report import (
    Report,
    Status,
    build_report,
    render_json,
    render_markdown,
    verification_report,
)
from foam_verify.study import assess_study, load_study

STUDIES = Path(__file__).resolve().parent.parent / "studies"
CHECKS = [
    "Grid convergence",
    "Refinement ratio",
    "Observed order",
    "Asymptotic range",
    "Coarser triplets",
    "Iterative convergence",
    "Iterative error",
    "Settings consistency",
    "Refined directions",
    "Refinement scope",
    "Grid sequence",
]


def assert_honest(report: Report) -> None:
    """A QoI is a clean pass exactly when no check fails and nothing is listed against it."""
    for v in report.qois:
        failed = [c.name for c in v.checks if c.status is Status.FAIL]
        assert v.clean_pass == (not failed), (v.name, failed)
        assert v.clean_pass == (not v.blocking), (v.name, v.blocking)
    assert report.clean_pass == all(v.clean_pass for v in report.qois)


def statuses(report: Report, qoi: str) -> dict[str, Status]:
    (verdict,) = [v for v in report.qois if v.name == qoi]
    return {c.name: c.status for c in verdict.checks}


def failed(report: Report, qoi: str) -> list[str]:
    return [name for name, s in statuses(report, qoi).items() if s is Status.FAIL]


def assert_tables_intact(md: str) -> None:
    """Every row of every Markdown table has as many cells as the table's header."""
    width: int | None = None
    for line in md.splitlines():
        if not line.startswith("|"):
            width = None
            continue
        cells = re.sub(r"\\\|", "", line).count("|") - 1
        if width is None:
            width = cells
        assert cells == width, line


# --- synthetic studies ------------------------------------------------------------------

HEADER = "FoamFile {{ version 2.0; format ascii; class {cls}; object {obj}; }}\n"
OWNER = 'FoamFile { version 2.0; format ascii; class labelList; note "nCells:%d"; object owner; }\n'
BOUNDARY = HEADER.format(cls="polyBoundaryMesh", obj="boundary") + (
    "2\n(\n    walls { type wall; nFaces 4; startFace 0; }\n"
    "    frontAndBack { type empty; nFaces %d; startFace 4; }\n)\n"
)
SCHEMES = HEADER.format(cls="dictionary", obj="fvSchemes") + (
    "ddtSchemes { default steadyState; }\ndivSchemes { default none; div(phi,U) Gauss %s; }\n"
)
SOLUTION = HEADER.format(cls="dictionary", obj="fvSolution") + "SIMPLE { nCorrectors 1; }\n"


def make_study(
    root: Path,
    values: Sequence[float],
    cells: Sequence[int],
    *,
    extra: str = "",
    schemes: Sequence[str] | None = None,
    histories: Sequence[Sequence[float]] | None = None,
) -> Path:
    """A 2-D study, finest first: one case per level with settings and a QoI history.

    Each history defaults to 100 samples of the level's value, so the QoI has settled.
    """
    text = f'name = "demo"\ndim = 2\nrefined = "mesh"\ngrid_sequence = "structured"\n{extra}'
    for i, (value, n) in enumerate(zip(values, cells, strict=True)):
        case = root / f"L{i}"
        (case / "constant" / "polyMesh").mkdir(parents=True)
        (case / "constant" / "polyMesh" / "owner").write_text(OWNER % n)
        (case / "constant" / "polyMesh" / "boundary").write_text(BOUNDARY % (2 * n))
        (case / "system").mkdir()
        scheme = schemes[i] if schemes is not None else "linear"
        (case / "system" / "fvSchemes").write_text(SCHEMES % scheme)
        (case / "system" / "fvSolution").write_text(SOLUTION)
        history = histories[i] if histories is not None else [value] * 100
        rows = "".join(f"{k}\t{v!r}\n" for k, v in enumerate(history, start=1))
        out = case / "postProcessing" / "avg" / "0"
        out.mkdir(parents=True)
        (out / "surfaceFieldValue.dat").write_text("# Time\tareaAverage(p)\n" + rows)
        text += f'\n[[levels]]\nname = "L{i}"\npath = "L{i}"\n'
    text += (
        '\n[[qoi]]\nname = "q"\nfile = "postProcessing/avg/*/surfaceFieldValue.dat"\n'
        'column = "areaAverage(p)"\n'
    )
    (root / "study.toml").write_text(text)
    return root


# phi = 1 + 0.005 h^2 on 2-D grids with r = 2: p = 2 exactly, asymptotic ratio 1.
CLEAN = ([1.005, 1.02, 1.08], [6400, 1600, 400])


def test_a_clean_synthetic_study(tmp_path: Path) -> None:
    report = verification_report(make_study(tmp_path, *CLEAN))
    assert_honest(report)
    assert report.clean_pass and report.summary == "1 of 1 quantity of interest is a clean pass"
    (q,) = report.qois
    assert [c.name for c in q.checks] == CHECKS
    assert statuses(report, "q")["Refinement scope"] is Status.ASSUMED
    assert statuses(report, "q")["Grid sequence"] is Status.ASSUMED
    assert statuses(report, "q")["Coarser triplets"] is Status.NOT_APPLICABLE
    assert q.grid_verdict is Verdict.MONOTONIC
    assert q.value == 1.005 and q.uncertainty is not None
    assert q.relative_uncertainty == pytest.approx(q.uncertainty / 1.005)
    assert q.band == pytest.approx((1.005 - q.uncertainty, 1.005 + q.uncertainty))


def test_an_unstructured_grid_sequence_is_stated_with_its_safety_factor(tmp_path: Path) -> None:
    study = make_study(tmp_path, *CLEAN)
    path = study / "study.toml"
    path.write_text(path.read_text().replace('"structured"', '"unstructured"'))
    report = verification_report(study)
    assert_honest(report)
    assert report.clean_pass  # Fs = 3 widens U; it fails no check
    (q,) = report.qois
    details = {c.name: c.detail for c in q.checks}
    assert details["Grid sequence"].startswith("grid sequence unstructured")
    assert details["Observed order"].endswith("Fs = 3 for an unstructured grid sequence")
    assert "grid sequence unstructured;" in render_markdown(report)


def test_two_grids_assume_the_order(tmp_path: Path) -> None:
    report = verification_report(make_study(tmp_path, [1.005, 1.02], [6400, 1600]))
    assert_honest(report)
    s = statuses(report, "q")
    assert s["Grid convergence"] is Status.FAIL
    assert s["Observed order"] is Status.ASSUMED
    assert s["Asymptotic range"] is Status.NOT_APPLICABLE
    assert any(item.startswith("only two grids") for item in report.qois[0].blocking)


def test_an_oscillatory_triplet_gets_a_spread_bound_and_no_pass(tmp_path: Path) -> None:
    report = verification_report(make_study(tmp_path, [1.0, 1.02, 0.99], CLEAN[1]))
    assert_honest(report)
    (q,) = report.qois
    assert q.grid_verdict is Verdict.OSCILLATORY and q.uncertainty is not None
    s = statuses(report, "q")
    assert failed(report, "q") == ["Grid convergence"]
    assert s["Observed order"] is Status.NOT_APPLICABLE
    assert "spread bound" in q.checks[0].detail


def test_close_grids_fail_the_ratio_check_only(tmp_path: Path) -> None:
    cells = [6400, 5000, 4000]
    values = [1 + 0.005 * (6400 / n) for n in cells]  # p = 2 in h = (6400 / n)^(1/2)
    report = verification_report(make_study(tmp_path, values, cells))
    assert_honest(report)
    assert failed(report, "q") == ["Refinement ratio"]


def test_a_drifting_level_fails_the_iterative_check(tmp_path: Path) -> None:
    values, cells = CLEAN
    histories = [[v] * 100 for v in values]
    histories[1] = [values[1] - 1e-4 * (99 - k) for k in range(100)]
    report = verification_report(make_study(tmp_path, values, cells, histories=histories))
    assert_honest(report)
    assert failed(report, "q") == ["Iterative convergence"]
    assert any(item.startswith("level L1: drifting") for item in report.qois[0].blocking)


def test_a_settings_difference_blocks_every_qoi(tmp_path: Path) -> None:
    study = make_study(tmp_path, *CLEAN, schemes=["linear", "linear", "upwind"])
    report = verification_report(study)
    assert_honest(report)
    assert failed(report, "q") == ["Settings consistency"]
    assert report.blocking == (
        "system/fvSchemes: divSchemes/div(phi,U): 'Gauss linear' on L0, L1; 'Gauss upwind' on L2",
    )
    md = render_markdown(report)
    assert "- every QoI: system/fvSchemes: divSchemes/div(phi,U):" in md
    assert (
        "| `system/fvSchemes` | `divSchemes/div(phi,U)` | Gauss linear | Gauss linear "
        "| Gauss upwind | yes |" in md
    )


def test_a_wrong_dim_fails_the_dimension_check(tmp_path: Path) -> None:
    study = make_study(tmp_path, *CLEAN)
    path = study / "study.toml"
    path.write_text(path.read_text().replace("dim = 2", "dim = 3"))
    report = verification_report(study)
    assert_honest(report)
    # With d = 3 the same cell counts mean r = 4^(1/3) and p = 3: still in range.
    assert failed(report, "q") == ["Refined directions"]
    assert report.blocking[0].startswith("dim = 3 but the mesh has empty or wedge patches")


def test_core_scope_needs_the_layer_cells(tmp_path: Path) -> None:
    values, cells = CLEAN
    make_study(tmp_path, values, cells)
    path = tmp_path / "study.toml"
    path.write_text(path.read_text().replace('refined = "mesh"', 'refined = "core"'))
    report = verification_report(tmp_path)
    assert_honest(report)
    assert failed(report, "q") == ["Refinement scope"]

    layered = [n + 100 for n in cells]
    core = tmp_path / "core"
    make_study(core, values, layered, extra="layer_cells = 100\n")
    path = core / "study.toml"
    path.write_text(path.read_text().replace('refined = "mesh"', 'refined = "core"'))
    report = verification_report(core)
    assert_honest(report)
    assert report.clean_pass
    assert statuses(report, "q")["Refinement scope"] is Status.ASSUMED
    md = render_markdown(report)
    assert "| Level | Folder | Cells | Core cells | r to the next coarser |" in md
    assert "| L0 | `L0` | 6,500 | 6,400 | 2.000 |" in md


def test_a_reason_with_pipes_does_not_break_a_table(tmp_path: Path) -> None:
    # R = -1.25: oscillatory divergence, whose reason reads "|R| >= 1".
    report = verification_report(make_study(tmp_path, [1.0, 1.05, 1.01], CLEAN[1]))
    assert_honest(report)
    assert report.qois[0].grid_verdict is Verdict.DIVERGENT
    md = render_markdown(report)
    assert "\\|R\\| >= 1" in md
    assert_tables_intact(md)


def test_an_unattributed_warning_still_fails_a_row(tmp_path: Path) -> None:
    # A future GCI warning that no row knows about: the table must not show a clean slate.
    study = load_study(make_study(tmp_path, *CLEAN))
    res = assess_study(study)
    (q,) = res.qois
    gci = replace(q.gci, clean_pass=False, warnings=("a warning no row knows",))
    report = build_report(study, replace(res, qois=(replace(q, gci=gci),)))
    assert_honest(report)
    assert report.qois[0].checks[-1].name == "Other"
    assert report.qois[0].checks[-1].detail == "a warning no row knows"


# --- reference comparison ---------------------------------------------------------------

FAR = '\n[[reference]]\nqoi = "q"\nkind = "code"\nvalue = 2.0\nsource = "a far-off table"\n'


def with_reference(root: Path, table: str) -> Path:
    path = root / "study.toml"
    path.write_text(path.read_text() + table)
    return root


def test_a_comparison_stays_outside_the_verdict(tmp_path: Path) -> None:
    report = verification_report(with_reference(make_study(tmp_path, *CLEAN), FAR))
    assert_honest(report)
    assert report.clean_pass  # |E| = 159 U_num from the reference changes no verdict
    (qc,) = report.comparisons
    assert qc.qoi == "q" and qc.comparison.outcome is Outcome.OUTSIDE
    md = render_markdown(report)
    assert_tables_intact(md)
    assert md.index("## Verdict") < md.index("## Reference comparison") < md.index("## Levels")
    row = "| `q` | a far-off table | code | 2 | -0.995 | -50% | 159 U_num | outside uncertainty |"
    assert row in md
    assert "- `q` against a far-off table: E = S - D = -0.995 is beyond" in md
    assert "- a far-off table on `q`: the reference states no uncertainty, so U_val is" in md
    assert "- Reference comparison, apart from the verdict:" in md  # in the method
    data = json.loads(render_json(report))
    assert data["clean_pass"] is True
    assert data["comparisons"][0]["qoi"] == "q"
    assert data["comparisons"][0]["comparison"]["outcome"] == "outside_uncertainty"


def test_without_references_there_is_no_comparison_section(tmp_path: Path) -> None:
    report = verification_report(make_study(tmp_path, *CLEAN))
    assert report.comparisons == ()
    assert "Reference comparison" not in render_markdown(report)
    assert json.loads(render_json(report))["comparisons"] == []


def test_a_comparison_without_an_uncertainty_is_not_judged(tmp_path: Path) -> None:
    # The divergent triplet of the test above gives no U, so E cannot be judged.
    study = make_study(tmp_path, [1.0, 1.05, 1.01], CLEAN[1])
    report = verification_report(with_reference(study, FAR.replace("2.0", "1.1")))
    (qc,) = report.comparisons
    assert qc.comparison.outcome is Outcome.NO_UNCERTAINTY
    row = "| `q` | a far-off table | code | 1.1 | -0.100 | -9.1% | n/a | no uncertainty |"
    assert row in render_markdown(report)


def test_an_experiment_shows_its_case(tmp_path: Path) -> None:
    table = FAR.replace('"code"', '"experiment"').replace("2.0", "1.0") + "uncertainty = 0.002\n"
    report = verification_report(with_reference(make_study(tmp_path, *CLEAN), table))
    md = render_markdown(report)
    assert_tables_intact(md)
    row = (
        "| `q` | a far-off table | experiment | 1 +/- 0.0020 | 0.00500 | 0.50% | 0.762 U_val "
        "| within uncertainty (case 3b) |"
    )
    assert row in md
    assert "u_num = U_num / 1.15" in md


def test_two_references_on_one_qoi_are_told_apart_by_their_labels(tmp_path: Path) -> None:
    near = (
        '\n[[reference]]\nqoi = "q"\nkind = "code"\nlabel = "Near"\nvalue = 1.004\n'
        'uncertainty = 1e-6\nsource = "a near table"\n'
    )
    far = FAR.replace("kind =", 'label = "Far"\nkind =')
    report = verification_report(with_reference(make_study(tmp_path, *CLEAN), far + near))
    assert [(qc.qoi, qc.label) for qc in report.comparisons] == [("q", "Far"), ("q", "Near")]
    md = render_markdown(report)
    assert_tables_intact(md)
    assert "| `q` | Far | code | 2 | -0.995 |" in md
    assert "| `q` | Near | code | 1.004 +/- 1.0e-06 | 0.00100 | 0.10% | 0.16 U_val |" in md
    # The warning is Far's alone; the note is both references'.
    assert "- Far on `q`: the reference states no uncertainty, so U_val is incomplete" in md
    assert "- Far on `q`; Near on `q`: a code reference makes this" in md


def test_reports_hold_no_absolute_path_or_time(tmp_path: Path) -> None:
    report = verification_report(make_study(tmp_path, *CLEAN))
    text = render_json(report) + render_markdown(report)
    assert str(tmp_path) not in text
    assert "root" not in json.loads(render_json(report))["result"]
    assert render_json(report) == render_json(verification_report(tmp_path))


def test_json_layout(tmp_path: Path) -> None:
    data = json.loads(render_json(verification_report(make_study(tmp_path, *CLEAN))))
    assert (data["tool"], data["schema"], data["study"]) == ("foam-verify", 1, "demo")
    assert data["criteria"]["asymptotic_band"] == [0.9, 1.1]
    (q,) = data["qois"]
    assert q["grid_verdict"] == "monotonic_convergence" and q["method"] == "gci"
    assert [c["status"] for c in q["checks"]][:3] == ["pass", "pass", "pass"]
    assert q["definition"]["column"] == "areaAverage(p)"
    assert data["result"]["qois"][0]["gci"]["verdict"] == "monotonic_convergence"


# --- the committed studies --------------------------------------------------------------


def test_duct_report() -> None:
    report = verification_report(STUDIES / "duct")
    assert_honest(report)
    assert report.clean_pass
    (fre,) = report.qois
    assert [c.name for c in fre.checks] == CHECKS
    assert {c.status for c in fre.checks} == {Status.PASS, Status.ASSUMED}
    md = render_markdown(report)
    assert_tables_intact(md)
    assert "**Clean pass.** 1 of 1 quantity of interest is a clean pass." in md
    assert "| `fRe` | 56.8997 +/- 0.0108 | 0.019% | monotonic, p = 1.995 | yes |" in md
    assert "band 56.8890 to 56.9105" in md
    # The exact value bounds the error: a code-verification check, outside the verdict.
    row = (
        "| `fRe` | Shah and London (1978) | exact | 56.90831 | -0.00858 | -0.015% | 0.797 U_num "
        "| within uncertainty |"
    )
    assert row in md


def test_cavity_report() -> None:
    report = verification_report(STUDIES / "cavity")
    assert_honest(report)
    assert report.clean_pass and report.summary == "6 of 6 quantities of interest are clean passes"
    # Ghia et al.'s values are 7 to 39 U_num away, Marchi et al.'s within U_val; either way the
    # verdict stays a clean pass.
    outcomes = [(qc.label, qc.qoi, qc.comparison.outcome) for qc in report.comparisons]
    ghia, marchi = "Ghia et al. (1982)", "Marchi et al. (2009)"
    assert outcomes == [
        *((ghia, q, Outcome.OUTSIDE) for q in ("u(y=0.5)", "u(y=0.4531)", "u(y=0.8516)")),
        *((marchi, q, Outcome.WITHIN) for q in ("u(y=0.5)", "u_min", "v_max", "v_min")),
    ]
    md = render_markdown(report)
    assert_tables_intact(md)
    rows = [
        "| `u(y=0.8516)` | Ghia et al. (1982) | code | 0.23151 | 0.00488 | 2.1% | 38.9 U_num "
        "| outside uncertainty |",
        "| `v_min` | Marchi et al. (2009) | code | -0.253804 +/- 1.1e-05 | 0.000219 | 0.086% "
        "| 0.797 U_val | within uncertainty |",
    ]
    assert all(row in md for row in rows)


def test_pitzdaily_report_refuses_a_clean_pass_and_says_why() -> None:
    report = verification_report(STUDIES / "pitzDaily")
    assert_honest(report)
    assert not report.clean_pass
    assert report.summary == "0 of 3 quantities of interest are clean passes"
    assert failed(report, "dp0") == ["Coarser triplets"]
    assert failed(report, "dp") == ["Asymptotic range", "Coarser triplets", "Iterative convergence"]
    assert failed(report, "xR/H") == ["Grid convergence", "Coarser triplets"]
    (xr,) = [v for v in report.qois if v.name == "xR/H"]
    assert xr.uncertainty is None and xr.band is None
    assert statuses(report, "xR/H")["Iterative error"] is Status.NOT_APPLICABLE


def same(a: Any, b: Any, where: str = "") -> None:
    """Equal JSON values, floats to 1e-9 relative: libm may differ in the last bit."""
    if isinstance(a, float) or isinstance(b, float):
        assert isinstance(a, int | float) and isinstance(b, int | float), where
        assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-300), where
    elif isinstance(a, dict):
        assert isinstance(b, dict), where
        x, y = cast(dict[str, Any], a), cast(dict[str, Any], b)
        assert x.keys() == y.keys(), where
        for key in x:
            same(x[key], y[key], f"{where}/{key}")
    elif isinstance(a, list):
        assert isinstance(b, list), where
        xs, ys = cast(list[Any], a), cast(list[Any], b)
        assert len(xs) == len(ys), where
        for i, (u, v) in enumerate(zip(xs, ys, strict=True)):
            same(u, v, f"{where}/{i}")
    else:
        assert a == b, where


@pytest.mark.parametrize("name", ["duct", "cavity", "pitzDaily"])
def test_committed_reports_match_the_code(name: str) -> None:
    # The reports under studies/ are regenerated with `make reports`.
    folder = STUDIES / name
    report = verification_report(folder)
    committed_md = (folder / "report.md").read_text(encoding="utf-8")
    assert committed_md == render_markdown(report), "stale report: run make reports"
    committed = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    same(committed, json.loads(render_json(report)))
