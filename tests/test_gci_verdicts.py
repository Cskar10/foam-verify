"""Every verdict type, and no fake GCI where the data cannot support one."""

from __future__ import annotations

import pytest

from foam_verify.gci import (
    Method,
    ObservedOrderError,
    Options,
    Verdict,
    grid_convergence,
    observed_order,
)

H = (1.0, 2.0, 4.0)


def test_oscillatory_convergence_uses_the_spread_bound() -> None:
    res = grid_convergence([1.0, 1.2, 0.5], h=H)
    assert res.convergence_ratio == pytest.approx(-0.2 / 0.7)
    assert res.verdict is Verdict.OSCILLATORY
    assert res.method is Method.SPREAD_BOUND
    assert not res.clean_pass and not res.richardson_used
    assert res.uncertainty == pytest.approx(3 * 0.7 / 2)


@pytest.mark.parametrize(
    ("values", "kind"),
    [([1.0, 1.5, 1.7], "monotonic"), ([1.0, 1.5, 1.2], "oscillatory")],
)
def test_divergence_has_no_gci(values: list[float], kind: str) -> None:
    res = grid_convergence(values, h=H)
    assert res.verdict is Verdict.DIVERGENT
    assert kind in res.reasons[0]
    assert res.richardson is None
    assert res.uncertainty is None and res.band is None
    assert res.method is Method.NONE
    assert not res.clean_pass


def test_equal_differences_are_divergent_not_converged() -> None:
    # R = 1 with equal ratios: the differences do not shrink.
    res = grid_convergence([1.0, 2.0, 3.0], h=H)
    assert res.verdict is Verdict.DIVERGENT


@pytest.mark.parametrize(
    "values",
    [[1.0, 1.0, 1.3], [1.0, 1.3, 1.3], [2.0, 2.0, 2.0], [0.0, 0.0, 0.0]],
)
def test_degenerate_differences_do_not_divide(values: list[float]) -> None:
    res = grid_convergence(values, h=H)
    assert res.verdict is Verdict.DEGENERATE
    assert res.richardson is None
    assert res.uncertainty is None
    assert "round-off" in res.reasons[0]


def test_plane_poiseuille_trap_is_degenerate() -> None:
    # A discretisation that reproduces a parabola exactly: differences at round-off level.
    res = grid_convergence([2.0 / 3.0, 2.0 / 3.0 + 1e-15, 2.0 / 3.0 - 2e-15], h=H)
    assert res.verdict is Verdict.DEGENERATE


def test_two_grids_assume_the_formal_order_with_fs_3() -> None:
    res = grid_convergence([1.005, 1.02], h=(1.0, 2.0))
    rich = res.richardson
    assert res.verdict is Verdict.TWO_GRID
    assert res.method is Method.ASSUMED_ORDER_GCI
    assert not res.clean_pass
    assert rich is not None
    assert rich.p_solver == "assumed"
    assert rich.p == 2.0
    assert rich.safety_factor == 3.0
    assert rich.gci_coarse is None and rich.asymptotic_ratio is None
    assert res.uncertainty == pytest.approx(3.0 * 0.015 / 3.0)
    assert any("only two grids" in w for w in res.warnings)


def test_two_identical_grids_are_degenerate() -> None:
    res = grid_convergence([1.0, 1.0], h=(1.0, 2.0))
    assert res.verdict is Verdict.DEGENERATE
    assert res.uncertainty is None


def test_small_refinement_ratio_blocks_a_clean_pass() -> None:
    h = (1.0, 1.1, 1.21)
    res = grid_convergence([1 + 0.01 * x**2 for x in h], h=h)
    assert res.verdict is Verdict.MONOTONIC
    assert not res.clean_pass
    assert sum("below 1.3" in w for w in res.warnings) == 2


def test_order_far_above_formal_uses_fs_3() -> None:
    h = (1.0, 2.0, 4.0)
    res = grid_convergence([1 + 0.001 * x**5 for x in h], h=h)
    rich = res.richardson
    assert rich is not None
    assert rich.p == pytest.approx(5.0)
    assert rich.safety_factor == 3.0
    assert not res.clean_pass
    assert any("outside [0.5, 4]" in w for w in res.warnings)


def test_order_below_half_uses_fs_3() -> None:
    h = (1.0, 2.0, 4.0)
    res = grid_convergence([1 + 0.1 * x**0.3 for x in h], h=h)
    assert res.richardson is not None
    assert res.richardson.safety_factor == 3.0
    assert not res.clean_pass


def test_non_asymptotic_triplet_is_flagged() -> None:
    # Exact power law far from the limit: GCI_32/(r^p GCI_21) = phi1/phi2, well below 0.9.
    h = (1.0, 2.0, 4.0)
    res = grid_convergence([0.1 + x**2 for x in h], h=h)
    assert res.verdict is Verdict.MONOTONIC
    assert res.richardson is not None and res.richardson.asymptotic_ratio is not None
    assert res.richardson.asymptotic_ratio == pytest.approx(1.1 / 4.1)
    assert not res.clean_pass
    assert any("asymptotic" in w for w in res.warnings)


def test_asymptotic_band_is_configurable() -> None:
    h = (1.0, 2.0, 4.0)
    res = grid_convergence(
        [0.1 + x**2 for x in h], h=h, options=Options(asymptotic_band=(0.2, 5.0))
    )
    assert res.clean_pass


def test_zero_fine_value_keeps_the_absolute_uncertainty() -> None:
    h = (1.0, 2.0, 4.0)
    res = grid_convergence([0.0, 3.0, 12.0], h=h)
    rich = res.richardson
    assert rich is not None
    assert rich.e_a is None and rich.gci_fine is None
    # p = log2(3), so r21^p = 3 and U = 1.25 |phi2 - phi1| / (3 - 1).
    assert rich.p == pytest.approx(1.584962500721156)
    assert res.uncertainty == pytest.approx(1.25 * 3.0 / 2.0)
    assert not res.clean_pass


def test_coarser_triplet_problems_are_noted() -> None:
    h = (1.0, 2.0, 4.0, 8.0)
    res = grid_convergence([1.0, 1.04, 1.16, 1.0], h=h)
    assert res.verdict is Verdict.MONOTONIC
    assert res.triplets[1].verdict is Verdict.OSCILLATORY
    assert any("grids 2-4" in n and "oscillatory" in n for n in res.notes)


def test_observed_order_rejects_zero_difference() -> None:
    with pytest.raises(ObservedOrderError):
        observed_order(0.0, 1.0, 2.0, 2.0)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"h": (1.0, 2.0, 4.0), "cells": (8, 4, 2), "dim": 1}, "exactly one"),
        ({}, "exactly one"),
        ({"h": (1.0, 4.0, 2.0)}, "strictly increasing"),
        ({"h": (1.0, 2.0)}, "one entry per value"),
        ({"cells": (100, 400, 1600), "dim": 2}, "strictly decreasing"),
        ({"cells": (1600, 400, 100), "dim": 4}, "dim"),
    ],
)
def test_bad_input_raises(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        grid_convergence([1.0, 1.1, 1.3], **kwargs)


def test_needs_two_grids_and_finite_values() -> None:
    with pytest.raises(ValueError, match="at least two"):
        grid_convergence([1.0], h=(1.0,))
    with pytest.raises(ValueError, match="finite"):
        grid_convergence([1.0, float("nan"), 1.2], h=H)
