"""Verification report for a grid study: a verdict on each quantity of interest, the checks
behind it and the numbers, as JSON and as Markdown.

build_report() runs assess_study() and turns what it found into one verdict per QoI. A QoI is
a clean pass only when every check holds:

- its grid study (foam_verify.gci): monotonic convergence on grids 1-3 with no warning, so the
  refinement ratios, the observed order, the asymptotic range, the coarser triplets and the
  refinement scope all hold, with the safety factor the stated grid sequence calls for;
- its iterative convergence (foam_verify.iterative): settled on the levels behind the result,
  with u_it at most a hundredth of U;
- the study's settings consistency (foam_verify.consistency): the levels differ only in the
  mesh;
- the study's refined directions d, checked against the patches of every level.

Each check is reported as pass, fail, n/a or assumed, with the numbers behind it, and every
warning that stops a clean pass is quoted word for word. When study.toml gives reference values,
the report also compares each with its QoI's finest-grid value (foam_verify.compare), apart
from the verdict: how far a value is from a reference is a different question from whether it
is converged, and no comparison changes a verdict. render_json() and render_markdown() give
the two forms. Neither holds an absolute path or a time stamp, so a study gives the same report
on any machine. docs/report.md describes the layout.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import __version__
from .compare import Comparison, ReferenceKind
from .consistency import ConsistencyResult
from .gci import (
    SCOPE_NOTES,
    SEQUENCE_NOTES,
    GCIResult,
    GridSequence,
    Method,
    Options,
    Scope,
    Verdict,
)
from .iterative import ContaminationCheck, IterativeResult
from .iterative import Verdict as IterativeVerdict
from .study import (
    MANIFEST,
    QoI,
    QoIComparison,
    QoIResult,
    Study,
    StudyResult,
    assess_study,
    compare_references,
    gci_options,
    iterative_options,
    load_study,
)

SCHEMA = 1


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "n/a"
    ASSUMED = "assumed"


@dataclass(frozen=True)
class Check:
    """One condition behind a verdict: whether it held, and the numbers that say so."""

    name: str
    status: Status
    detail: str


@dataclass(frozen=True)
class QoIVerdict:
    """The verdict on one QoI: its finest-grid value, the uncertainty, and why."""

    name: str
    clean_pass: bool
    value: float
    uncertainty: float | None
    band: tuple[float, float] | None
    # U / |value|; None without an uncertainty or for a zero value.
    relative_uncertainty: float | None
    grid_verdict: Verdict
    method: Method
    checks: tuple[Check, ...]
    # Every reason and warning that stops a clean pass, word for word, study-wide ones included.
    blocking: tuple[str, ...]
    # The QoI as study.toml defines it.
    definition: QoI


@dataclass(frozen=True)
class Report:
    tool: str
    version: str
    schema: int
    study: str
    clean_pass: bool
    summary: str
    layer_cells: float | None
    # The thresholds the grid studies were judged by, the formal order among them.
    criteria: Options
    # What stops every QoI from passing: settings differences and dimension warnings.
    blocking: tuple[str, ...]
    qois: tuple[QoIVerdict, ...]
    # Each reference in study.toml against its QoI, in the manifest's order; outside the verdict.
    comparisons: tuple[QoIComparison, ...]
    # Everything assess_study() found, finest level first.
    result: StudyResult

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        del data["result"]["root"]  # an absolute path, so machine-specific
        return data


def build_report(study: Study, result: StudyResult | None = None) -> Report:
    """The report on a study. result, if given, must be assess_study(study)."""
    res = assess_study(study) if result is None else result
    opt = gci_options(study)
    shared = _study_blocking(res)
    verdicts = tuple(
        _qoi_verdict(q, definition, res, opt, shared, study.layer_cells)
        for q, definition in zip(res.qois, study.qois, strict=True)
    )
    passed = sum(v.clean_pass for v in verdicts)
    return Report(
        tool="foam-verify",
        version=__version__,
        schema=SCHEMA,
        study=res.name,
        clean_pass=bool(verdicts) and passed == len(verdicts),
        summary=_summary(passed, len(verdicts)),
        layer_cells=study.layer_cells,
        criteria=opt,
        blocking=tuple(shared),
        qois=verdicts,
        comparisons=compare_references(study, res),
        result=res,
    )


def verification_report(path: str | Path) -> Report:
    """The report on the study in a folder (or its study.toml)."""
    return build_report(load_study(path))


def render_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2) + "\n"


# --- verdicts ---------------------------------------------------------------------------


def _summary(passed: int, total: int) -> str:
    noun = "quantity" if total == 1 else "quantities"
    verb = "is a clean pass" if passed == 1 else "are clean passes"
    return f"{passed} of {total} {noun} of interest {verb}"


def _study_blocking(res: StudyResult) -> list[str]:
    items = list(res.warnings)
    if res.consistency is None:
        items.append("the settings consistency of the levels was not checked")
    else:
        items.extend(res.consistency.warnings)
    return items


def _qoi_verdict(
    qoi: QoIResult,
    definition: QoI,
    res: StudyResult,
    opt: Options,
    shared: Sequence[str],
    layer_cells: float | None,
) -> QoIVerdict:
    gci = qoi.gci
    check = qoi.contamination
    own: list[str] = []
    if gci.verdict is not Verdict.MONOTONIC:
        own.extend(gci.reasons)
    own.extend(gci.warnings)
    if check is None:
        own.append("the iterative convergence was not checked")
    else:
        own.extend(check.warnings)
    clean = gci.clean_pass and check is not None and check.clean_pass and not shared
    checks = _checks(qoi, definition, res, opt, layer_cells)
    if not clean and not any(c.status is Status.FAIL for c in checks):
        # Every way to fail has a row above; this keeps the table honest if one is missed.
        checks.append(Check("Other", Status.FAIL, "; ".join([*own, *shared])))
    value = qoi.values[0]
    u = gci.uncertainty
    return QoIVerdict(
        name=qoi.name,
        clean_pass=clean,
        value=value,
        uncertainty=u,
        band=gci.band,
        relative_uncertainty=None if u is None or value == 0 else u / abs(value),
        grid_verdict=gci.verdict,
        method=gci.method,
        checks=tuple(checks),
        blocking=(*own, *shared),
        definition=definition,
    )


def _checks(
    qoi: QoIResult, definition: QoI, res: StudyResult, opt: Options, layer_cells: float | None
) -> list[Check]:
    gci = qoi.gci
    used = 2 if gci.r32 is None else 3  # the grids behind the result
    names = [lv.name for lv in res.levels]
    return [
        _convergence_check(gci, used),
        _ratio_check(gci, opt),
        _order_check(gci, opt),
        _asymptotic_check(gci, opt),
        _coarser_check(gci, len(qoi.values)),
        _settled_check(qoi.iterative, names, used, definition),
        _contamination_check(qoi.contamination),
        _consistency_check(res.consistency),
        _dimension_check(res),
        _scope_check(gci, res.scope, layer_cells),
        _sequence_check(gci),
    ]


def _grid_text(res: GCIResult) -> str:
    """A grid verdict in a few words: the convergence type and its key number."""
    rich = res.richardson
    if res.verdict is Verdict.MONOTONIC and rich is not None:
        return f"monotonic, p = {_sig(rich.p, 4)}"
    if res.verdict is Verdict.TWO_GRID:
        return "two grids, p assumed"
    text = {
        Verdict.OSCILLATORY: "oscillatory",
        Verdict.DIVERGENT: "divergence",
        Verdict.DEGENERATE: "degenerate",
        Verdict.ORDER_UNRESOLVED: "order unresolved",
    }.get(res.verdict, res.verdict.value)
    if res.convergence_ratio is not None:
        text += f", R = {_sig(res.convergence_ratio, 4)}"
    return text


def _convergence_check(gci: GCIResult, used: int) -> Check:
    name = "Grid convergence"
    head = f"grids 1-{used}: "
    if gci.verdict is Verdict.MONOTONIC:
        return Check(name, Status.PASS, head + gci.reasons[0])
    detail = "; ".join(gci.reasons)
    if gci.verdict is Verdict.OSCILLATORY:
        detail += "; U is a spread bound, not a Richardson GCI"
    return Check(name, Status.FAIL, head + detail)


def _ratio_check(gci: GCIResult, opt: Options) -> Check:
    ratios = [("r21", gci.r21)] + ([] if gci.r32 is None else [("r32", gci.r32)])
    ok = all(r >= opt.min_refinement_ratio for _, r in ratios)
    shown = ", ".join(f"{name} = {_sig(r, 4)}" for name, r in ratios)
    detail = f"{shown}; at least {opt.min_refinement_ratio:g} (Celik et al. 2008, step 2)"
    return Check("Refinement ratio", Status.PASS if ok else Status.FAIL, detail)


def _solver_text(p_solver: str, iterations: int) -> str:
    if p_solver == "closed_form":
        return "closed form, equal ratios"
    if p_solver == "fixed_point":
        return f"fixed-point iteration, {iterations} steps"
    return f"{p_solver.replace('_', ' ')}, {iterations} steps"


def _order_check(gci: GCIResult, opt: Options) -> Check:
    name = "Observed order"
    rich = gci.richardson
    if rich is None:
        return Check(name, Status.NOT_APPLICABLE, f"not defined: {_grid_text(gci)}")
    if rich.p_solver == "assumed":
        return Check(
            name,
            Status.ASSUMED,
            f"two grids: p is taken as the formal order, {opt.formal_order:g}, with "
            f"Fs = {rich.safety_factor:g} (Roache)",
        )
    lo, hi = opt.p_min, opt.p_max_factor * opt.formal_order
    ok = lo <= rich.p <= hi
    fs = f"Fs = {rich.safety_factor:g}"
    if ok and gci.grid_sequence is GridSequence.UNSTRUCTURED:
        fs += " for an unstructured grid sequence"
    detail = (
        f"p = {_sig(rich.p, 4)} ({_solver_text(rich.p_solver, rich.p_iterations)}), "
        f"{'within' if ok else 'outside'} [{lo:g}, {hi:g}] for a formal order of "
        f"{opt.formal_order:g}; {fs}"
    )
    if _capped(gci):
        detail += f"; U uses p = {gci.order_used:g}, the formal order (ASME V&V 20, Appendix C-4)"
    if gci.verdict is not Verdict.MONOTONIC:
        return Check(name, Status.NOT_APPLICABLE, f"{detail}; for reference only")
    return Check(name, Status.PASS if ok else Status.FAIL, detail)


def _capped(gci: GCIResult) -> bool:
    """Whether U uses a lower order than the observed one (p above the formal order)."""
    rich = gci.richardson
    return (
        rich is not None
        and rich.p_solver != "assumed"
        and gci.order_used is not None
        and gci.order_used < rich.p
    )


def _asymptotic_check(gci: GCIResult, opt: Options) -> Check:
    name = "Asymptotic range"
    rich = gci.richardson
    if gci.verdict is not Verdict.MONOTONIC or rich is None:
        return Check(name, Status.NOT_APPLICABLE, "checked only for monotonic convergence")
    ratio = rich.asymptotic_ratio
    if ratio is None:
        return Check(
            name, Status.FAIL, "GCI_32 / (r21^p GCI_21) is undefined: a solution value is zero"
        )
    lo, hi = opt.asymptotic_band
    ok = lo <= ratio <= hi
    detail = (
        f"GCI_32 / (r21^p GCI_21) = {_sig(ratio, 4)}, {'within' if ok else 'outside'} "
        f"[{lo:g}, {hi:g}]"
    )
    return Check(name, Status.PASS if ok else Status.FAIL, detail)


def _coarser_check(gci: GCIResult, grids: int) -> Check:
    name = "Coarser triplets"
    if len(gci.triplets) < 2:
        return Check(name, Status.NOT_APPLICABLE, f"{grids} grids: no coarser triplet")
    parts = [f"grids {i}-{i + 2}: {_grid_text(t)}" for i, t in enumerate(gci.triplets[1:], start=2)]
    ok = all(t.verdict is Verdict.MONOTONIC for t in gci.triplets[1:])
    return Check(name, Status.PASS if ok else Status.FAIL, "; ".join(parts))


_SETTLED = (IterativeVerdict.CONVERGED, IterativeVerdict.OSCILLATING)


def _settled_check(
    results: Sequence[IterativeResult], names: Sequence[str], used: int, definition: QoI
) -> Check:
    name = "Iterative convergence"
    if len(results) != len(names):
        return Check(name, Status.FAIL, "not checked")
    groups: dict[str, list[str]] = {}
    for label, res in zip(names, results, strict=True):
        groups.setdefault(res.verdict.value.replace("_", " "), []).append(label)
    if len(groups) == 1:
        detail = f"{next(iter(groups))} on every level"
    else:
        detail = "; ".join(f"{verdict} on {', '.join(names)}" for verdict, names in groups.items())
    head = results[:used]
    warned = [label for label, res in zip(names, head, strict=False) if res.warnings]
    if warned:
        detail += f"; warnings on {', '.join(warned)}"
    tol = iterative_options(definition).tol
    detail += f" (tol {tol:g})"
    ok = all(res.verdict in _SETTLED and not res.warnings for res in head)
    return Check(name, Status.PASS if ok else Status.FAIL, detail)


def _contamination_check(check: ContaminationCheck | None) -> Check:
    name = "Iterative error"
    if check is None:
        return Check(name, Status.FAIL, "not checked")
    if check.u_num is None or check.u_num <= 0:
        return Check(name, Status.NOT_APPLICABLE, "no discretisation uncertainty U to compare with")
    if check.worst_ratio is None:
        return Check(
            name, Status.NOT_APPLICABLE, "no level behind the result has an iterative uncertainty"
        )
    ok = check.worst_ratio <= 1 / check.ratio
    detail = (
        f"largest u_it / U = {_small(check.worst_ratio)} ({check.worst_level}), "
        f"{'within' if ok else 'above'} 1/{check.ratio:g} (ASME V&V 20, para. 2-4)"
    )
    return Check(name, Status.PASS if ok else Status.FAIL, detail)


def _consistency_check(check: ConsistencyResult | None) -> Check:
    name = "Settings consistency"
    if check is None:
        return Check(name, Status.FAIL, "not checked")
    files = f"{len(check.files)} files compared"
    if not check.clean_pass:
        more = len(check.warnings) - 1
        detail = check.warnings[0] if check.warnings else "not a clean pass"
        return Check(name, Status.FAIL, detail + (f" (and {more} more)" if more > 0 else ""))
    if not check.differences:
        return Check(name, Status.PASS, f"the levels differ only in the mesh ({files})")
    noted = ", ".join(f"{d.file} {d.key}".strip() for d in check.differences)
    return Check(name, Status.PASS, f"no difference blocks ({files}); noted: {noted}")


def _dimension_check(res: StudyResult) -> Check:
    name = "Refined directions"
    if res.warnings:
        return Check(name, Status.FAIL, "; ".join(res.warnings))
    if res.notes:
        return Check(name, Status.PASS, "; ".join(res.notes))
    patches = sorted({p for lv in res.levels for p in lv.two_d_patches})
    if patches:
        detail = f"dim = {res.dim}, with empty or wedge patches on every level: " + ", ".join(
            patches
        )
    else:
        detail = f"dim = {res.dim}, with no empty, wedge or one-cell-thick patches"
    return Check(name, Status.PASS, detail)


def _scope_check(gci: GCIResult, scope: Scope, layer_cells: float | None) -> Check:
    name = "Refinement scope"
    if scope is Scope.CORE and layer_cells is None and gci.uncertainty is not None:
        warning = next(
            (w for w in gci.warnings if w.startswith("scope core")),
            "refined = core with total cell counts: give layer_cells",
        )
        return Check(name, Status.FAIL, warning)
    return Check(name, Status.ASSUMED, SCOPE_NOTES[scope])


def _sequence_check(gci: GCIResult) -> Check:
    # Stated in study.toml, not read from the mesh: whether the levels refine one grid
    # systematically decides Fs, and nothing on disk shows it reliably.
    return Check("Grid sequence", Status.ASSUMED, SEQUENCE_NOTES[gci.grid_sequence])


# --- Markdown ---------------------------------------------------------------------------


def _sig(x: float, digits: int) -> str:
    """x to a number of significant digits, trailing zeros kept."""
    mantissa, e, exponent = f"{x:#.{digits}g}".partition("e")
    return mantissa.rstrip(".") + (e + exponent if e else "")


def _val(x: float) -> str:
    return _sig(x, 7)


def _small(x: float | None) -> str:
    return "" if x is None else "0" if x == 0 else _sig(x, 2)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{_sig(100 * x, 2)}%"


def _decimals(u: float) -> tuple[float, int]:
    """U to three significant digits, and the decimal place it ends at (negative: tens...)."""
    rounded = float(f"{u:.3g}")
    return rounded, 2 - math.floor(math.log10(rounded))


def _fixed(x: float, decimals: int) -> str:
    return f"{x:.{decimals}f}" if decimals > 0 else f"{round(x, decimals):.0f}"


def _pm(value: float, u: float | None) -> str:
    """The value +/- U, with the value rounded where U's third significant digit ends."""
    if u is None or not u > 0 or not math.isfinite(u):
        return _val(value)
    rounded, decimals = _decimals(u)
    return f"{_fixed(value, decimals)} +/- {_fixed(rounded, decimals)}"


def _band(band: tuple[float, float], u: float) -> str:
    _, decimals = _decimals(u)
    return f"{_fixed(band[0], decimals)} to {_fixed(band[1], decimals)}"


def _code(text: str) -> str:
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def _row(cells: Sequence[str]) -> str:
    """A Markdown table row: pipes escaped, line breaks flattened."""
    escaped = (c.replace("|", "\\|").replace("\n", " ") for c in cells)
    return "| " + " | ".join(escaped) + " |"


def _table(head: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    return [_row(head), "|" + "---|" * len(head), *(_row(r) for r in rows), ""]


def _bullets(items: Sequence[str], title: str | None = None) -> list[str]:
    if not items:
        return []
    return ([f"{title}:", ""] if title else []) + [f"- {item}" for item in items] + [""]


_AXES = "xyz"
_PROFILES = {
    "min": "minimum",
    "max": "maximum",
    "first_crossing": "first change of sign",
    "last_crossing": "last change of sign",
}


def _describe(q: QoI) -> str:
    parts = [_code(q.file)]
    if q.profile is None:
        parts.append(f"column {_code(str(q.column))}")
        if q.component is not None:
            parts.append(f"{_AXES[q.component]} component")
        parts.append("last value" if q.reduction == "last" else "mean over the window")
    else:
        what = "values" if q.component is None else f"{_AXES[q.component]} component"
        axis = _AXES[q.axis if q.axis is not None else 0]
        parts.append(f"{_PROFILES[q.profile]} of the {what} along {axis}, latest profile")
    if q.scale != 1:
        parts.append(f"times {q.scale:g}")
    window = f"the last {100 * q.window:g}% of the samples, at least {q.min_samples}"
    return ", ".join(parts) + f"; window: {window}"


def _level_ratios(gci: GCIResult) -> list[float]:
    """r from each level to the next coarser, finest first, as the grid study computed it."""
    triplets = gci.triplets or (gci,)
    ratios = [t.r21 for t in triplets]
    last = triplets[-1].r32
    return ratios if last is None else [*ratios, last]


def render_markdown(report: Report) -> str:
    res = report.result
    scope = res.scope.value.replace("_", "-")
    lines = [
        f"# Verification report: {res.name}",
        "",
        f"foam-verify {report.version}, from `{MANIFEST}`: {len(res.levels)} levels, finest "
        f"first; refined = {scope}; grid sequence {res.grid_sequence.value}; refined directions "
        f"d = {res.dim}; formal order {report.criteria.formal_order:g}.",
        "",
    ]
    lines += _verdict_section(report)
    lines += _comparison_section(report)
    lines += _levels_section(report)
    lines += _consistency_section(res)
    for verdict, qoi in zip(report.qois, res.qois, strict=True):
        lines += _qoi_section(verdict, qoi, res)
    lines += _method_section(report)
    return "\n".join(lines).rstrip("\n") + "\n"


def _verdict_section(report: Report) -> list[str]:
    head = "Clean pass." if report.clean_pass else "Not a clean pass."
    lines = ["## Verdict", "", f"**{head}** {report.summary[0].upper()}{report.summary[1:]}.", ""]
    rows = [
        [
            _code(v.name),
            _pm(v.value, v.uncertainty),
            _pct(v.relative_uncertainty),
            _grid_text(q.gci),
            "yes" if v.clean_pass else "no",
        ]
        for v, q in zip(report.qois, report.result.qois, strict=True)
    ]
    lines += _table(["QoI", "Finest grid", "Relative U", "Grid convergence", "Clean pass"], rows)
    own = [
        f"{_code(v.name)}: {item}"
        for v in report.qois
        for item in v.blocking
        if item not in report.blocking
    ]
    shared = [f"every QoI: {item}" for item in report.blocking]
    return lines + _bullets([*own, *shared], "What stops a clean pass")


def _against(c: Comparison) -> str:
    """|E| as a multiple of the uncertainty the outcome is judged against, which is named."""
    if c.numerical is None:
        return "n/a"
    name = "U_num" if c.kind is ReferenceKind.EXACT or c.reference_uncertainty is None else "U_val"
    return f"{name} = 0" if c.ratio is None else f"{c.ratio:.3g} {name}"


def _reference_value(c: Comparison) -> str:
    """D, with the reference's U_D when it states one."""
    d = f"{c.reference:.7g}"
    u = c.reference_uncertainty
    return d if not u else f"{d} +/- {_small(u)}"


def _grouped(comparisons: Sequence[QoIComparison], warnings: bool, title: str) -> list[str]:
    """Each warning or note once, after the references and QoIs it applies to."""
    groups: dict[str, dict[str, list[str]]] = {}
    for qc in comparisons:
        items = qc.comparison.warnings if warnings else qc.comparison.notes
        for item in items:
            names = groups.setdefault(item, {}).setdefault(qc.label, [])
            if _code(qc.qoi) not in names:
                names.append(_code(qc.qoi))
    lines = [
        "; ".join(f"{label} on {', '.join(names)}" for label, names in by_label.items())
        + f": {item}"
        for item, by_label in groups.items()
    ]
    return _bullets(lines, title)


def _comparison_section(report: Report) -> list[str]:
    if not report.comparisons:
        return []
    lines = [
        "## Reference comparison",
        "",
        "Apart from the verdict: the comparison error E = S - D sets the finest-grid value S "
        "against a reference value D, every uncertainty at 95%. The verdict says whether S is "
        "converged; this says how far it is from D (foam-verify docs/compare.md).",
        "",
    ]
    rows: list[list[str]] = []
    for qc in report.comparisons:
        c = qc.comparison
        outcome = c.outcome.value.replace("_", " ")
        rows.append(
            [
                _code(qc.qoi),
                qc.label,
                c.kind.value,
                _reference_value(c),
                _sig(c.error, 3),
                _pct(c.relative_error),
                _against(c),
                outcome if c.case is None else f"{outcome} (case {c.case})",
            ]
        )
    head = ["QoI", "Reference", "Kind", "D +/- U_D", "E = S - D", "E / |D|", "|E| / U", "Outcome"]
    lines += _table(head, rows)
    reasons = [
        f"{_code(qc.qoi)} against {qc.comparison.source or 'the reference'}: "
        + "; ".join(qc.comparison.reasons)
        for qc in report.comparisons
    ]
    lines += _bullets(reasons)
    lines += _grouped(report.comparisons, True, "Warnings")
    return lines + _grouped(report.comparisons, False, "Notes")


def _levels_section(report: Report) -> list[str]:
    res = report.result
    ratios = _level_ratios(res.qois[0].gci) if res.qois else []
    core = report.layer_cells
    heights = any(lv.first_layer_height is not None for lv in res.levels)
    head = ["Level", "Folder", "Cells"]
    head += ["Core cells"] if core is not None else []
    head += ["First-layer height"] if heights else []
    head += ["r to the next coarser"]
    rows: list[list[str]] = []
    for i, lv in enumerate(res.levels):
        row = [lv.name, _code(lv.path), f"{lv.cells:,}"]
        if core is not None:
            row.append(f"{lv.cells - core:,.0f}")
        if heights:
            row.append("" if lv.first_layer_height is None else f"{lv.first_layer_height:g}")
        row.append(_sig(ratios[i], 4) if i < len(ratios) else "")
        rows.append(row)
    warnings = [f"Warning: {w}" for w in res.warnings]
    return ["## Levels", "", *_table(head, rows), *_bullets([*warnings, *res.notes])]


def _consistency_section(res: StudyResult) -> list[str]:
    lines = ["## Settings consistency", ""]
    check = res.consistency
    if check is None:
        return [*lines, "Not checked.", ""]
    if not check.clean_pass:
        head = "**Fail.** The levels differ in more than the mesh, or could not be compared."
    elif check.differences:
        head = "**Pass.** No difference blocks a clean pass; the differences below are noted."
    else:
        head = "**Pass.** The levels differ only in the mesh."
    lines += [head, ""]
    if check.files:
        compared = ", ".join(_code(f) for f in check.files)
        lines += [f"Compared on every level: {compared}.", ""]
    if check.differences:
        rows = [
            [
                _code(d.file),
                _code(d.key) if d.key else "(the file)",
                *("(absent)" if v is None else v for v in d.values),
                "yes" if d.blocking else "no",
            ]
            for d in check.differences
        ]
        lines += _table(["File", "Entry", *check.levels, "Blocks"], rows)
    # Each difference also has a sentence in the warnings or notes; the table shows it.
    shown = tuple(
        f"{d.file}: {d.key}: " if d.key else f"{d.file}: present on " for d in check.differences
    )
    warnings = [w for w in check.warnings if not w.startswith(shown)]
    notes = [n for n in check.notes if not n.startswith(shown)]
    return lines + _bullets(warnings, "Warnings") + _bullets(notes, "Notes")


def _qoi_section(v: QoIVerdict, q: QoIResult, res: StudyResult) -> list[str]:
    gci = q.gci
    head = "Clean pass." if v.clean_pass else "Not a clean pass."
    text = _pm(v.value, v.uncertainty)
    if v.uncertainty is not None and v.band is not None:
        how = {
            Method.GCI: "GCI",
            Method.ASSUMED_ORDER_GCI: "GCI at an assumed order",
            Method.SPREAD_BOUND: "spread bound",
        }.get(v.method, v.method.value)
        text += f" ({how}, {_pct(v.relative_uncertainty)}); band {_band(v.band, v.uncertainty)}"
    else:
        text += ", with no uncertainty estimate"
    lines = [f"## {_code(v.name)}", "", f"**{head}** {text}.", ""]
    lines += [f"From {_describe(v.definition)}.", ""]
    lines += _table(
        ["Check", "Result", "Detail"], [[c.name, c.status.value, c.detail] for c in v.checks]
    )

    u = gci.uncertainty
    if len(q.iterative) == len(q.values):
        rows: list[list[str]] = []
        for lv, value, it in zip(res.levels, q.values, q.iterative, strict=True):
            window = f"{it.window} of {it.samples}"
            if it.window_x is not None:
                window += f", {it.window_x[0]:g} to {it.window_x[1]:g}"
            ratio = _small(it.uncertainty / u) if u and it.uncertainty is not None else ""
            rows.append(
                [
                    lv.name,
                    _val(value),
                    it.verdict.value.replace("_", " "),
                    window,
                    _small(it.relative_range),
                    _small(it.relative_drift),
                    _small(it.uncertainty),
                    ratio,
                ]
            )
        head_row = [
            "Level",
            "Value",
            "Iterative",
            "Window",
            "Relative range",
            "Relative drift",
            "u_it",
            "u_it / U",
        ]
        lines += _table(head_row, rows)

    rich = gci.richardson
    if rich is not None:
        grids = "1-2" if gci.r32 is None else "1-3"
        label = f"Richardson extrapolation, grids {grids}"
        if not gci.richardson_used:
            label += " (for reference only, not used for U)"
        elif _capped(gci):
            label += f" (at the observed order; U uses p = {gci.order_used:g})"
        parts = [
            f"phi_ext = {_val(rich.phi_ext)}",
            f"e_a = {_pct(rich.e_a)}",
            f"e_ext = {_pct(rich.e_ext)}",
            f"GCI_fine = {_pct(rich.gci_fine)}",
        ]
        if rich.gci_coarse is not None:
            parts.append(f"GCI_32 = {_pct(rich.gci_coarse)}")
        parts.append(f"Fs = {rich.safety_factor:g}")
        lines += [f"{label}: {', '.join(parts)}.", ""]

    if len(gci.triplets) > 1:
        rows = []
        for i, t in enumerate(gci.triplets, start=1):
            rows.append(
                [
                    f"{i}-{i + 2}",
                    _grid_text(t),
                    _pm(t.phi[0], t.uncertainty),
                    _pct(t.uncertainty / abs(t.phi[0]))
                    if t.uncertainty is not None and t.phi[0] != 0
                    else "n/a",
                ]
            )
        lines += _table(["Grids", "Convergence", "Result", "Relative U"], rows)

    # The scope and sequence notes and the summary of the contamination check are rows of the
    # checks table.
    contamination = [
        n
        for n in (q.contamination.notes if q.contamination is not None else ())
        if not n.startswith(_CONTAMINATION_SUMMARIES)
    ]
    shown = (SCOPE_NOTES[gci.scope], SEQUENCE_NOTES[gci.grid_sequence])
    notes = [n for n in (*gci.notes, *q.notes, *contamination) if n not in shown]
    return lines + _bullets(notes, "Notes")


_CONTAMINATION_SUMMARIES = ("largest u_it / U", "no discretisation uncertainty")


def _method_section(report: Report) -> list[str]:
    o = report.criteria
    lo, hi = o.asymptotic_band
    ratio = next((q.contamination.ratio for q in report.result.qois if q.contamination), 100.0)
    items = [
        f"Grid convergence after Celik et al. (2008), with the convergence types of Eça and "
        f"Hoekstra (2014): Fs = {o.fs_three_grid:g} on three or more grids of a structured grid "
        f"sequence, and {o.fs_fallback:g} for an unstructured sequence (ASME V&V 20, "
        f"para. 2-4.1), on two grids, or when p is outside "
        f"[{o.p_min:g}, {o.p_max_factor * o.formal_order:g}]; refinement ratios of at least "
        f"{o.min_refinement_ratio:g}; an asymptotic-range ratio within [{lo:g}, {hi:g}]; with "
        "four or more grids, every coarser triplet converges monotonically too. Above the formal "
        "order, U uses the formal order (ASME V&V 20, Appendix C-4); the Richardson numbers and "
        "the checks keep the observed p. An oscillatory "
        "triplet gets a spread bound and never a clean pass (foam-verify docs/gci.md).",
        "Iterative convergence of each QoI from its own history over the window given with it: "
        "converged when its relative range and relative drift are within tol, and u_it is half "
        f"the range. On the grids behind the result, u_it must be at most U/{ratio:g} "
        "(ASME V&V 20, para. 2-4; docs/iterative.md).",
        "Settings consistency: the schemes, solver settings, physical properties, boundary "
        "conditions and near-wall layer settings of the levels, compared entry by entry "
        "(docs/consistency.md).",
        "U is the uncertainty of the finest-grid value, and the band is that value +/- U. A QoI "
        "is a clean pass only when no check fails (docs/report.md).",
    ]
    if report.comparisons:
        items.append(
            "Reference comparison, apart from the verdict: |E| against U_num for an exact "
            "reference (a code-verification check); against U_val = sqrt(U_num^2 + U_input^2 + "
            "U_D^2) for a code or experimental reference, or U_num alone, with a warning, when a "
            "code reference states no uncertainty; for an experiment, the case of Eça, Dowding "
            "and Roache (2020) with their constant C (ASME V&V 20; docs/compare.md)."
        )
    return ["## Method", "", *_bullets(items)]
