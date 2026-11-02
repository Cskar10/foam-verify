"""MCP server: foam-verify's checks as read-only tools, over stdio.

Each tool reads a grid study, a folder holding study.toml, and returns JSON: the verdict, the
numbers behind it and the reasons, as the library gives them. The server only reads. No tool
writes a file, starts a process or uses the network, and every read happens inside a sandbox
(foam_verify.access): a path is resolved, with its symlinks followed, and must lie under one of
the roots the server was started with, and no file may be larger than the cap.

A tool's study argument is the study's folder or its study.toml, absolute or relative to a
root; a relative path goes to the first root that has it. Results give each study's absolute
path. foam-verify mcp --root DIR runs the server (foam_verify.cli); docs/mcp.md lists the tools
and how to connect a client.

Needs the mcp package (pip install "foam-verify[mcp]"); nothing else in foam-verify does.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import access
from .report import build_report, render_markdown
from .study import (
    MANIFEST,
    QoIResult,
    Study,
    StudyError,
    StudyResult,
    assess_study,
    cell_count,
    compare_references,
    load_study,
)

DEFAULT_MAX_BYTES = 64 * 2**20
# list_studies looks at most this many folders below each root, and lists at most this many.
MAX_DEPTH = 4
MAX_STUDIES = 200

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)

INSTRUCTIONS = """\
foam-verify checks whether a number from an OpenFOAM grid study can be trusted: grid \
convergence (GCI, observed order, Richardson extrapolation), the iterative convergence of each \
quantity of interest (QoI), and whether the grid levels differ only in the mesh. A study is a \
folder holding study.toml and one case per grid level. Start with list_studies, then \
verification_report for the verdict on each QoI with the checks behind it; the other tools \
give the parts. Every tool is read-only and confined to the folders the server was started \
with. A QoI is a clean pass only when no check fails; the report says what stops one."""


def _manifests(root: Path) -> Iterator[Path]:
    """study.toml files below root, at most MAX_DEPTH folders down, hidden folders skipped.

    Symlinked folders are not followed; a symlinked study.toml is listed and refused on loading.
    """
    for folder, subfolders, files in os.walk(root):
        here = Path(folder)
        depth = len(here.relative_to(root).parts)
        subfolders[:] = sorted(s for s in subfolders if not s.startswith(".") and depth < MAX_DEPTH)
        if MANIFEST in files:
            yield here / MANIFEST


def _qois(result: StudyResult, qoi: str | None) -> list[QoIResult]:
    if qoi is None:
        return list(result.qois)
    chosen = [q for q in result.qois if q.name == qoi]
    if not chosen:
        names = ", ".join(q.name for q in result.qois)
        raise StudyError(f"no qoi {qoi!r} in study {result.name}; its qois: {names}")
    return chosen


def create_server(roots: Sequence[str | Path], *, max_bytes: int = DEFAULT_MAX_BYTES) -> FastMCP:
    """A server whose tools read only under roots, and no file above max_bytes."""
    box = access.make_sandbox(roots, max_bytes)
    server = FastMCP("foam-verify", instructions=INSTRUCTIONS)

    def locate(study: str) -> Path:
        """The study's folder as a real path under a root; outside paths are not looked at."""
        given = Path(study).expanduser()
        candidates = [given] if given.is_absolute() else [root / given for root in box.roots]
        allowed = [real for real in (c.resolve() for c in candidates) if box.allows(real)]
        if not allowed:
            raise access.AccessError(f"study {study!r} is outside the allowed roots")
        for real in allowed:
            folder = real.parent if real.name == MANIFEST else real
            if (folder / MANIFEST).is_file():
                return folder
        raise StudyError(f"no study at {study!r}: no {MANIFEST} there under the allowed roots")

    def load(study: str) -> Study:
        return load_study(locate(study))

    @server.tool(annotations=READ_ONLY)
    def list_studies() -> dict[str, Any]:
        """The grid studies under the server's roots: every folder holding a study.toml, up to
        four folders down, with its name, levels (finest first), quantities of interest (QoIs)
        and number of reference values. Pass a study's path to the other tools. A study that
        cannot be read is listed with the error instead."""
        studies: list[dict[str, Any]] = []
        truncated = False
        with access.sandbox(box):
            for root in box.roots:
                for manifest in _manifests(root):
                    if len(studies) == MAX_STUDIES:
                        truncated = True
                        break
                    entry: dict[str, Any] = {"path": str(manifest.parent)}
                    try:
                        s = load_study(manifest)
                    except (StudyError, OSError) as exc:
                        entry["error"] = str(exc)
                    else:
                        entry |= {
                            "name": s.name,
                            "levels": [lv.name for lv in s.levels],
                            "qois": [q.name for q in s.qois],
                            "references": len(s.references),
                        }
                    studies.append(entry)
        return {
            "roots": [str(r) for r in box.roots],
            "studies": studies,
            "truncated": truncated,
        }

    @server.tool(annotations=READ_ONLY)
    def study_summary(study: str) -> dict[str, Any]:
        """A study as its study.toml defines it: refined directions d, what was refined, the
        grid sequence, the formal order, the levels finest first with their cell counts (from
        the mesh), each QoI's definition (file, column, reduction, window) and each reference
        value. Judges nothing: verification_report gives the verdict."""
        with access.sandbox(box):
            s = load(study)
            levels = [
                {
                    "name": lv.name,
                    "path": str(lv.path.relative_to(s.root)),
                    "cells": cell_count(lv.path),
                    "first_layer_height": lv.first_layer_height,
                }
                for lv in s.levels
            ]
        return {
            "path": str(s.root),
            "name": s.name,
            "dim": s.dim,
            "formal_order": s.formal_order,
            "refined": s.scope.value.replace("_", "-"),
            "grid_sequence": s.grid_sequence.value,
            "layer_cells": s.layer_cells,
            "levels": levels,
            "qois": [asdict(q) for q in s.qois],
            "references": [asdict(r) for r in s.references],
        }

    @server.tool(annotations=READ_ONLY)
    def grid_convergence(study: str, qoi: str | None = None) -> dict[str, Any]:
        """Grid convergence of every QoI, or of one: its value on each level, finest first;
        the convergence type (monotonic, oscillatory, divergent, degenerate, two grids, order
        unresolved); the observed order p; Richardson extrapolation; the uncertainty U of the
        finest-grid value and its band (GCI, Celik et al. 2008, ASME V&V 20); every triplet
        when there are four or more grids; and the reasons and warnings. The grid study alone:
        verification_report adds the iterative and settings checks to a verdict."""
        with access.sandbox(box):
            s = load(study)
            result = assess_study(s)
        return {
            "path": str(s.root),
            "name": result.name,
            "levels": [{"name": lv.name, "cells": lv.cells} for lv in result.levels],
            "qois": [
                {
                    "name": q.name,
                    "values": list(q.values),
                    "notes": list(q.notes),
                    "gci": q.gci.to_dict(),
                }
                for q in _qois(result, qoi)
            ],
        }

    @server.tool(annotations=READ_ONLY)
    def iterative_convergence(study: str, qoi: str | None = None) -> dict[str, Any]:
        """Iterative convergence of every QoI, or of one, from its own history on each level
        (not from residuals): converged, oscillating or drifting over its window, with the
        relative range and drift and the iterative uncertainty u_it; then whether u_it on the
        grids behind the result is small against the grid study's U (at most U/100, ASME V&V
        20), so that iterative error does not contaminate the grid study."""
        with access.sandbox(box):
            s = load(study)
            result = assess_study(s)
        names = [lv.name for lv in result.levels]
        return {
            "path": str(s.root),
            "name": result.name,
            "qois": [
                {
                    "name": q.name,
                    "levels": [
                        {"level": name, **it.to_dict()}
                        for name, it in zip(names, q.iterative, strict=True)
                    ],
                    "contamination": None if q.contamination is None else q.contamination.to_dict(),
                }
                for q in _qois(result, qoi)
            ],
        }

    @server.tool(annotations=READ_ONLY)
    def settings_consistency(study: str) -> dict[str, Any]:
        """Whether the levels differ only in the mesh: schemes, solver settings, physical
        properties, boundary conditions and near-wall layer settings, compared entry by entry,
        with every difference level by level and whether it blocks a clean pass."""
        with access.sandbox(box):
            s = load(study)
            result = assess_study(s)
        consistency = result.consistency
        return {
            "path": str(s.root),
            "name": result.name,
            "consistency": None if consistency is None else consistency.to_dict(),
        }

    @server.tool(annotations=READ_ONLY)
    def compare_reference(study: str, qoi: str | None = None) -> dict[str, Any]:
        """Each reference value in study.toml, for every QoI or one, set against the QoI's
        finest-grid value S and its 95% uncertainty: the comparison error E = S - D, judged
        against U_num for an exact reference and U_val for a code or experimental one, with
        the outcome and the reasons (ASME V&V 20; Eça, Dowding and Roache 2020). No part of
        the verification verdict: it says how far a value is from a reference, not whether
        the value is converged."""
        with access.sandbox(box):
            s = load(study)
            result = assess_study(s)
        names = {q.name for q in _qois(result, qoi)}
        return {
            "path": str(s.root),
            "name": result.name,
            "comparisons": [
                {"qoi": c.qoi, "label": c.label, "comparison": c.comparison.to_dict()}
                for c in compare_references(s, result)
                if c.qoi in names
            ],
        }

    @server.tool(annotations=READ_ONLY)
    def verification_report(
        study: str, format: Literal["json", "markdown"] = "json"
    ) -> dict[str, Any]:
        """The verdict on every QoI of a study: whether it is a clean pass, its finest-grid
        value with its uncertainty, and every check behind the verdict (grid convergence,
        refinement ratio, observed order, asymptotic range, coarser triplets, iterative
        convergence and error, settings consistency, refined directions, refinement scope,
        grid sequence), what stops a clean pass, word for word, and the reference comparisons.
        Start here to judge whether a value is converged and mesh-independent. format
        "markdown" gives the same report as text."""
        with access.sandbox(box):
            s = load(study)
            report = build_report(s)
        if format == "markdown":
            return {"path": str(s.root), "markdown": render_markdown(report)}
        return {"path": str(s.root), **report.to_dict()}

    return server
