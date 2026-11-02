"""Comparison with reference data: the comparison error E = S - D, and what it can say.

ASME V&V 20 (para. 1-5) defines the comparison error E = S - D between a simulation value S and
a reference value D. What E means depends on the reference, so every comparison names its kind:

- exact: an exact or analytical solution of the same equations. The reference has no error and
  the model error is zero by construction, so E is the numerical error itself. Comparing it
  with the numerical uncertainty is a code-verification check (V&V 20, para. 1-6: error
  evaluation from a known benchmark solution): does the stated uncertainty bound the error?
- code: another numerical solution of the same equations (code-to-code). E is the difference
  of two numerical errors and says nothing about the model.
- experiment: measured data. Only this is validation in V&V 20's sense (para. 1-1: "There can
  be no validation without experimental data").

Every uncertainty here is a 95% expanded uncertainty. U_num is the grid study's U as it is: the
GCI is a 95% uncertainty with no distribution assumed (V&V 20, para. 2-4.1). Independent
components combine as U_val = sqrt(U_num^2 + U_input^2 + U_D^2) (Eça, Dowding and Roache 2020,
Eq. 15). For an experiment, the outcome follows their algorithmic reading of V&V 20 with the
constant C, and the standard uncertainty u_num is given as well, with its divisor (V&V 20,
eqs. 2-4-13 and 2-4-14). docs/compare.md records each rule and its source.

Every function here is pure arithmetic on numbers the caller supplies; nothing reads files.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .gci import GCIResult, Method


class ReferenceKind(StrEnum):
    EXACT = "exact"
    CODE = "code"
    EXPERIMENT = "experiment"


class Outcome(StrEnum):
    # |E| within the uncertainty that applies: U_num for an exact reference, U_val otherwise
    # (U_num alone when a code reference states no uncertainty). For an experiment: Eça,
    # Dowding and Roache's cases 3b and 2, a model error that the comparison cannot resolve.
    WITHIN = "within_uncertainty"
    # |E| beyond it. For an experiment, case 3a: the model error has the sign of E.
    OUTSIDE = "outside_uncertainty"
    # Experiments only, case 1: |E| > C U_val, so the model error is E.
    MODEL_ERROR = "model_error"
    # No numerical uncertainty (a divergent or degenerate grid study): E cannot be judged.
    NO_UNCERTAINTY = "no_uncertainty"


@dataclass(frozen=True)
class Reference:
    """A reference value D and what it is.

    uncertainty is the reference's 95% expanded uncertainty U_D: None when the source states
    none, and always 0 for an exact reference. standard_uncertainty is u_D, for an experiment
    that states it. source says where the value comes from (a citation, a function, a table).
    """

    value: float
    kind: ReferenceKind
    uncertainty: float | None = None
    standard_uncertainty: float | None = None
    source: str = ""


@dataclass(frozen=True)
class StandardUncertainty:
    """The numerical standard uncertainty u_num = U_num / divisor, for an experiment."""

    numerical: float
    divisor: float
    basis: str
    # u_val = sqrt(u_num^2 + u_D^2) when the experiment states u_D and U_input is zero.
    validation: float | None


@dataclass(frozen=True)
class Comparison:
    kind: ReferenceKind
    outcome: Outcome
    simulation: float
    reference: float
    # E = S - D, and E / |D| (None when D is zero).
    error: float
    relative_error: float | None
    # 95% expanded uncertainties: U_num, U_input, U_D (None when the reference states none) and
    # U_val, their root sum of squares (None when U_D or U_num is missing).
    numerical: float | None
    input: float
    reference_uncertainty: float | None
    validation: float | None
    # |E| divided by the uncertainty the outcome is judged against; None when that is zero.
    ratio: float | None
    # A code or experimental reference that states no uncertainty, with |E| above U_num: the
    # smallest U_D that would bring |E| within U_val, sqrt(E^2 - U_num^2).
    needed: float | None
    # Experiments only: Eça, Dowding and Roache's case (1, 3a, 3b or 2), the bound on the model
    # error, its sign (+1 or -1, None when unknown), and the constant C used.
    case: str | None
    model_error_bound: float | None
    model_error_sign: int | None
    c: float | None
    standard: StandardUncertainty | None
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    notes: tuple[str, ...]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_C = 10.0

# The divisor from U_num to u_num (ASME V&V 20, para. 2-4.1). A monotonic GCI's error is roughly
# Gaussian about the extrapolated value, which gives k = 1.1 to 1.15 (eq. 2-4-14; 1.15 is the
# conservative end); an oscillatory one's about the fine-grid value, k = 2 (eq. 2-4-13). The
# standard says nothing for two grids: 1.15 gives the larger, conservative u_num.
_DIVISORS = {
    Method.GCI: (1.15, "ASME V&V 20, eq. 2-4-14: monotonic convergence, k = 1.1 to 1.15"),
    Method.ASSUMED_ORDER_GCI: (
        1.15,
        "two grids: ASME V&V 20 gives no divisor; 1.15, the conservative end of eq. 2-4-14",
    ),
    Method.SPREAD_BOUND: (2.0, "ASME V&V 20, eq. 2-4-13: oscillatory convergence, k = 2"),
}


def _non_negative(x: float | None, name: str) -> None:
    if x is not None and not (math.isfinite(x) and x >= 0):
        raise ValueError(f"{name} must be a finite, non-negative number")


def _sig(x: float) -> str:
    return f"{x:.3g}"


def _ratio(error: float, uncertainty: float) -> float | None:
    """|E| / U, 0 for no error, None when U is zero and E is not."""
    if error == 0:
        return 0.0
    return abs(error) / uncertainty if uncertainty > 0 else None


def _times(ratio: float | None, name: str) -> str:
    return f"|E| = {_sig(ratio)} {name}" if ratio is not None else f"{name} = 0 < |E|"


def check_reference(
    reference: Reference, *, input_uncertainty: float = 0.0, c: float = DEFAULT_C
) -> None:
    """Raise ValueError when a reference, with the options to compare with it, is unusable.

    compare() calls this; a study manifest calls it too, so a bad reference fails on loading.
    """
    kind = ReferenceKind(reference.kind)
    if not math.isfinite(reference.value):
        raise ValueError("the reference value must be finite")
    _non_negative(reference.uncertainty, "the reference uncertainty")
    _non_negative(reference.standard_uncertainty, "the reference standard uncertainty")
    _non_negative(input_uncertainty, "the input uncertainty")
    if not (math.isfinite(c) and c > 1):
        raise ValueError("c must be a finite number above 1")
    if kind is ReferenceKind.EXACT and (reference.uncertainty or reference.standard_uncertainty):
        raise ValueError("an exact reference has no uncertainty")
    if kind is not ReferenceKind.EXPERIMENT and input_uncertainty:
        raise ValueError(
            "input uncertainty applies to experiments only: an exact or code reference solves "
            "the same problem with the same inputs"
        )
    if kind is ReferenceKind.EXPERIMENT and not reference.uncertainty:
        raise ValueError(
            "an experimental reference needs its 95% uncertainty, above zero: V&V 20 cannot be "
            "applied without the experimental uncertainty"
        )
    if reference.standard_uncertainty is not None and kind is not ReferenceKind.EXPERIMENT:
        raise ValueError("a standard uncertainty for the reference applies to experiments only")


def compare(
    simulation: float,
    numerical: float | None,
    reference: Reference,
    *,
    method: Method = Method.GCI,
    input_uncertainty: float = 0.0,
    c: float = DEFAULT_C,
) -> Comparison:
    """Compare a simulation value S, with its 95% numerical uncertainty U_num, to a reference.

    method is how U_num was obtained (foam_verify.gci.Method); it sets the divisor for the
    standard uncertainty of an experiment comparison. input_uncertainty is U_input at 95%, for
    experiments only: an exact or code reference solves the same problem with the same inputs.
    c is Eça, Dowding and Roache's constant for experiments, 10 by default ("typically", one
    order of magnitude); they cite 7 for problems without high-risk decisions.
    """
    kind = ReferenceKind(reference.kind)
    method = Method(method)
    if not math.isfinite(simulation):
        raise ValueError("simulation must be finite")
    _non_negative(numerical, "the numerical uncertainty")
    check_reference(reference, input_uncertainty=input_uncertainty, c=c)

    d = reference.value
    e = simulation - d
    u_d = 0.0 if kind is ReferenceKind.EXACT else reference.uncertainty
    base: dict[str, Any] = {
        "kind": kind,
        "simulation": simulation,
        "reference": d,
        "error": e,
        "relative_error": None if d == 0 else e / abs(d),
        "numerical": numerical,
        "input": input_uncertainty,
        "reference_uncertainty": u_d,
        "validation": None,
        "ratio": None,
        "needed": None,
        "case": None,
        "model_error_bound": None,
        "model_error_sign": None,
        "c": None,
        "standard": None,
        "source": reference.source,
    }
    notes: list[str] = []
    warnings: list[str] = []

    def done(outcome: Outcome, reasons: Sequence[str], **extra: Any) -> Comparison:
        fields: dict[str, Any] = {**base, **extra}
        return Comparison(
            outcome=outcome,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
            notes=tuple(notes),
            **fields,
        )

    if kind is ReferenceKind.EXPERIMENT and not input_uncertainty:
        notes.append(
            "U_input = 0: the simulation inputs are taken as exact, so any error from them is "
            "part of the model error (V&V 20, para. 1-5)"
        )
    if numerical is None:
        return done(
            Outcome.NO_UNCERTAINTY,
            [
                f"E = S - D = {_sig(e)}, but the grid study gives no numerical uncertainty, so "
                "E cannot be judged"
            ],
        )

    if kind is ReferenceKind.EXACT:
        ratio = _ratio(e, numerical)
        within = abs(e) <= numerical
        reason = (
            f"the reference is exact, so E = S - D = {_sig(e)} is the numerical error itself; "
            f"{_times(ratio, 'U_num')}, so the numerical uncertainty "
            + ("bounds it" if within else "does not bound it: U_num is not conservative here")
        )
        notes.append("an exact reference makes this a code-verification check (V&V 20, para. 1-6)")
        outcome = Outcome.WITHIN if within else Outcome.OUTSIDE
        return done(outcome, [reason], validation=numerical, ratio=ratio)

    if u_d is None:  # a code reference that states no uncertainty
        ratio = _ratio(e, numerical)
        within = abs(e) <= numerical
        needed = None if within else math.sqrt(e * e - numerical * numerical)
        if within:
            reason = (
                f"E = S - D = {_sig(e)} is within the simulation's numerical uncertainty alone "
                f"({_times(ratio, 'U_num')})"
            )
        else:
            reason = (
                f"E = S - D = {_sig(e)} is beyond the simulation's numerical uncertainty "
                f"({_times(ratio, 'U_num')}); the reference states no uncertainty, and would "
                f"need one of at least {_sig(needed or 0.0)} for the two to agree"
            )
        warnings.append("the reference states no uncertainty, so U_val is incomplete")
        notes.append(
            "a code reference makes this a code-to-code comparison: E is the difference of two "
            "numerical errors and says nothing about the model"
        )
        outcome = Outcome.WITHIN if within else Outcome.OUTSIDE
        return done(outcome, [reason], ratio=ratio, needed=needed)

    u_val = math.sqrt(numerical**2 + input_uncertainty**2 + u_d**2)
    ratio = _ratio(e, u_val)
    combined = (
        f"U_val = sqrt(U_num^2 + U_input^2 + U_D^2) = {_sig(u_val)} "
        "(Eça, Dowding and Roache 2020, Eq. 15: independent errors)"
    )
    if kind is ReferenceKind.CODE:
        within = abs(e) <= u_val
        reason = f"E = S - D = {_sig(e)}, {_times(ratio, 'U_val')}: " + (
            "the two solutions agree within their numerical uncertainties"
            if within
            else "the two solutions differ by more than their numerical uncertainties"
        )
        notes.append(
            "a code reference makes this a code-to-code comparison: E is the difference of two "
            "numerical errors and says nothing about the model"
        )
        outcome = Outcome.WITHIN if within else Outcome.OUTSIDE
        return done(outcome, [reason, combined], validation=u_val, ratio=ratio)

    # Experiment: Eça, Dowding and Roache (2020), the algorithmic version of V&V 20's outcome.
    # At |E| = U_val their Figure 1 puts case 3a (|E| >= U_val); at |E| = U_val / C, case 3b.
    # U_val > 0 here: an experimental reference has a non-zero uncertainty.
    a = abs(e)
    sign = 1 if e > 0 else -1
    if a > c * u_val:
        case, outcome, bound, known = "1", Outcome.MODEL_ERROR, a, sign
        reading = f"|E| > C U_val, so the model error is E = {_sig(e)}"
    elif a >= u_val:
        case, outcome, bound, known = "3a", Outcome.OUTSIDE, a + u_val, sign
        reading = (
            f"U_val <= |E| <= C U_val: |model error| < |E| + U_val = {_sig(a + u_val)}, with the "
            "sign of E"
        )
    elif a >= u_val / c:
        case, outcome, bound, known = "3b", Outcome.WITHIN, a + u_val, None
        reading = (
            f"U_val / C <= |E| < U_val: |model error| < |E| + U_val = {_sig(a + u_val)}, sign "
            "unknown"
        )
    else:
        case, outcome, bound, known = "2", Outcome.WITHIN, u_val, None
        reading = f"|E| < U_val / C: |model error| < U_val = {_sig(u_val)}, sign unknown"
    divisor, basis = _DIVISORS[method]
    u_num = numerical / divisor
    u_val_std = None
    if reference.standard_uncertainty is not None:
        if input_uncertainty:
            notes.append("u_val is not formed: the input uncertainty is given at 95% only")
        else:
            u_val_std = math.sqrt(u_num**2 + reference.standard_uncertainty**2)
    notes.append(
        f"standard uncertainty for combining with experimental data: u_num = U_num / "
        f"{divisor:g} = {_sig(u_num)} ({basis})"
    )
    return done(
        outcome,
        [
            f"E = S - D = {_sig(e)}, {_times(ratio, 'U_val')}; case {case} with C = {c:g}: "
            f"{reading} (Eça, Dowding and Roache 2020)",
            combined,
        ],
        validation=u_val,
        ratio=ratio,
        case=case,
        model_error_bound=bound,
        model_error_sign=known,
        c=c,
        standard=StandardUncertainty(u_num, divisor, basis, u_val_std),
    )


def compare_result(
    result: GCIResult,
    reference: Reference,
    *,
    input_uncertainty: float = 0.0,
    c: float = DEFAULT_C,
) -> Comparison:
    """compare() with S, U_num and the method taken from a grid study's result."""
    return compare(
        result.phi[0],
        result.uncertainty,
        reference,
        method=result.method,
        input_uncertainty=input_uncertainty,
        c=c,
    )
