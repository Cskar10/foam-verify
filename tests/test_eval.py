"""The evaluation bundles against their labels (eval/README.md).

Each built bundle must show what its label says, judged from its files and the committed
studies rather than from foam-verify, and must hold nothing that gives its label away. Then
foam-verify's own verdict on each is checked against the label, as the tool's own score. A
bundle not built yet is skipped.
"""

from __future__ import annotations

import math
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from foam_verify.gci import Verdict
from foam_verify.report import Status, verification_report
from foam_verify.study import (
    QoI,
    Series,
    Study,
    assess_study,
    cell_count,
    load_study,
    read_series,
)

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
BUNDLES = EVAL / "bundles"
STUDIES = ROOT / "studies"
LABELS: list[dict[str, Any]] = tomllib.loads((EVAL / "labels.toml").read_text(encoding="utf-8"))[
    "bundle"
]
BY_ID = {label["id"]: label for label in LABELS}
BUILT = [label for label in LABELS if (BUNDLES / label["id"] / "study.toml").is_file()]
IDS = [label["id"] for label in BUILT]
# The report's checks that find each reason a label may give.
CHECKS = {
    "iterative": {"Iterative convergence", "Iterative error"},
    "two_grids": {"Grid convergence"},
    "refinement_ratio": {"Refinement ratio"},
    "settings": {"Settings consistency"},
    "grid_convergence": {
        "Grid convergence",
        "Observed order",
        "Asymptotic range",
        "Coarser triplets",
    },
}


def built(bundle: str) -> Path:
    folder = BUNDLES / bundle
    if not (folder / "study.toml").is_file():
        pytest.skip(f"{bundle} is not built yet")
    return folder


def qoi(study: Study, name: str) -> QoI:
    return next(q for q in study.qois if q.name == name)


def at(series: Series, x: float) -> float:
    """The sample nearest x."""
    return series.y[min(range(len(series.x)), key=lambda k: abs(series.x[k] - x))]


def same_tree(a: Path, b: Path) -> bool:
    """The same files with the same bytes under a and b."""
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    if files != sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file()):
        return False
    return all((a / f).read_bytes() == (b / f).read_bytes() for f in files)


def inputs(case: Path) -> dict[str, bytes]:
    """A case's settings: system/, 0/ and constant/ without the mesh."""
    return {
        str(p.relative_to(case)): p.read_bytes()
        for sub in ("system", "constant", "0")
        for p in (case / sub).rglob("*")
        if p.is_file() and "polyMesh" not in p.parts
    }


def test_twelve_labels_four_of_them_trustworthy() -> None:
    assert [label["id"] for label in LABELS] == [f"b{i:02d}" for i in range(1, 13)]
    verdicts = [label["verdict"] for label in LABELS]
    assert (verdicts.count("trustworthy"), verdicts.count("not_trustworthy")) == (4, 8)
    for label in LABELS:
        assert set(label["reasons"]) <= set(CHECKS), label["id"]
        assert (label["verdict"] == "trustworthy") == (not label["reasons"]), label["id"]


@pytest.mark.parametrize("label", BUILT, ids=IDS)
def test_a_bundle_asks_about_its_qoi_and_gives_nothing_away(label: dict[str, Any]) -> None:
    folder = BUNDLES / label["id"]
    study = load_study(folder)
    assert [q.name for q in study.qois] == [label["qoi"]]
    assert study.references == ()
    for path in folder.rglob("*"):
        name = path.name.lower()
        assert not name.startswith(("report", "readme", "label", "generate", "run.")), path
        assert not name.endswith(".md"), path
    # The comments are ours; the rest of study.toml points at the data (the cavity's probes
    # were named ghiaPoints when the committed studies were run).
    comments = " ".join(
        line.lower() for line in (folder / "study.toml").read_text().splitlines() if "#" in line
    )
    for word in ("ghia", "marchi", "exact", "reference", "stop", "early", "upwind", "residual"):
        assert word not in comments, word
    for word in ("ratio", "trust", "label", "converge", "drift", "steady"):
        assert word not in comments, word


def test_b01_the_qoi_is_still_moving_at_the_end_on_every_level() -> None:
    bundle, cavity = load_study(built("b01")), load_study(STUDIES / "cavity")
    name = BY_ID["b01"]["qoi"]
    for level, committed in zip(bundle.levels, cavity.levels, strict=True):
        ours = read_series(level.path, qoi(bundle, name))
        full = read_series(committed.path, qoi(cavity, name))
        assert ours.x[-1] == pytest.approx(1.0)
        assert list(ours.y) == list(full.y[: len(ours.y)])  # the committed run, stopped at 1 s
        steady = full.y[-1]
        assert (ours.y[-1] - steady) / abs(steady) == pytest.approx(-0.0045, abs=1e-4)
        assert (ours.y[-1] - at(ours, 0.9)) / abs(steady) == pytest.approx(0.0032, abs=1e-4)


def test_b10_only_the_finest_level_stops_at_one_second() -> None:
    folder = built("b10")
    assert same_tree(folder / "n160", built("b01") / "n160")
    for n in (80, 40, 20):
        assert same_tree(folder / f"n{n}", STUDIES / "cavity" / f"n{n}"), n
    bundle, cavity = load_study(folder), load_study(STUDIES / "cavity")
    ours = read_series(bundle.levels[0].path, qoi(bundle, "u(y=0.5)"))
    steady = read_series(cavity.levels[0].path, qoi(cavity, "u(y=0.5)")).y[-1]
    assert ours.x[-1] == pytest.approx(1.0)
    assert (ours.y[-1] - steady) / abs(steady) == pytest.approx(0.00096, abs=2e-5)
    assert (ours.y[-1] - at(ours, 0.9)) / abs(steady) == pytest.approx(-0.00071, abs=2e-5)


def test_b05_one_level_uses_another_convection_scheme() -> None:
    folder = built("b05")
    for n in (160, 40, 20):
        assert same_tree(folder / f"n{n}", STUDIES / "cavity" / f"n{n}"), n
    ours, committed = inputs(folder / "n80"), inputs(STUDIES / "cavity" / "n80")
    assert ours.keys() == committed.keys()
    assert [rel for rel in ours if ours[rel] != committed[rel]] == ["system/fvSchemes"]
    scheme = (
        committed["system/fvSchemes"]
        .decode()
        .replace("div(phi,U)      Gauss linear;", "div(phi,U)      Gauss linearUpwind grad(U);")
    )
    assert ours["system/fvSchemes"].decode() == scheme


def test_b03_refines_by_about_1_1_and_every_level_settles() -> None:
    folder = built("b03")
    study = load_study(folder)
    cells = [cell_count(level.path) for level in study.levels]
    assert cells == [160**2, 145**2, 132**2, 120**2]
    assert all(1.09 < math.sqrt(a / b) < 1.11 for a, b in zip(cells, cells[1:], strict=False))
    assert same_tree(folder / "n160", STUDIES / "duct" / "n160")
    committed = inputs(STUDIES / "duct" / "n160")
    for n in (145, 132, 120):
        ours = inputs(folder / f"n{n}")
        assert [rel for rel in ours if ours[rel] != committed[rel]] == ["system/blockMeshDict"]
        window = read_series(folder / f"n{n}", study.qois[0]).y[-80:]
        assert (max(window) - min(window)) / abs(window[-1]) < 1e-11, n


def test_b12_stops_on_its_residuals_while_dp_still_swings() -> None:
    bundle, pitz = load_study(built("b12")), load_study(STUDIES / "pitzDaily")
    stops: dict[str, int] = {}
    for level, committed in zip(bundle.levels, pitz.levels, strict=True):
        match = re.search(
            r"SIMPLE solution converged in (\d+) iterations",
            (level.path / "log.simpleFoam").read_text(),
        )
        assert match is not None, level.name
        stops[level.name] = int(match.group(1))
        ours = read_series(level.path, bundle.qois[0])
        full = read_series(committed.path, qoi(pitz, "dp"))
        assert ours.x[-1] == stops[level.name]
        # The committed run's iterations, every tenth of which it sampled, up to the stop.
        sampled = dict(zip(full.x, full.y, strict=True))
        pairs = [(y, sampled[x]) for x, y in zip(ours.x, ours.y, strict=True) if x in sampled]
        assert len(pairs) == stops[level.name] // 10 and all(a == b for a, b in pairs)
        window = len(full.y) // 10
        settled = sum(full.y[-window:]) / window
        swing = abs(ours.y[-1] - at(ours, ours.x[-1] - 50)) / abs(settled)
        assert swing > 0.05, level.name
    assert stops == {"139k": 1419, "62k": 811, "28k": 440, "12k": 279}


@pytest.mark.parametrize("label", BUILT, ids=IDS)
def test_foam_verify_agrees_with_the_label(label: dict[str, Any]) -> None:
    report = verification_report(BUNDLES / label["id"])
    assert report.clean_pass == (label["verdict"] == "trustworthy")
    if label["reasons"]:
        (verdict,) = report.qois
        failed = {c.name for c in verdict.checks if c.status is Status.FAIL}
        assert failed & CHECKS[label["reasons"][0]], (label["id"], failed)


# --- the bundles cut from the committed studies ---------------------------------------------

CUT = {  # bundle: the committed study and the levels it holds, finest first
    "b02": ("duct", ("n160", "n80")),
    "b04": ("pitzDaily", ("n62k", "n28k", "n12k")),
    "b06": ("duct", ("n160", "n80", "n40", "n20")),
    "b07": ("cavity", ("n160", "n80", "n40")),
    "b08": ("pitzDaily", ("n139k", "n62k", "n28k", "n12k")),
    "b09": ("cavity", ("n160", "n80", "n40", "n20")),
    "b11": ("duct", ("n160", "n80", "n40")),
}
# What a sound bundle's band must hold, from outside foam-verify: the duct's exact f Re (the
# series solution), or Marchi, Suero and Araki's (2009) value.
EXACT_FRE = 56.90830753911475
OUTSIDE = {"b06": EXACT_FRE, "b11": EXACT_FRE, "b07": -0.2091491418, "b09": 0.179572814}


def half_unit(x: float) -> float:
    """Half a unit in the last decimal place that x is written with."""
    return 0.5 * 10.0 ** -len(repr(x).split(".")[1])


@pytest.mark.parametrize("bundle", sorted(CUT))
def test_a_cut_bundle_holds_the_committed_levels_unchanged(bundle: str) -> None:
    folder = built(bundle)
    study, levels = CUT[bundle]
    assert sorted(p.name for p in folder.iterdir() if p.is_dir()) == sorted(levels)
    assert [level.path.name for level in load_study(folder).levels] == list(levels)
    for level in levels:
        assert same_tree(folder / level, STUDIES / study / level), level


@pytest.mark.parametrize("bundle", sorted(OUTSIDE))
def test_a_sound_bundle_gives_its_label_s_result_whose_band_holds_the_reference(
    bundle: str,
) -> None:
    label = BY_ID[bundle]
    assert label["verdict"] == "trustworthy"
    (verdict,) = verification_report(built(bundle)).qois
    assert verdict.value == pytest.approx(label["value"], abs=half_unit(label["value"]))
    assert verdict.uncertainty is not None and verdict.band is not None
    assert verdict.uncertainty == pytest.approx(
        label["uncertainty"], abs=half_unit(label["uncertainty"])
    )
    low, high = verdict.band
    assert low <= OUTSIDE[bundle] <= high
    if "exact" in label:
        assert label["exact"] == EXACT_FRE


def test_b04_the_loss_diverges_over_the_three_coarser_levels() -> None:
    (q,) = assess_study(load_study(built("b04"))).qois
    fine, medium, coarse = q.values
    assert fine - medium == pytest.approx(0.602, abs=5e-4)
    assert medium - coarse == pytest.approx(0.5555, abs=1e-4)  # the label rounds it to 0.556
    assert (fine - medium) / (medium - coarse) == pytest.approx(1.08, abs=5e-3)


def test_b08_the_finest_triplet_converges_slowly_and_the_coarser_one_diverges() -> None:
    (q,) = assess_study(load_study(built("b08"))).qois
    gci = q.gci
    assert gci.verdict is Verdict.MONOTONIC and gci.richardson is not None
    assert gci.richardson.p == pytest.approx(0.85, abs=0.01)  # the formal order is 2
    assert gci.uncertainty is not None
    assert gci.uncertainty / abs(q.values[0]) == pytest.approx(0.08, abs=0.005)
    assert gci.triplets[1].verdict is Verdict.DIVERGENT
