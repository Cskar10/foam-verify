"""Comparison with reference data: E = S - D against the uncertainty that applies."""

from __future__ import annotations

import json
import math

import pytest

from foam_verify.compare import (
    Outcome,
    Reference,
    ReferenceKind,
    check_reference,
    compare,
    compare_result,
)
from foam_verify.exact import rectangular_duct_fre
from foam_verify.gci import Method, grid_convergence

EXACT = ReferenceKind.EXACT
CODE = ReferenceKind.CODE
EXPERIMENT = ReferenceKind.EXPERIMENT

# The committed square-duct study: fine-grid f Re and its 95% uncertainty (studies/duct).
DUCT_S, DUCT_U = 56.899724578704, 0.010770340967144163


# --- exact references: a code-verification check ------------------------------------------


def test_duct_against_its_exact_value() -> None:
    d = rectangular_duct_fre(1.0)
    res = compare(DUCT_S, DUCT_U, Reference(d, EXACT, source="Shah and London 1978"))
    assert res.outcome is Outcome.WITHIN
    assert res.error == pytest.approx(-0.0085830, abs=1e-7)
    assert res.ratio == pytest.approx(0.797, abs=1e-3)
    assert res.reference_uncertainty == 0.0 and res.validation == DUCT_U
    assert res.relative_error == pytest.approx(res.error / d)
    assert res.case is None and res.standard is None
    assert "the numerical uncertainty bounds it" in res.reasons[0]
    assert any("code-verification check" in n for n in res.notes)


def test_an_error_beyond_u_num_is_not_bounded() -> None:
    res = compare(1.02, 0.01, Reference(1.0, EXACT))
    assert res.outcome is Outcome.OUTSIDE
    assert res.ratio == pytest.approx(2.0)
    assert "does not bound it" in res.reasons[0]


def test_an_exact_reference_has_no_uncertainty() -> None:
    with pytest.raises(ValueError, match="no uncertainty"):
        compare(1.0, 0.1, Reference(1.0, EXACT, uncertainty=0.01))


# --- code references: code-to-code ------------------------------------------------------------


def test_code_reference_without_uncertainty_within_u_num() -> None:
    res = compare(1.003, 0.005, Reference(1.0, CODE))
    assert res.outcome is Outcome.WITHIN
    assert res.reference_uncertainty is None and res.validation is None
    assert res.needed is None
    assert res.warnings == ("the reference states no uncertainty, so U_val is incomplete",)


def test_code_reference_without_uncertainty_beyond_u_num_says_what_it_would_need() -> None:
    # |E| = 0.005 and U_num = 0.003: agreement needs U_D >= sqrt(0.005^2 - 0.003^2) = 0.004.
    res = compare(1.005, 0.003, Reference(1.0, CODE))
    assert res.outcome is Outcome.OUTSIDE
    assert res.needed == pytest.approx(0.004)
    assert "at least 0.004" in res.reasons[0]


def test_code_reference_with_uncertainty_combines_both() -> None:
    res = compare(1.005, 0.003, Reference(1.0, CODE, uncertainty=0.004))
    assert res.validation == pytest.approx(0.005)
    assert res.outcome is Outcome.WITHIN  # |E| = U_val exactly: within
    assert compare(1.006, 0.003, Reference(1.0, CODE, uncertainty=0.004)).outcome is (
        Outcome.OUTSIDE
    )


# --- experiments: validation ---------------------------------------------------------------------


def experiment(standard_uncertainty: float | None = None) -> Reference:
    """D = 10 with U_D = 0.8: with U_num = 0.6, U_val = 1, and S = 10 + e gives E = e."""
    return Reference(10.0, EXPERIMENT, uncertainty=0.8, standard_uncertainty=standard_uncertainty)


@pytest.mark.parametrize(
    ("e", "case", "outcome", "bound", "sign"),
    [
        (12.0, "1", Outcome.MODEL_ERROR, 12.0, 1),
        (10.0, "3a", Outcome.OUTSIDE, 11.0, 1),  # |E| = C U_val: still 3a
        (-5.0, "3a", Outcome.OUTSIDE, 6.0, -1),
        (1.0, "3a", Outcome.OUTSIDE, 2.0, 1),  # |E| = U_val: 3a (their Figure 1)
        (0.5, "3b", Outcome.WITHIN, 1.5, None),
        (0.05, "2", Outcome.WITHIN, 1.0, None),
    ],
)
def test_experiment_cases(
    e: float, case: str, outcome: Outcome, bound: float, sign: int | None
) -> None:
    # Eça, Dowding and Roache (2020): the algorithmic version of the V&V 20 outcome, C = 10.
    res = compare(10.0 + e, 0.6, experiment())
    assert res.validation == pytest.approx(1.0)
    assert res.error == pytest.approx(e)
    assert (res.case, res.outcome) == (case, outcome)
    assert res.model_error_bound == pytest.approx(bound)
    assert res.model_error_sign == sign
    assert res.c == 10.0


def test_e_equal_to_u_val_over_c_is_case_3b() -> None:
    # Exact in binary: U_val = sqrt(0.75^2 + 1^2) = 1.25 and E = 0.125 = U_val / 10.
    res = compare(8.125, 0.75, Reference(8.0, EXPERIMENT, uncertainty=1.0))
    assert res.validation == 1.25 and res.error == 0.125
    assert res.case == "3b"
    assert compare(8.124, 0.75, Reference(8.0, EXPERIMENT, uncertainty=1.0)).case == "2"


def test_c_sets_the_model_error_threshold() -> None:
    assert compare(18.0, 0.6, experiment()).case == "3a"
    assert compare(18.0, 0.6, experiment(), c=7.0).case == "1"


def test_experiment_input_uncertainty_enters_u_val() -> None:
    res = compare(10.5, 0.6, experiment(), input_uncertainty=math.sqrt(3.0) * 0.5)
    assert res.validation == pytest.approx(math.sqrt(0.36 + 0.75 + 0.64))
    assert not any(n.startswith("U_input = 0") for n in res.notes)
    assert any(n.startswith("U_input = 0") for n in compare(10.5, 0.6, experiment()).notes)


def test_experiment_standard_uncertainty_states_its_divisor() -> None:
    # ASME V&V 20: GCI / 1.15 for monotonic convergence (eq. 2-4-14), U / 2 for oscillatory
    # (eq. 2-4-13). u_val needs the experiment's own standard uncertainty.
    res = compare(10.5, 0.6, experiment(standard_uncertainty=0.4))
    std = res.standard
    assert std is not None
    assert (std.divisor, std.numerical) == (1.15, pytest.approx(0.6 / 1.15))
    assert "eq. 2-4-14" in std.basis
    assert std.validation == pytest.approx(math.hypot(0.6 / 1.15, 0.4))
    osc = compare(10.5, 0.6, experiment(), method=Method.SPREAD_BOUND).standard
    assert osc is not None and osc.divisor == 2.0 and "eq. 2-4-13" in osc.basis
    assert osc.validation is None
    two = compare(10.5, 0.6, experiment(), method=Method.ASSUMED_ORDER_GCI).standard
    assert two is not None and two.divisor == 1.15 and "two grids" in two.basis


def test_an_experiment_needs_its_uncertainty() -> None:
    for u in (None, 0.0):
        with pytest.raises(ValueError, match="experimental uncertainty"):
            compare(1.0, 0.1, Reference(1.0, EXPERIMENT, uncertainty=u))


# --- common rules -------------------------------------------------------------------------------


def test_no_numerical_uncertainty_cannot_be_judged() -> None:
    res = compare(1.2, None, Reference(1.0, EXACT))
    assert res.outcome is Outcome.NO_UNCERTAINTY
    assert res.ratio is None and res.validation is None
    assert res.error == pytest.approx(0.2)


def test_bad_options() -> None:
    with pytest.raises(ValueError, match="experiments only"):
        compare(1.0, 0.1, Reference(1.0, CODE), input_uncertainty=0.1)
    for c in (1.0, math.inf):
        with pytest.raises(ValueError, match="above 1"):
            compare(1.0, 0.1, Reference(1.0, CODE), c=c)


def test_bad_numbers() -> None:
    with pytest.raises(ValueError, match="finite"):
        compare(math.nan, 0.1, Reference(1.0, EXACT))
    with pytest.raises(ValueError, match="non-negative"):
        compare(1.0, -0.1, Reference(1.0, EXACT))
    with pytest.raises(ValueError, match="experiments only"):
        compare(1.0, 0.1, Reference(1.0, CODE, standard_uncertainty=0.1))


def test_check_reference_applies_the_rules_without_a_simulation() -> None:
    # A study manifest calls it on loading, before any value is read.
    check_reference(Reference(1.0, CODE))
    check_reference(experiment(0.025), input_uncertainty=0.1, c=7.0)
    for reference, options, message in (
        (Reference(math.inf, CODE), {}, "finite"),
        (Reference(1.0, EXACT, uncertainty=0.1), {}, "no uncertainty"),
        (Reference(1.0, EXPERIMENT), {}, "experimental uncertainty"),
        (Reference(1.0, CODE), {"input_uncertainty": 0.1}, "experiments only"),
        (Reference(1.0, CODE, standard_uncertainty=0.1), {}, "experiments only"),
        (Reference(1.0, CODE, uncertainty=-0.1), {}, "non-negative"),
        (Reference(1.0, CODE), {"c": 0.5}, "above 1"),
    ):
        with pytest.raises(ValueError, match=message):
            check_reference(reference, **options)


def test_zero_reference_has_no_relative_error() -> None:
    res = compare(0.001, 0.002, Reference(0.0, CODE, uncertainty=0.0))
    assert res.relative_error is None and res.outcome is Outcome.WITHIN


def test_zero_uncertainty_with_an_error_has_no_ratio() -> None:
    res = compare(1.001, 0.0, Reference(1.0, EXACT))
    assert res.outcome is Outcome.OUTSIDE and res.ratio is None
    assert "U_num = 0 < |E|" in res.reasons[0]


def test_compare_result_takes_s_u_and_the_method_from_a_grid_study() -> None:
    gci = grid_convergence([1 + 0.01 * x**2 for x in (1.0, 2.0, 4.0)], h=(1.0, 2.0, 4.0))
    res = compare_result(gci, Reference(1.0, EXACT))
    assert res.simulation == gci.phi[0] and res.numerical == gci.uncertainty
    assert res.outcome is Outcome.WITHIN  # exact p = 2 data: the GCI bounds the error


def test_json() -> None:
    data = json.loads(json.dumps(compare(10.5, 0.6, experiment()).to_dict()))
    assert data["kind"] == "experiment" and data["outcome"] == "within_uncertainty"
    assert data["standard"]["divisor"] == 1.15
