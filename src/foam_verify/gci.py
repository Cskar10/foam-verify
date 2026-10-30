"""Grid convergence: observed order, Richardson extrapolation and the grid convergence index.

Follows the procedure of Celik et al. (2008), "Procedure for Estimation and Reporting of
Uncertainty Due to Discretization in CFD Applications", J. Fluids Eng. 130(7) 078001, with the
convergence classification of Eca and Hoekstra (2014), J. Comput. Phys. 262, 104-130.

Grid 1 is always the finest. Every function here is pure arithmetic on numbers the caller
supplies; nothing reads files or runs a solver. docs/gci.md records each convention and its
source, including the ones that are foam-verify's own choices.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any


class Verdict(StrEnum):
    MONOTONIC = "monotonic_convergence"
    OSCILLATORY = "oscillatory_convergence"
    DIVERGENT = "divergence"
    DEGENERATE = "degenerate"
    TWO_GRID = "two_grid"
    ORDER_UNRESOLVED = "order_unresolved"


class Scope(StrEnum):
    """Which part of the mesh was refined between levels."""

    MESH = "mesh"  # every cell, near-wall layers included (Celik et al. 2008 assume this)
    CORE = "core"  # core volume only; the near-wall layers were identical on every level
    BOUNDARY_LAYER = "boundary_layer"  # wall-normal layer refinement only; core fixed


SCOPE_NOTES = {
    Scope.MESH: (
        "scope mesh: assumes every cell, near-wall layers included, was refined by the same "
        "ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells)"
    ),
    Scope.CORE: (
        "scope core: the uncertainty covers the core-volume discretisation only; the near-wall "
        "layers were the same on every level, so their discretisation error is not included and "
        "needs its own boundary-layer study"
    ),
    Scope.BOUNDARY_LAYER: (
        "scope boundary_layer: the uncertainty covers wall-normal layer refinement only, with the "
        "core mesh fixed; h should be the first-layer height, with the growth ratio and the "
        "core-transition ratio held constant across levels"
    ),
}


class GridSequence(StrEnum):
    """How the levels were generated: by systematic refinement of one base grid, or not."""

    STRUCTURED = "structured"  # every level refines the same base grid systematically
    UNSTRUCTURED = "unstructured"  # e.g. each level meshed afresh at its own cell size


SEQUENCE_NOTES = {
    GridSequence.STRUCTURED: (
        "grid sequence structured: the levels refine one base grid systematically (the base grid "
        "may itself be unstructured), so Fs = 1.25 with three or more grids (ASME V&V 20, "
        "para. 2-4.1)"
    ),
    GridSequence.UNSTRUCTURED: (
        "grid sequence unstructured: the levels do not refine one grid systematically, so r is "
        "only approximate and Fs = 3 (ASME V&V 20, para. 2-4.1: Fs = 1.25 has not been evaluated "
        "for unstructured refinement)"
    ),
}


class Method(StrEnum):
    """How the uncertainty in the result was obtained."""

    GCI = "gci"
    ASSUMED_ORDER_GCI = "assumed_order_gci"
    SPREAD_BOUND = "spread_bound"
    NONE = "none"


@dataclass(frozen=True)
class Options:
    formal_order: float = 2.0
    # Safety factors (Celik et al. 2008 Eq. 7; Roache for two grids or a doubtful order).
    fs_three_grid: float = 1.25
    fs_fallback: float = 3.0
    # Celik et al. 2008, step 2: "It is desirable that ... r ... be greater than 1.3."
    min_refinement_ratio: float = 1.3
    # GCI_32 / (r21^p GCI_21) should be close to 1 in the asymptotic range.
    asymptotic_band: tuple[float, float] = (0.9, 1.1)
    # An observed order outside [p_min, p_max_factor * formal_order] gets Fs = 3 and a warning.
    p_min: float = 0.5
    p_max_factor: float = 2.0
    # Differences at or below round_off_rel * max|phi| count as zero.
    round_off_rel: float = 1e-10
    p_tol: float = 1e-12
    p_max_iter: int = 500
    # Oscillatory triplets: U = spread_factor * (max - min) / (n_grids - 1). See docs/gci.md.
    spread_factor: float = 3.0
    # U uses min(p, formal_order): ASME V&V 20 (Appendix C-4) limits the p used in the GCI to the
    # theoretical order. The Richardson numbers and the checks keep the observed p.
    cap_order: bool = True


class ObservedOrderError(ArithmeticError):
    """The observed order of accuracy could not be determined."""


@dataclass(frozen=True)
class Richardson:
    """Richardson extrapolation and GCI numbers, as defined in Celik et al. (2008) Eqs. 3-7.

    Relative quantities are fractions, not percent. They are None when the value they are
    relative to is zero.
    """

    p: float
    # How p was obtained: "closed_form" (equal ratios), "fixed_point" or "bisection" when
    # observed, or "assumed" (the formal order, for two grids).
    p_solver: str
    p_iterations: int
    safety_factor: float
    phi_ext: float
    e_a: float | None
    e_ext: float | None
    gci_fine: float | None
    gci_coarse: float | None
    asymptotic_ratio: float | None


@dataclass(frozen=True)
class GCIResult:
    verdict: Verdict
    clean_pass: bool
    method: Method
    phi: tuple[float, ...]
    h: tuple[float, ...]
    r21: float
    r32: float | None
    convergence_ratio: float | None
    # Present whenever the arithmetic is defined. richardson_used says whether the
    # uncertainty below comes from it; for oscillatory triplets it is shown for reference only.
    richardson: Richardson | None
    richardson_used: bool
    uncertainty: float | None
    band: tuple[float, float] | None
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    notes: tuple[str, ...] = ()
    triplets: tuple[GCIResult, ...] = ()
    scope: Scope = Scope.MESH
    grid_sequence: GridSequence = GridSequence.STRUCTURED
    # The order behind the uncertainty: the observed p, the formal order when p is above it (see
    # Options.cap_order) or assumed (two grids); None when U is not a GCI.
    order_used: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def refinement_ratio(n_fine: float, n_coarse: float, dim: int) -> float:
    """r = h_coarse / h_fine = (N_fine / N_coarse)^(1/d) for the same domain."""
    return (n_fine / n_coarse) ** (1.0 / dim)


def divergence_threshold(r21: float, r32: float) -> float:
    """Largest convergence ratio R = eps21/eps32 that still means monotonic convergence.

    For phi = phi0 + c h^p, R = (r21^p - 1) / (r21^p (r32^p - 1)) (Eca and Hoekstra 2014,
    Eq. 3), which falls strictly as p grows, so p > 0 exactly when R < lim_{p->0} R =
    ln r21 / ln r32. With equal ratios this is the familiar R < 1. docs/gci.md has the proof.
    """
    return math.log(r21) / math.log(r32)


def _ln_rp_minus_s(a: float, s: float) -> float:
    """ln(e^a - s) for a = p ln r > 0, without overflow or cancellation."""
    return a + (math.log(-math.expm1(-a)) if s > 0 else math.log1p(math.exp(-a)))


def _order_residual(p: float, ln_ratio: float, ln_r21: float, ln_r32: float, s: float) -> float:
    """Celik et al. (2008) Eq. 3 without its outer absolute value: zero at the observed order."""
    q = _ln_rp_minus_s(p * ln_r21, s) - _ln_rp_minus_s(p * ln_r32, s)
    return p * ln_r21 - ln_ratio - q


def observed_order(
    eps21: float,
    eps32: float,
    r21: float,
    r32: float,
    *,
    tol: float = 1e-12,
    max_iter: int = 500,
) -> tuple[float, int, str]:
    """Observed order p from Celik et al. (2008) Eq. 3, for a convergent triplet.

    Returns (p, iterations, solver). Equal ratios give p in closed form. Otherwise Celik's
    fixed-point iteration runs first, starting from the first term (q = 0). It can diverge
    when r21 and r32 differ a lot, and its absolute value admits a spurious fixed point, so
    its answer is checked against the signed equation, and bisection on that equation (whose
    root is unique) takes over if the check fails. Raises ObservedOrderError if both fail.
    """
    if eps21 == 0 or eps32 == 0:
        raise ObservedOrderError("a solution difference is zero; p is undefined")
    ratio = eps32 / eps21
    s = math.copysign(1.0, ratio)
    ln_r21, ln_r32 = math.log(r21), math.log(r32)
    ln_ratio = math.log(abs(ratio))
    p = abs(ln_ratio) / ln_r21
    if math.isclose(r21, r32, rel_tol=1e-12):
        return p, 0, "closed_form"

    def residual(x: float) -> float:
        return _order_residual(x, ln_ratio, ln_r21, ln_r32, s)

    for k in range(1, max_iter + 1):
        if not 0 < p < 1e4:
            break
        q = _ln_rp_minus_s(p * ln_r21, s) - _ln_rp_minus_s(p * ln_r32, s)
        p_new = abs(ln_ratio + q) / ln_r21
        if abs(p_new - p) <= tol * max(1.0, p_new):
            if abs(residual(p_new)) <= 1e-9:
                return p_new, k, "fixed_point"
            break
        p = p_new

    lo, hi = 1e-12, 1.0
    if residual(lo) >= 0:
        raise ObservedOrderError("the observed order is not positive (p <= 0)")
    while residual(hi) <= 0:
        hi *= 2.0
        if hi > 1e4:
            raise ObservedOrderError("no observed order below p = 1e4")
    for k in range(1, 400):
        mid = 0.5 * (lo + hi)
        if residual(mid) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo <= tol * max(1.0, hi):
            return 0.5 * (lo + hi), k, "bisection"
    raise ObservedOrderError("bisection for p did not converge")


def grid_convergence(
    values: Sequence[float],
    *,
    cells: Sequence[float] | None = None,
    dim: int | None = None,
    h: Sequence[float] | None = None,
    scope: Scope = Scope.MESH,
    grid_sequence: GridSequence = GridSequence.STRUCTURED,
    layer_cells: float | None = None,
    options: Options | None = None,
) -> GCIResult:
    """Assess a grid study. values, cells and h are ordered finest grid first.

    Give either cell counts with the number of refined directions (cells, dim) or
    representative cell sizes (h). Four or more grids give one result per consecutive
    triplet; the returned verdict is the finest triplet's, with all triplets attached.

    scope says which part of the mesh was refined (see Scope). For Scope.CORE with total
    cell counts, layer_cells is the fixed number of near-wall layer cells, subtracted from
    every level so that r measures the core refinement. Scope.BOUNDARY_LAYER needs h
    (first-layer heights): cell counts do not measure wall-normal refinement.

    grid_sequence says how the levels were generated (see GridSequence). An unstructured
    sequence gets Fs = fs_fallback (3) where a structured one gets fs_three_grid (1.25), as
    ASME V&V 20 (para. 2-4.1) recommends.
    """
    opt = options or Options()
    if not opt.formal_order > 0:
        raise ValueError("formal_order must be positive")
    scope = Scope(scope)
    grid_sequence = GridSequence(grid_sequence)
    phi = _finite_tuple(values, "values")
    if len(phi) < 2:
        raise ValueError("a grid study needs at least two grids")
    if layer_cells is not None:
        if scope is not Scope.CORE:
            raise ValueError("layer_cells applies only to scope core")
        if cells is None:
            raise ValueError("layer_cells needs cells (total cell counts)")
        if not 0 <= layer_cells < min(cells):
            raise ValueError("layer_cells must be non-negative and below every cell count")
        cells = [c - layer_cells for c in cells]
    if scope is Scope.BOUNDARY_LAYER and h is None:
        raise ValueError(
            "scope boundary_layer needs h (first-layer heights, finest first): cell counts do "
            "not measure wall-normal refinement"
        )
    sizes = _sizes(len(phi), cells, dim, h)
    extra: list[str] = []
    if scope is Scope.CORE and cells is not None and layer_cells is None:
        extra.append(
            "scope core with total cell counts: the fixed layer cells are counted as refined, "
            "so r understates the core refinement ratio; give layer_cells (0 if negligible)"
        )
    if grid_sequence is GridSequence.UNSTRUCTURED:
        opt = replace(opt, fs_three_grid=opt.fs_fallback)
    return _with_inputs(_assess(phi, sizes, opt), scope, grid_sequence, extra)


def _with_inputs(
    res: GCIResult, scope: Scope, grid_sequence: GridSequence, extra: list[str]
) -> GCIResult:
    # The scope warnings concern the size of an uncertainty estimate, so they are attached only
    # to results that have one: a divergent or degenerate verdict does not depend on them.
    def tag(r: GCIResult) -> GCIResult:
        add = extra if r.uncertainty is not None else []
        return replace(
            r,
            scope=scope,
            grid_sequence=grid_sequence,
            warnings=(*r.warnings, *add),
            clean_pass=r.clean_pass and not add,
        )

    out = tag(res)
    notes = (SCOPE_NOTES[scope], SEQUENCE_NOTES[grid_sequence], *out.notes)
    return replace(out, notes=notes, triplets=tuple(tag(t) for t in res.triplets))


def _assess(phi: tuple[float, ...], sizes: tuple[float, ...], opt: Options) -> GCIResult:
    if len(phi) == 2:
        return _two_grid(phi, sizes, opt)

    triplets = [_triplet(phi[i : i + 3], sizes[i : i + 3], opt) for i in range(len(phi) - 2)]
    finest = triplets[0]
    if len(triplets) == 1:
        return finest
    notes = [
        *finest.notes,
        f"{len(phi)} grids: one result per consecutive triplet; the verdict is from grids 1-3.",
    ]
    # A coarser triplet that does not converge monotonically shows that the grids are not all
    # in the asymptotic range, which the finest triplet's uncertainty assumes; see docs/gci.md.
    blocking: list[str] = []
    for i, t in enumerate(triplets[1:], start=2):
        if t.verdict is Verdict.MONOTONIC:
            continue
        if finest.uncertainty is None:
            notes.append(f"coarser triplet (grids {i}-{i + 2}): {t.verdict.value}")
        else:
            blocking.append(
                f"coarser triplet (grids {i}-{i + 2}): {t.verdict.value}, so the grids are not "
                "all in the asymptotic range; leave out a level that is too coarse rather than "
                "accept grids 1-3 alone"
            )
    return replace(
        finest,
        notes=tuple(notes),
        warnings=(*finest.warnings, *blocking),
        clean_pass=finest.clean_pass and not blocking,
        triplets=tuple(triplets),
    )


def _finite_tuple(xs: Sequence[float], name: str) -> tuple[float, ...]:
    out = tuple(float(x) for x in xs)
    if not all(math.isfinite(x) for x in out):
        raise ValueError(f"{name} must all be finite numbers")
    return out


def _sizes(
    n: int, cells: Sequence[float] | None, dim: int | None, h: Sequence[float] | None
) -> tuple[float, ...]:
    if (cells is None) == (h is None):
        raise ValueError("give exactly one of cells (with dim) or h")
    if h is not None:
        sizes = _finite_tuple(h, "h")
        if len(sizes) != n:
            raise ValueError("h must have one entry per value")
        if sizes[0] <= 0 or any(b <= a for a, b in zip(sizes, sizes[1:], strict=False)):
            raise ValueError("h must be positive and strictly increasing (finest grid first)")
        return sizes
    assert cells is not None
    if dim not in (1, 2, 3):
        raise ValueError("dim (number of refined directions) must be 1, 2 or 3")
    counts = _finite_tuple(cells, "cells")
    if len(counts) != n:
        raise ValueError("cells must have one entry per value")
    if counts[-1] <= 0 or any(b >= a for a, b in zip(counts, counts[1:], strict=False)):
        raise ValueError("cells must be positive and strictly decreasing (finest grid first)")
    # Same domain on every level, so h_i / h_1 = (N_1 / N_i)^(1/d).
    return tuple(refinement_ratio(counts[0], c, dim) for c in counts)


def _ratio_warnings(ratios: Sequence[tuple[str, float]], opt: Options) -> list[str]:
    return [
        f"{name} = {r:.4g} is below {opt.min_refinement_ratio:g} (Celik et al. 2008 step 2): "
        "the grids are too similar for a reliable estimate"
        for name, r in ratios
        if r < opt.min_refinement_ratio
    ]


def _relative(num: float, den: float) -> float | None:
    return abs(num / den) if den != 0 else None


def _band(phi1: float, u: float) -> tuple[float, float]:
    return (phi1 - u, phi1 + u)


def _p_in_range(p: float, opt: Options) -> bool:
    return opt.p_min <= p <= opt.p_max_factor * opt.formal_order


def _richardson(
    phi: tuple[float, ...],
    r21: float,
    r32: float | None,
    p: float,
    p_solver: str,
    iterations: int,
    fs: float,
) -> Richardson:
    phi1, phi2 = phi[0], phi[1]
    r21p = r21**p
    phi_ext = (r21p * phi1 - phi2) / (r21p - 1.0)
    e_a = _relative(phi1 - phi2, phi1)
    e_ext = _relative(phi_ext - phi1, phi_ext)
    gci_fine = fs * e_a / (r21p - 1.0) if e_a is not None else None
    gci_coarse = asymptotic = None
    if r32 is not None:
        e_a32 = _relative(phi2 - phi[2], phi2)
        if e_a32 is not None:
            gci_coarse = fs * e_a32 / (r32**p - 1.0)
            if gci_fine:
                asymptotic = gci_coarse / (r21p * gci_fine)
    return Richardson(
        p=p,
        p_solver=p_solver,
        p_iterations=iterations,
        safety_factor=fs,
        phi_ext=phi_ext,
        e_a=e_a,
        e_ext=e_ext,
        gci_fine=gci_fine,
        gci_coarse=gci_coarse,
        asymptotic_ratio=asymptotic,
    )


def _two_grid(phi: tuple[float, ...], h: tuple[float, ...], opt: Options) -> GCIResult:
    r21 = h[1] / h[0]
    eps21 = phi[1] - phi[0]
    warnings = _ratio_warnings([("r21", r21)], opt)
    if abs(eps21) <= opt.round_off_rel * max(abs(x) for x in phi):
        return GCIResult(
            verdict=Verdict.DEGENERATE,
            clean_pass=False,
            method=Method.NONE,
            phi=phi,
            h=h,
            r21=r21,
            r32=None,
            convergence_ratio=None,
            richardson=None,
            richardson_used=False,
            uncertainty=None,
            band=None,
            reasons=(
                "the two solutions agree to round-off, so there is no difference to "
                "extrapolate from; add a third grid",
            ),
            warnings=tuple(warnings),
        )
    p = opt.formal_order
    fs = opt.fs_fallback
    rich = _richardson(phi, r21, None, p, "assumed", 0, fs)
    u = fs * abs(eps21) / (r21**p - 1.0)
    warnings.append(
        f"only two grids: the observed order cannot be estimated, so the GCI assumes the formal "
        f"order p = {p:g} with Fs = {fs:g} (Roache); a third grid is needed to check it"
    )
    return GCIResult(
        verdict=Verdict.TWO_GRID,
        clean_pass=False,
        method=Method.ASSUMED_ORDER_GCI,
        phi=phi,
        h=h,
        r21=r21,
        r32=None,
        convergence_ratio=None,
        richardson=rich,
        richardson_used=True,
        uncertainty=u,
        band=_band(phi[0], u),
        reasons=("two-grid estimate at an assumed order of accuracy",),
        warnings=tuple(warnings),
        order_used=p,
    )


def _triplet(phi: tuple[float, ...], h: tuple[float, ...], opt: Options) -> GCIResult:
    phi1, phi2, phi3 = phi
    r21, r32 = h[1] / h[0], h[2] / h[1]
    eps21, eps32 = phi2 - phi1, phi3 - phi2
    warnings = _ratio_warnings([("r21", r21), ("r32", r32)], opt)
    zero = opt.round_off_rel * max(abs(x) for x in phi)

    def result(verdict: Verdict, reasons: Sequence[str], **kw: Any) -> GCIResult:
        fields: dict[str, Any] = {
            "clean_pass": False,
            "method": Method.NONE,
            "convergence_ratio": None,
            "richardson": None,
            "richardson_used": False,
            "uncertainty": None,
            "band": None,
            "warnings": tuple(warnings),
        }
        fields.update(kw)
        return GCIResult(
            verdict=verdict, phi=phi, h=h, r21=r21, r32=r32, reasons=tuple(reasons), **fields
        )

    if abs(eps21) <= zero or abs(eps32) <= zero:
        which = [
            name
            for name, eps in (("phi2 - phi1", eps21), ("phi3 - phi2", eps32))
            if abs(eps) <= zero
        ]
        return result(
            Verdict.DEGENERATE,
            [
                f"{' and '.join(which)} is zero to round-off, so the observed order is undefined "
                "(Celik et al. 2008, step 3)",
                "this can mean oscillatory convergence or a discretisation that reproduces the "
                "exact solution; refine further or report the values as they are",
            ],
        )

    R = eps21 / eps32
    limit = divergence_threshold(r21, r32) if R > 0 else 1.0
    if abs(R) >= limit:
        kind = "monotonic" if R > 0 else "oscillatory"
        test = "|R| >= 1" if math.isclose(limit, 1.0) else f"R >= ln r21 / ln r32 = {limit:.4g}"
        return result(
            Verdict.DIVERGENT,
            [
                f"convergence ratio R = (phi2 - phi1)/(phi3 - phi2) = {R:.4g}: {test}, "
                f"{kind} divergence (Eca and Hoekstra 2014)",
                "the solution is not grid-converged, so no GCI is given",
            ],
            convergence_ratio=R,
        )

    try:
        p, iterations, solver = observed_order(
            eps21, eps32, r21, r32, tol=opt.p_tol, max_iter=opt.p_max_iter
        )
    except ObservedOrderError as exc:
        return result(
            Verdict.ORDER_UNRESOLVED,
            [f"observed order of accuracy could not be determined: {exc}"],
            convergence_ratio=R,
        )

    p_ok = _p_in_range(p, opt)
    fs = opt.fs_three_grid if p_ok else opt.fs_fallback
    rich = _richardson(phi, r21, r32, p, solver, iterations, fs)
    if not p_ok:
        warnings.append(
            f"observed order p = {p:.4g} is outside [{opt.p_min:g}, "
            f"{opt.p_max_factor * opt.formal_order:g}] for a formal order of "
            f"{opt.formal_order:g}, so Fs = {fs:g} is used"
        )

    if R > 0:
        lo, hi = opt.asymptotic_band
        a = rich.asymptotic_ratio
        if a is None:
            warnings.append("asymptotic-range ratio is undefined (a solution value is zero)")
        elif not lo <= a <= hi:
            warnings.append(
                f"asymptotic-range ratio GCI_32/(r21^p GCI_21) = {a:.4g} is outside "
                f"[{lo:g}, {hi:g}]: the grids may not be in the asymptotic range"
            )
        # Above the formal order, U uses the formal order; p within round-off of it is not "above".
        capped = opt.cap_order and p > opt.formal_order * (1.0 + 1e-9)
        p_u = opt.formal_order if capped else p
        u = fs * abs(eps21) / (r21**p_u - 1.0)
        notes: list[str] = []
        if capped:
            notes.append(
                f"observed order p = {p:.4g} is above the formal order {opt.formal_order:g}, so "
                f"the uncertainty uses p = {p_u:g} (ASME V&V 20, Appendix C-4); the Richardson "
                "numbers and the asymptotic-range check use the observed p"
            )
        return result(
            Verdict.MONOTONIC,
            [f"convergence ratio R = {R:.4g}: monotonic convergence (0 < R < {limit:.4g})"],
            clean_pass=not warnings,
            method=Method.GCI,
            convergence_ratio=R,
            richardson=rich,
            richardson_used=True,
            uncertainty=u,
            band=_band(phi1, u),
            notes=tuple(notes),
            order_used=p_u,
        )

    spread = max(phi) - min(phi)
    u = opt.spread_factor * spread / (len(phi) - 1)
    warnings.append(
        "oscillatory convergence: the Richardson GCI assumes monotonic behaviour, so the "
        f"uncertainty is a spread bound, {opt.spread_factor:g} x (max - min)/(n - 1), and the "
        "Richardson numbers are shown for reference only"
    )
    return result(
        Verdict.OSCILLATORY,
        [f"convergence ratio R = {R:.4g}: oscillatory convergence (-1 < R < 0)"],
        method=Method.SPREAD_BOUND,
        convergence_ratio=R,
        richardson=rich,
        uncertainty=u,
        band=_band(phi1, u),
    )
