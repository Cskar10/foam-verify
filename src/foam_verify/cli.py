"""Command line interface: foam-verify gci and foam-verify report.

Exit codes: 0 for a clean pass, 1 when the verdict is anything else, 2 for bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .gci import GCIResult, GridSequence, Options, Scope, grid_convergence
from .report import render_json, render_markdown, verification_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="foam-verify", description="Read-only verification of OpenFOAM results."
    )
    parser.add_argument("--version", action="version", version=f"foam-verify {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    gci = sub.add_parser(
        "gci",
        help="grid convergence index from values and grid sizes",
        description="Grid convergence from values on two or more grids, finest grid first.",
    )
    gci.add_argument("--values", type=float, nargs="+", required=True, metavar="PHI")
    sizes = gci.add_mutually_exclusive_group(required=True)
    sizes.add_argument("--cells", type=float, nargs="+", metavar="N", help="cell counts")
    sizes.add_argument("--h", type=float, nargs="+", metavar="H", help="representative sizes")
    gci.add_argument(
        "--dim", type=int, choices=(1, 2, 3), help="refined directions (required with --cells)"
    )
    gci.add_argument(
        "--refined",
        required=True,
        choices=("mesh", "core", "boundary-layer"),
        help="what was refined between levels: the whole mesh including near-wall layers, the "
        "core volume only (layers identical on every level), or the near-wall layers only "
        "(core fixed; give first-layer heights with --h)",
    )
    gci.add_argument(
        "--grid-sequence",
        required=True,
        choices=tuple(s.value for s in GridSequence),
        help="how the levels were generated: by systematic refinement of one base grid, with "
        "geometrically similar cells (structured), or not, for example each level meshed afresh "
        "(unstructured); unstructured refinement gets Fs = 3 (ASME V&V 20, para. 2-4.1)",
    )
    gci.add_argument(
        "--layer-cells",
        type=float,
        metavar="N",
        help="with --refined core and --cells: the fixed number of layer cells, subtracted "
        "from every level so that r measures the core refinement",
    )
    gci.add_argument("--formal-order", type=float, default=2.0, metavar="P")
    gci.add_argument("--json", action="store_true", help="print the full result as JSON")

    report = sub.add_parser(
        "report",
        help="verification report on a grid study (a folder with study.toml)",
        description="Verification report on a grid study: a verdict on each quantity of "
        "interest, the checks behind it and the numbers. Printed as Markdown unless --json or "
        "--output is given.",
    )
    report.add_argument("study", metavar="STUDY", help="the study folder, or its study.toml")
    out = report.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="print the report as JSON")
    out.add_argument(
        "-o",
        "--output",
        metavar="DIR",
        help="write report.md and report.json into DIR instead of printing",
    )
    return parser


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.4g}%"


def _num(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.6g}"


def format_result(res: GCIResult) -> str:
    status = "clean pass" if res.clean_pass else "not a clean pass"
    lines = [
        f"verdict: {res.verdict.value} ({status})",
        f"refined: {res.scope.value}",
        f"grid sequence: {res.grid_sequence.value}",
    ]
    ratios = f"r21 = {res.r21:.4g}" + (f", r32 = {res.r32:.4g}" if res.r32 is not None else "")
    if res.convergence_ratio is not None:
        ratios += f", R = {res.convergence_ratio:.4g}"
    lines.append(f"grids: {len(res.phi)}, {ratios}")
    rich = res.richardson
    if rich is not None:
        tag = "" if res.richardson_used else " (reference only, not used)"
        how = (
            "assumed formal order"
            if rich.p_solver == "assumed"
            else f"{rich.p_solver}, {rich.p_iterations} iterations"
        )
        lines.append(f"richardson{tag}:")
        lines.append(f"  p = {rich.p:.4g} ({how}), Fs = {rich.safety_factor:g}")
        lines.append(f"  phi_ext = {_num(rich.phi_ext)}")
        lines.append(
            f"  e_a = {_pct(rich.e_a)}, e_ext = {_pct(rich.e_ext)}, "
            f"GCI_fine = {_pct(rich.gci_fine)}, GCI_32 = {_pct(rich.gci_coarse)}"
        )
        if rich.asymptotic_ratio is not None:
            lines.append(f"  asymptotic-range ratio = {rich.asymptotic_ratio:.4g}")
    if res.uncertainty is not None:
        lines.append(
            f"result: {_num(res.phi[0])} +/- {_num(res.uncertainty)} (method: {res.method.value})"
        )
    else:
        lines.append("result: no uncertainty estimate")
    for title, items in (
        ("reasons", res.reasons),
        ("warnings", res.warnings),
        ("notes", res.notes),
    ):
        if items:
            lines.append(f"{title}:")
            lines.extend(f"  - {item}" for item in items)
    return "\n".join(lines)


def _cmd_gci(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.cells is not None and args.dim is None:
        parser.error("--dim is required with --cells")
    try:
        res = grid_convergence(
            args.values,
            cells=args.cells,
            dim=args.dim,
            h=args.h,
            scope=Scope(args.refined.replace("-", "_")),
            grid_sequence=GridSequence(args.grid_sequence),
            layer_cells=args.layer_cells,
            options=Options(formal_order=args.formal_order),
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(res.to_dict(), indent=2) if args.json else format_result(res))
    return 0 if res.clean_pass else 1


def _cmd_report(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        report = verification_report(args.study)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if args.output is None:
        print(render_json(report) if args.json else render_markdown(report), end="")
    else:
        folder = Path(args.output)
        written = (folder / "report.md", folder / "report.json")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            # \n line endings on every platform, so a committed report is the same everywhere.
            written[0].write_text(render_markdown(report), encoding="utf-8", newline="\n")
            written[1].write_text(render_json(report), encoding="utf-8", newline="\n")
        except OSError as exc:
            parser.error(f"cannot write the report: {exc}")
        verdict = "clean pass" if report.clean_pass else "not a clean pass"
        print(f"{report.study}: {verdict}; {report.summary}")
        print(f"wrote {written[0]} and {written[1]}")
    return 0 if report.clean_pass else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "gci":
        return _cmd_gci(args, parser)
    if args.command == "report":
        return _cmd_report(args, parser)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
