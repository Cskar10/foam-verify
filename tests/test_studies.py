"""The committed OpenFOAM studies under studies/, read back through foam-verify."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from foam_verify.exact import rectangular_duct_fre
from foam_verify.gci import Verdict
from foam_verify.iterative import Verdict as IterativeVerdict
from foam_verify.study import assess_study, load_study

STUDIES = Path(__file__).resolve().parent.parent / "studies"
DUCT = STUDIES / "duct"


def test_duct_fine_grid_band_contains_the_exact_value() -> None:
    res = assess_study(load_study(DUCT))
    assert [lv.cells for lv in res.levels] == [160**2, 80**2, 40**2, 20**2]
    (fre,) = res.qois
    gci = fre.gci
    assert gci.verdict is Verdict.MONOTONIC
    assert gci.band is not None
    low, high = gci.band
    assert low <= rectangular_duct_fre(1.0) <= high


def test_duct_wall_stress_matches_the_pressure_gradient_source() -> None:
    # Force balance: f Re = 800 tau_w = 200 G on every level, from two independent outputs.
    res = assess_study(load_study(DUCT))
    for level, value in zip(res.levels, res.qois[0].values, strict=True):
        props = (DUCT / level.path / "final" / "momentumSourceProperties").read_text()
        match = re.search(r"gradient\s+([-+0-9.eE]+);", props)
        assert match is not None
        assert value == pytest.approx(200 * float(match.group(1)), rel=1e-9)


CAVITY = STUDIES / "cavity"


def test_cavity_every_qoi_converges_monotonically_near_second_order() -> None:
    res = assess_study(load_study(CAVITY))
    assert [lv.cells for lv in res.levels] == [160**2, 80**2, 40**2, 20**2]
    assert res.warnings == ()
    assert len(res.qois) == 6
    for qoi in res.qois:
        gci = qoi.gci
        assert gci.verdict is Verdict.MONOTONIC, qoi.name
        assert gci.clean_pass, qoi.name
        assert gci.richardson is not None
        assert 1.5 < gci.richardson.p < 3.0, qoi.name
        assert gci.richardson.asymptotic_ratio == pytest.approx(1.0, abs=0.01), qoi.name


def test_cavity_fitted_minimum_is_below_the_nearest_ghia_point() -> None:
    # The parabola through the discrete minimum cannot sit above a sampled value nearby.
    qois = {q.name: q for q in assess_study(load_study(CAVITY)).qois}
    for fitted, sampled in zip(qois["u_min"].values, qois["u(y=0.4531)"].values, strict=True):
        assert fitted <= sampled


# --- iterative convergence ----------------------------------------------------------------


@pytest.mark.parametrize("study", [DUCT, CAVITY], ids=["duct", "cavity"])
def test_every_qoi_has_settled_on_every_level(study: Path) -> None:
    # The QoIs vary by about 1e-12 (relative) over their windows: u_it is far below U.
    for qoi in assess_study(load_study(study)).qois:
        assert [r.verdict for r in qoi.iterative] == [IterativeVerdict.CONVERGED] * 4, qoi.name
        assert all(r.clean_pass for r in qoi.iterative), qoi.name
        check = qoi.contamination
        assert check is not None and check.clean_pass, qoi.name
        assert check.worst_ratio is not None and check.worst_ratio < 1e-6, qoi.name


def test_cavity_points_and_profiles_share_one_window() -> None:
    # The Ghia points are written every 0.05 s from the start, the profiles every 0.05 s from
    # t = 7.5 s: both windows are the last 50 samples, t = 7.55 to 10 s.
    qois = assess_study(load_study(CAVITY)).qois
    samples = {q.name: q.iterative[0].samples for q in qois}
    assert samples == {
        "u(y=0.5)": 200,
        "u(y=0.4531)": 200,
        "u(y=0.8516)": 200,
        "u_min": 51,
        "v_max": 51,
        "v_min": 51,
    }
    for qoi in qois:
        for res in qoi.iterative:
            assert res.window == 50, qoi.name
            assert res.window_x == pytest.approx((7.55, 10.0)), qoi.name
