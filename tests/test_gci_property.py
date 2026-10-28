"""Property tests: exact power-law data must give back its order, limit and convergence type."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from foam_verify.gci import Verdict, grid_convergence

orders = st.floats(0.5, 3.0)
ratios = st.floats(1.3, 3.0)
limits = st.floats(-10.0, 10.0)
coefficients = st.floats(0.1, 10.0) | st.floats(-10.0, -0.1)
fine_sizes = st.floats(0.05, 1.0)


def _sizes(h1: float, r21: float, r32: float) -> tuple[float, float, float]:
    return (h1, h1 * r21, h1 * r21 * r32)


@settings(max_examples=300, deadline=None)
@given(p=orders, c=coefficients, phi0=limits, h1=fine_sizes, r21=ratios, r32=ratios)
def test_monotonic_power_law(
    p: float, c: float, phi0: float, h1: float, r21: float, r32: float
) -> None:
    h = _sizes(h1, r21, r32)
    res = grid_convergence([phi0 + c * x**p for x in h], h=h)
    assert res.verdict is Verdict.MONOTONIC
    assert res.richardson is not None
    assert res.richardson.p == pytest.approx(p, abs=1e-6)
    assert res.richardson.phi_ext == pytest.approx(phi0, abs=1e-6 * max(1.0, abs(c)))


@settings(max_examples=300, deadline=None)
@given(p=orders, c=coefficients, phi0=limits, h1=fine_sizes, r21=ratios, r32=ratios)
def test_alternating_power_law(
    p: float, c: float, phi0: float, h1: float, r21: float, r32: float
) -> None:
    h = _sizes(h1, r21, r32)
    values = [phi0 + c * (-1) ** k * x**p for k, x in enumerate(h)]
    res = grid_convergence(values, h=h)
    assert res.verdict is Verdict.OSCILLATORY
    assert res.richardson is not None
    assert res.richardson.p == pytest.approx(p, abs=1e-6)
    assert res.band is not None
    lo, hi = res.band
    assert lo <= phi0 <= hi


@settings(max_examples=300, deadline=None)
@given(p=orders, c=coefficients, phi0=limits, h1=fine_sizes, r21=ratios, r32=ratios)
def test_growing_differences_are_divergent(
    p: float, c: float, phi0: float, h1: float, r21: float, r32: float
) -> None:
    h = _sizes(h1, r21, r32)
    res = grid_convergence([phi0 + c * x ** (-p) for x in h], h=h)
    assert res.verdict is Verdict.DIVERGENT
    assert res.uncertainty is None
