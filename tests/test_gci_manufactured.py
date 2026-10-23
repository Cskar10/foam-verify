"""Manufactured sequences with known order and limit."""

from __future__ import annotations

import pytest

from foam_verify.gci import Method, Verdict, divergence_threshold, grid_convergence


def phi(h: float, p: float = 2.0) -> float:
    return 1.0 + 0.5 * h**p


def test_constant_ratio_recovers_p_and_limit() -> None:
    h = (0.1, 0.2, 0.4)
    res = grid_convergence([phi(x) for x in h], h=h)
    rich = res.richardson
    assert res.verdict is Verdict.MONOTONIC
    assert rich is not None
    assert rich.p_solver == "closed_form"
    assert rich.p == pytest.approx(2.0, abs=1e-12)
    assert rich.phi_ext == pytest.approx(1.0, abs=1e-12)


def test_constant_ratio_from_cell_counts() -> None:
    # 160^2, 80^2, 40^2 cells in 2-D: r = 2 throughout.
    cells = (160**2, 80**2, 40**2)
    h = (1.0, 2.0, 4.0)
    res = grid_convergence([phi(0.01 * x) for x in h], cells=cells, dim=2)
    assert res.r21 == pytest.approx(2.0)
    assert res.r32 == pytest.approx(2.0)
    assert res.richardson is not None
    assert res.richardson.p == pytest.approx(2.0, abs=1e-10)


def test_unequal_ratios_need_q_iteration() -> None:
    h1 = 0.1
    h = (h1, 1.5 * h1, 1.5 * 1.333 * h1)
    res = grid_convergence([phi(x) for x in h], h=h)
    rich = res.richardson
    assert rich is not None
    assert rich.p_solver == "fixed_point"
    assert rich.p_iterations > 1
    assert rich.p == pytest.approx(2.0, abs=1e-10)
    assert rich.phi_ext == pytest.approx(1.0, abs=1e-10)


def test_fixed_point_divergence_falls_back_to_bisection() -> None:
    # Celik's fixed-point map has slope above 1 here (r21 = 1.3, r32 = 2), so it diverges.
    h = (1.0, 1.3, 2.6)
    res = grid_convergence([phi(x, p=1.0) for x in h], h=h)
    rich = res.richardson
    assert res.verdict is Verdict.MONOTONIC
    assert rich is not None
    assert rich.p_solver == "bisection"
    assert rich.p == pytest.approx(1.0, abs=1e-9)


def test_unequal_ratios_beyond_r_equals_one_still_converge() -> None:
    # r21 = 2, r32 = 1.3: exact power-law data with p = 2 has R > 1, so the equal-ratio
    # rule "R >= 1 means divergence" would wrongly reject it.
    h = (1.0, 2.0, 2.6)
    res = grid_convergence([phi(x) for x in h], h=h)
    assert res.convergence_ratio is not None
    assert 1.0 < res.convergence_ratio < divergence_threshold(2.0, 1.3)
    assert res.verdict is Verdict.MONOTONIC
    assert res.richardson is not None
    assert res.richardson.p == pytest.approx(2.0, abs=1e-9)


def test_four_grids_give_one_result_per_triplet() -> None:
    h = (0.05, 0.1, 0.2, 0.4)
    res = grid_convergence([phi(x) for x in h], h=h)
    assert len(res.triplets) == 2
    assert res.triplets[0].phi == res.phi
    for t in res.triplets:
        assert t.verdict is Verdict.MONOTONIC
        assert t.richardson is not None
        assert t.richardson.p == pytest.approx(2.0, abs=1e-9)
    assert any("4 grids" in note for note in res.notes)


def test_band_contains_the_limit_for_converged_data() -> None:
    h = (0.1, 0.2, 0.4)
    res = grid_convergence([phi(x) for x in h], h=h)
    assert res.band is not None
    lo, hi = res.band
    assert lo <= 1.0 <= hi
    assert res.method is Method.GCI
