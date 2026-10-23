"""Reproduce Table 1 of Celik et al. (2008) to its printed precision.

The published values are in tests/data/celik2008_table1.json, copied from the paper with its
source and checksum. One printed value does not follow from the paper's own Eq. 6; that case is
tested separately below rather than loosened.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from foam_verify.gci import Method, Verdict, grid_convergence

TABLE = json.loads((Path(__file__).parent / "data" / "celik2008_table1.json").read_text())
COLUMNS = {c["name"]: c for c in TABLE["columns"]}

# (column, field) pairs whose printed value disagrees with Eq. 6; see test_e_ext_erratum.
ERRATA = {("axial_velocity_p_below_1", "e_ext_pct")}


def agrees(computed: float, printed: str) -> bool:
    """True if computed rounds to the printed value at the printed number of decimals."""
    d = Decimal(printed)
    half_ulp = Decimal(1).scaleb(d.as_tuple().exponent) / 2
    return abs(Decimal(repr(computed)) - d) <= half_ulp


def _result(col: dict):
    return grid_convergence([float(x) for x in col["phi"]], cells=col["N"], dim=2)


def _computed(col: dict) -> dict[str, float]:
    res = _result(col)
    rich = res.richardson
    assert rich is not None
    return {
        "r21": res.r21,
        "r32": res.r32,
        "p": rich.p,
        "phi_ext": rich.phi_ext,
        "e_a_pct": 100 * rich.e_a,
        "e_ext_pct": 100 * rich.e_ext,
        "gci_fine_pct": 100 * rich.gci_fine,
    }


CASES = [
    (name, field)
    for name in COLUMNS
    for field in ("r21", "r32", "p", "phi_ext", "e_a_pct", "e_ext_pct", "gci_fine_pct")
    if (name, field) not in ERRATA
]


@pytest.mark.parametrize(("name", "field"), CASES)
def test_reproduces_printed_value(name: str, field: str) -> None:
    col = COLUMNS[name]
    value = _computed(col)[field]
    assert agrees(value, col[field]), f"{name}.{field}: computed {value!r}, printed {col[field]}"


def test_e_ext_erratum() -> None:
    """Column 2 prints e_ext = 0.9%, but Eq. 6 gives 0.85%.

    Eq. 6 divides by phi_ext: |10.8801 - 10.7880| / 10.8801 = 0.8465%, which rounds to 0.8%.
    Dividing by phi_1 instead gives 0.8537%, which rounds to the printed 0.9%, so the table entry
    looks computed with the wrong denominator. foam-verify follows Eq. 6 as published.
    """
    col = COLUMNS["axial_velocity_p_below_1"]
    rich = _result(col).richardson
    assert rich is not None
    assert agrees(100 * rich.e_ext, "0.85")
    assert not agrees(100 * rich.e_ext, col["e_ext_pct"])
    phi1 = float(col["phi"][0])
    assert agrees(100 * abs(rich.phi_ext - phi1) / phi1, col["e_ext_pct"])


def test_monotonic_columns_pass_cleanly() -> None:
    for name in ("reattachment_length", "axial_velocity_p_below_1"):
        res = _result(COLUMNS[name])
        assert res.verdict is Verdict.MONOTONIC
        assert res.clean_pass, res.warnings
        assert res.method is Method.GCI
        assert res.richardson_used
        assert res.richardson is not None and res.richardson.gci_fine is not None
        assert res.uncertainty == pytest.approx(res.richardson.gci_fine * abs(res.phi[0]))


def test_oscillatory_column_is_not_a_clean_gci() -> None:
    res = _result(COLUMNS["axial_velocity_oscillatory"])
    assert res.verdict is Verdict.OSCILLATORY
    assert not res.clean_pass
    assert res.method is Method.SPREAD_BOUND
    assert not res.richardson_used
    # Spread bound: 3 x (6.0909 - 5.9624) / 2, about seven times the 0.5% Richardson GCI.
    assert res.uncertainty == pytest.approx(3 * (6.0909 - 5.9624) / 2)
    assert res.richardson is not None and res.richardson.gci_fine is not None
    assert res.uncertainty > 5 * res.richardson.gci_fine * abs(res.phi[0])


def test_fixed_point_converges_on_published_data() -> None:
    for col in COLUMNS.values():
        rich = _result(col).richardson
        assert rich is not None
        assert rich.p_solver == "fixed_point"
        assert rich.p_iterations > 0
