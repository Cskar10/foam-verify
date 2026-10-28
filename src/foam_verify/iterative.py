"""Iterative convergence of a quantity of interest: has the reported value stopped moving?

Residuals are not the quantity reported. This module reads the history of the QoI itself
(iterations for a steady run, time for a transient one) and measures how much it still changes
over the last window of samples: the relative range, the relative drift of a least-squares
trend, and the iterative uncertainty u_it, half the range. Half the range is the ITTC bound for
an oscillating error (7.5-03-01-01, 2008, section 4.1), taken over the last two periods of the
iteration history in ITTC 7.5-03-02-01 (section 2.3.1). For a grid study, u_it on every level
should be at least an order of magnitude below the discretisation uncertainty (Celik et al.
2008, Appendix A), or iterative error contaminates the GCI.

Every function here is pure arithmetic on numbers the caller supplies; nothing reads files.
docs/iterative.md records each convention and its source, including the ones that are
foam-verify's own choices.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class Verdict(StrEnum):
    CONVERGED = "converged"
    OSCILLATING = "oscillating"
    DRIFTING = "drifting"
    INSUFFICIENT_DATA = "insufficient_data"
    NON_FINITE = "non_finite"
    NO_SCALE = "no_scale"


@dataclass(frozen=True)
class Options:
    # The window: the last `window` fraction of the samples, but at least min_samples of them
    # (the same window as a study QoI's window_mean reduction).
    window: float = 0.1
    min_samples: int = 50
    # Relative range and relative drift both at or below tol: converged.
    tol: float = 1e-3
    # A window with fewer samples than this is not assessed at all.
    min_window: int = 3
    # ITTC 7.5-03-02-01 takes the range over the last two periods of an oscillation. With at
    # least this many full cycles (and at least two) in the window, the drift is the trend of
    # the cycle means, which a steady oscillation does not tilt; see docs/iterative.md.
    min_periods: float = 2.0
    # A window mean at or below round_off_rel * max|phi| is zero: relative values are undefined.
    round_off_rel: float = 1e-10


@dataclass(frozen=True)
class IterativeResult:
    """Iterative convergence of one QoI history.

    Relative values are fractions of `scale`, the window mean's magnitude unless a reference
    magnitude was given. Numbers are None where the verdict leaves them undefined.
    """

    verdict: Verdict
    clean_pass: bool
    samples: int
    window: int
    window_x: tuple[float, float] | None
    mean: float | None
    last: float | None
    minimum: float | None
    maximum: float | None
    scale: float | None
    relative_range: float | None
    # Change of the trend across the window, signed, in the QoI's units: the least-squares
    # line through the samples, or through the cycle means once the window holds enough full
    # cycles of an oscillation (drift_method "least_squares" or "cycle_means").
    drift: float | None
    relative_drift: float | None
    drift_method: str | None
    # Twice the standard error of a cycle-mean drift, from the scatter of the cycle means about
    # their trend; None when there are fewer than three cycles or no cycle means were used.
    drift_noise: float | None
    half_range: float | None
    # Full cycles of oscillation about the least-squares line found in the window.
    cycles: int | None
    # u_it: half the range when the QoI is not drifting. A drifting QoI has none.
    uncertainty: float | None
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContaminationCheck:
    """Iterative uncertainty on each level of a grid study against its discretisation one."""

    clean_pass: bool
    u_num: float | None
    worst_ratio: float | None
    worst_level: str | None
    warnings: tuple[str, ...]
    notes: tuple[str, ...]
    # The margin required: u_it at most U / ratio on every headline level.
    ratio: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def window_size(n: int, window: float, min_samples: int) -> int:
    """Samples in the window: the last `window` fraction of n, but at least min_samples."""
    return min(n, max(math.ceil(window * n), min_samples))


def _check_options(opt: Options) -> None:
    if not 0 < opt.window <= 1:
        raise ValueError("window is a fraction of the samples, in (0, 1]")
    if opt.min_samples < 1 or opt.min_window < 2:
        raise ValueError("min_samples must be at least 1 and min_window at least 2")
    if not opt.tol > 0:
        raise ValueError("tol must be positive")
    if not (opt.min_periods >= 0 and opt.round_off_rel >= 0):
        raise ValueError("min_periods and round_off_rel must be non-negative")


def _fit(
    t: Sequence[float], y: Sequence[float], weights: Sequence[float] | None = None
) -> tuple[float, float | None]:
    """Weighted least-squares slope and its standard error (None below three points)."""
    n = len(t)
    wt = [1.0] * n if weights is None else list(weights)
    sw = math.fsum(wt)
    tm = math.fsum(c * a for c, a in zip(wt, t, strict=True)) / sw
    ym = math.fsum(c * b for c, b in zip(wt, y, strict=True)) / sw
    sxx = math.fsum(c * (a - tm) ** 2 for c, a in zip(wt, t, strict=True))
    slope = math.fsum(c * (a - tm) * (b - ym) for c, a, b in zip(wt, t, y, strict=True)) / sxx
    if n < 3:
        return slope, None
    sse = math.fsum(c * (b - ym - slope * (a - tm)) ** 2 for c, a, b in zip(wt, t, y, strict=True))
    return slope, math.sqrt(sse / (n - 2) / sxx)


def _cycle_means(
    t: Sequence[float], y: Sequence[float], r: Sequence[float]
) -> tuple[list[float], list[float], list[float]]:
    """Centre, mean and length of each full cycle of the oscillation r of y about its trend.

    A cycle runs from one upward crossing of +h to the next, h being half the amplitude of r;
    a crossing counts only after r has been below -h, so noise near the line does not split
    cycles. Crossing times are interpolated between samples and y is integrated as a
    piecewise-linear function between them, so every cycle of a steady oscillation covers the
    same phase and has the same mean.
    """
    h = 0.25 * (max(r) - min(r))
    marks: list[tuple[int, float, float]] = []
    armed = False
    for k, value in enumerate(r):
        if value <= -h:
            armed = True
        elif armed and value >= h:
            f = (h - r[k - 1]) / (value - r[k - 1])
            marks.append((k, t[k - 1] + f * (t[k] - t[k - 1]), y[k - 1] + f * (y[k] - y[k - 1])))
            armed = False
    centres: list[float] = []
    means: list[float] = []
    lengths: list[float] = []
    for (k0, t0, y0), (k1, t1, y1) in zip(marks, marks[1:], strict=False):
        if t1 > t0:
            pts = [(t0, y0), *zip(t[k0:k1], y[k0:k1], strict=True), (t1, y1)]
            area = math.fsum(
                0.5 * (ya + yb) * (tb - ta)
                for (ta, ya), (tb, yb) in zip(pts, pts[1:], strict=False)
            )
            centres.append(0.5 * (t0 + t1))
            means.append(area / (t1 - t0))
            lengths.append(t1 - t0)
    return centres, means, lengths


def iterative_convergence(
    values: Sequence[float],
    x: Sequence[float] | None = None,
    *,
    reference: float | None = None,
    options: Options | None = None,
) -> IterativeResult:
    """Assess the history of one QoI. values are in sample order, oldest first.

    x is the iteration or time of each sample (non-decreasing), or None for the sample index.
    The drift is the change of the trend across the window: a least-squares line through the
    samples, or through the cycle means once the window holds full cycles of an oscillation.
    It is measured in x, so it copes with uneven sampling. reference is a magnitude to divide
    by instead of the window mean, for a QoI whose mean is zero or close to it.
    """
    opt = options or Options()
    _check_options(opt)
    y = tuple(float(v) for v in values)
    n = len(y)
    if x is None:
        xs = tuple(float(i) for i in range(n))
    else:
        xs = tuple(float(v) for v in x)
        if len(xs) != n:
            raise ValueError("x must have one entry per value")
        if not all(math.isfinite(v) for v in xs):
            raise ValueError("x must be finite")
        if any(b < a for a, b in zip(xs, xs[1:], strict=False)):
            raise ValueError("x must be non-decreasing (oldest sample first)")
    if reference is not None and not (math.isfinite(reference) and reference > 0):
        raise ValueError("reference must be a positive finite number")

    def result(verdict: Verdict, reasons: Sequence[str], **kw: Any) -> IterativeResult:
        fields: dict[str, Any] = {
            "clean_pass": False,
            "window": 0,
            "window_x": None,
            "mean": None,
            "last": None,
            "minimum": None,
            "maximum": None,
            "scale": None,
            "relative_range": None,
            "drift": None,
            "relative_drift": None,
            "drift_method": None,
            "drift_noise": None,
            "half_range": None,
            "cycles": None,
            "uncertainty": None,
            "warnings": (),
        }
        fields.update(kw)
        return IterativeResult(verdict=verdict, samples=n, reasons=tuple(reasons), **fields)

    bad = next((i for i, v in enumerate(y) if not math.isfinite(v)), None)
    if bad is not None:
        return result(
            Verdict.NON_FINITE,
            [
                f"sample {bad + 1} of {n} (x = {xs[bad]:g}) is {y[bad]}: the run diverged or "
                "the output is corrupt"
            ],
        )
    m = window_size(n, opt.window, opt.min_samples)
    if m < opt.min_window:
        return result(
            Verdict.INSUFFICIENT_DATA,
            [
                f"{n} sample(s): at least {opt.min_window} are needed to judge iterative "
                "convergence; write the QoI at intervals during the run, not only at the end"
            ],
            window=m,
        )

    w, xw = y[-m:], xs[-m:]
    warnings: list[str] = []
    notes: list[str] = []
    if m < opt.min_samples:
        warnings.append(
            f"only {n} samples, fewer than min_samples = {opt.min_samples}: the window is the "
            "whole history, start-up included, and is too short to judge reliably"
        )
    mean = math.fsum(w) / m
    lo, hi = min(w), max(w)
    spread = hi - lo
    # With every sample at one x (a single write time), fall back to the sample index.
    t = xw if xw[-1] > xw[0] else tuple(float(i) for i in range(m))
    tm = math.fsum(t) / m
    slope = _fit(t, w)[0] if spread > 0 else 0.0
    # A steady oscillation tilts a least-squares line through its samples, by up to about its
    # range divided by the number of periods, depending on phase; its cycle means do not move.
    # Cycles are found about the least-squares line, then again about the cycle-mean trend, so
    # that the crossing level does not creep along a tilted line from cycle to cycle.
    cycles, method, slope_se = 0, "least_squares", None
    if spread > 0:
        trend, trend_se = slope, None
        for _ in range(2):
            about = [b - mean - trend * (a - tm) for a, b in zip(t, w, strict=True)]
            centres, means, lengths = _cycle_means(t, w, about)
            if len(means) < max(2.0, opt.min_periods):
                break
            # Weighted by length: a cycle mean's noise variance falls with its length.
            cycles = len(means)
            trend, trend_se = _fit(centres, means, lengths)
        # A trend that carries the QoI further across the window than its samples range is not
        # in the data: it is noise in a few short cycles, extrapolated. Keep the least squares.
        if cycles and abs(trend) * (t[-1] - t[0]) <= spread:
            slope, slope_se, method = trend, trend_se, "cycle_means"
    resolved = method == "cycle_means"
    length = t[-1] - t[0]
    drift = slope * length
    # Cycle means scatter about their trend when the QoI is noisy; a drift within twice its
    # standard error is not resolved by this window.
    drift_noise = None if slope_se is None else 2 * slope_se * length
    stats: dict[str, Any] = {
        "window": m,
        "window_x": (xw[0], xw[-1]),
        "mean": mean,
        "last": w[-1],
        "minimum": lo,
        "maximum": hi,
        "drift": drift,
        "drift_method": method,
        "drift_noise": drift_noise,
        "half_range": 0.5 * spread,
        "cycles": cycles,
    }

    zero_mean = abs(mean) <= opt.round_off_rel * max(abs(lo), abs(hi))
    if reference is None and zero_mean and spread > 0:
        return result(
            Verdict.NO_SCALE,
            [
                f"the window mean ({mean:.3g}) is zero to round-off, so the relative range and "
                "drift are undefined; give a reference magnitude for this QoI"
            ],
            warnings=tuple(warnings),
            **stats,
        )
    scale = reference if reference is not None else abs(mean)
    rel_range = spread / scale if spread > 0 else 0.0
    rel_drift = drift / scale if spread > 0 else 0.0
    stats.update(scale=scale, relative_range=rel_range, relative_drift=rel_drift)
    measured = (
        f"over the last {m} samples (x = {xw[0]:g} to {xw[-1]:g}): relative range "
        f"{rel_range:.3g}, relative drift {rel_drift:.3g}"
        + (f" (trend of {cycles} cycle means)" if resolved else "")
    )

    unresolved = drift_noise is not None and abs(drift) <= drift_noise
    if abs(rel_drift) > opt.tol and not unresolved:
        if not resolved:
            notes.append(
                "a slow oscillation would also look like drift: if the QoI oscillates with a "
                "period longer than half the window, widen the window to two periods"
            )
        elif drift_noise is None:
            notes.append(
                f"the drift rests on {cycles} cycle means, too few to estimate its noise: if the "
                "QoI is noisy, widen the window to confirm it"
            )
        return result(
            Verdict.DRIFTING,
            [
                f"{measured}; the drift exceeds tol = {opt.tol:g}, so the QoI is still changing",
                "half the range would understate the iterative error of a moving value, so no "
                "iterative uncertainty is given",
            ],
            warnings=tuple(warnings),
            notes=tuple(notes),
            **stats,
        )
    if drift_noise is not None and abs(rel_drift) > opt.tol:  # unresolved, or returned above
        warnings.append(
            f"the drift of the {cycles} cycle means ({rel_drift:.3g}) exceeds tol = "
            f"{opt.tol:g} but is within twice its standard error ({drift_noise / scale:.3g}): "
            "the window cannot tell drift at tol from noise; widen it"
        )
    if rel_range > opt.tol:
        if cycles < opt.min_periods:
            warnings.append(
                f"the window holds {cycles} full cycle(s) of the oscillation; ITTC "
                f"7.5-03-02-01 takes the range over the last {opt.min_periods:g} periods, so "
                "u_it may understate the amplitude and drift cannot be told from a slow "
                "oscillation: widen the window"
            )
        notes.append(
            "u_it is half the range (ITTC 7.5-03-01-01, 2008, section 4.1); if the flow itself "
            "is unsteady, the oscillation is physical rather than iterative"
        )
        return result(
            Verdict.OSCILLATING,
            [f"{measured}; the range exceeds tol = {opt.tol:g} but the drift does not"],
            uncertainty=0.5 * spread,
            warnings=tuple(warnings),
            notes=tuple(notes),
            **stats,
        )
    return result(
        Verdict.CONVERGED,
        [f"{measured}; both at or below tol = {opt.tol:g}"],
        clean_pass=not warnings,
        uncertainty=0.5 * spread,
        warnings=tuple(warnings),
        notes=tuple(notes),
        **stats,
    )


_FAILED = (Verdict.DRIFTING, Verdict.INSUFFICIENT_DATA, Verdict.NON_FINITE, Verdict.NO_SCALE)


def check_contamination(
    results: Sequence[IterativeResult],
    u_num: float | None,
    *,
    names: Sequence[str] | None = None,
    used: int | None = None,
    ratio: float = 10.0,
) -> ContaminationCheck:
    """Compare u_it on each level of a grid study with its discretisation uncertainty u_num.

    results are per level, finest first; the first `used` levels are the ones behind the
    headline result (grids 1-3 of a triplet, both of a two-grid study), and only they can block
    a clean pass: the others are reported in notes, as coarser triplets are. Every headline
    level's u_it is compared with the fine-grid u_num, the smallest discretisation uncertainty:
    an iterative error on any level enters the differences the GCI is built from. ratio is
    the required margin, one order of magnitude by default (Celik et al. 2008, Appendix A).
    """
    if not ratio > 1:
        raise ValueError("ratio must be above 1")
    labels = list(names) if names is not None else [str(i + 1) for i in range(len(results))]
    if len(labels) != len(results):
        raise ValueError("names must have one entry per result")
    used = len(results) if used is None else used
    warnings: list[str] = []
    notes: list[str] = []
    worst: tuple[float, str] | None = None
    compared = False
    for i, (label, res) in enumerate(zip(labels, results, strict=True)):
        headline = i < used
        out = warnings if headline else notes
        tag = "" if headline else " (not in the headline result)"
        if res.verdict in _FAILED:
            out.append(f"level {label}{tag}: {res.verdict.value}: {res.reasons[0]}")
            continue
        out.extend(f"level {label}{tag}: {w}" for w in res.warnings)
        if not headline or u_num is None or u_num <= 0:
            continue
        u_it = res.uncertainty if res.uncertainty is not None else 0.0
        q = u_it / u_num
        compared = True
        if worst is None or q > worst[0]:
            worst = (q, label)
        if q > 1 / ratio:
            warnings.append(
                f"level {label}: u_it = {u_it:.3g} is {q:.3g} of the discretisation uncertainty "
                f"U = {u_num:.3g}, more than 1/{ratio:g} (Celik et al. 2008, Appendix A): "
                "iterative error may contaminate the grid study"
            )
        elif res.verdict is Verdict.OSCILLATING:
            notes.append(
                f"level {label}: oscillating, but u_it = {u_it:.3g} is {q:.3g} of U, below "
                f"1/{ratio:g}"
            )
    if u_num is None or u_num <= 0:
        notes.append("no discretisation uncertainty to compare u_it with")
    elif worst is not None:
        notes.append(
            f"largest u_it / U on the headline levels: {worst[0]:.3g} (level {worst[1]}), "
            f"limit 1/{ratio:g}"
        )
    return ContaminationCheck(
        clean_pass=not warnings and compared,
        u_num=u_num,
        worst_ratio=None if worst is None else worst[0],
        worst_level=None if worst is None else worst[1],
        warnings=tuple(warnings),
        notes=tuple(notes),
        ratio=ratio,
    )
