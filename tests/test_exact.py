"""Exact duct friction factor used as the reference for the square-duct study."""

from __future__ import annotations

import pytest

from foam_verify.exact import rectangular_duct_fre


def test_square_duct_matches_published_value() -> None:
    # Darcy f Re = 56.91 (Fanning 14.227) is the value quoted for the square duct.
    assert round(rectangular_duct_fre(1.0), 2) == 56.91
    assert round(rectangular_duct_fre(1.0, darcy=False), 3) == 14.227


def test_parallel_plate_limit() -> None:
    # aspect -> 0 is flow between parallel plates: Darcy f Re = 96 exactly.
    assert rectangular_duct_fre(1e-6) == pytest.approx(96.0, rel=1e-5)


def test_friction_rises_towards_the_plate_limit() -> None:
    values = [rectangular_duct_fre(a) for a in (1.0, 0.5, 0.25, 0.125)]
    assert values == sorted(values)


@pytest.mark.parametrize("aspect", [0.0, -0.5, 1.5])
def test_rejects_bad_aspect(aspect: float) -> None:
    with pytest.raises(ValueError):
        rectangular_duct_fre(aspect)
