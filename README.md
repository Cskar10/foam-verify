# foam-verify

Read-only verification of OpenFOAM results. It answers "can I trust this number?": grid
convergence index (GCI), iterative convergence of the quantities you report, settings consistency
across grid levels, and comparison with reference data, with the uncertainty stated.

**Status: early development.** The GCI engine, the `study.toml` reader, the iterative
convergence and settings consistency checks, the `report` command, the comparison with
reference data, from numbers (`compare`) or from a study's `study.toml` into its report, and a
read-only MCP server (`mcp`) exist, the server tested tool by tool through an MCP client. The
agent evaluation is ready to run: its labels, its twelve bundles, a sandboxed run harness and
the scorer are committed, and a pilot has tried the harness and the scorer
([eval/](eval/README.md)).

## Results

Three grid studies, run in a pinned OpenFOAM v2512 container and committed with their outputs
under [`studies/`](studies/README.md), each with foam-verify's report beside it:

| Study                                        | Quantities of interest             | Verdict                                            | Report                               |
| -------------------------------------------- | ---------------------------------- | -------------------------------------------------- | ------------------------------------ |
| Square duct, fully developed laminar flow    | f Re, known exactly                | clean pass: f Re = 56.8997 +/- 0.0108              | [report](studies/duct/report.md)      |
| Lid-driven cavity, Re = 100                  | six velocities on the centrelines  | clean pass, all six                                | [report](studies/cavity/report.md)    |
| `pitzDaily`, k-epsilon with wall functions | pressure loss, reattachment length | refused: none of the three converges with the mesh | [report](studies/pitzDaily/report.md) |

**Does the duct's uncertainty band contain the exact answer? Yes.** For fully developed laminar
flow in a square duct, the Darcy friction factor is f Re = 56.9083 (the series solution, Shah and
London 1978). On the three finest of four grids, 160 x 160 to 20 x 20, foam-verify finds
monotonic convergence at an observed order of 1.995 and gives 56.8997 +/- 0.0108, a band from
56.8890 to 56.9105. The actual error, 0.0086, is 80% of the stated uncertainty, and the
Richardson extrapolation, 56.90834, is within 3.3e-5 of the exact value.

**The cavity against two published solutions: within one, outside the other.** Marchi, Suero
and Araki (2009) give four of the cavity's values from a 1024 x 1024 solution with estimated errors
of 1e-8 to 1e-5; all four are within the cavity's uncertainty, with |E| at 0.77 to 0.81 of it.
Ghia, Ghia and Shin (1982) give three, with no stated uncertainty; they differ by 1.3 to 2.1%, 7 to
39 times the uncertainty, and at the one point both papers give, Marchi et al. put Ghia's value
1.6% off. Both comparisons are code-to-code, and the report gives them beside the verdict, not in
it. Details in [the cavity&#39;s README](studies/cavity/README.md#against-two-reference-solutions).

**`pitzDaily` shows the other half of the job: refusing.** Refining the mesh moves the walls
through the switch of the wall function at y+ = 11.53, so the levels do not solve the same
equations. The total-pressure loss converges monotonically on the three finest grids, and on its
own that triplet would pass at +/- 8%; the coarser triplet diverges, and foam-verify refuses the
clean pass. Details in [the study&#39;s README](studies/pitzDaily/README.md).

## Verification report

```console
$ uv run foam-verify report studies/duct                    # Markdown
$ uv run foam-verify report studies/duct --json             # JSON
$ uv run foam-verify report studies/duct --output out/      # out/report.md and out/report.json
```

Each quantity of interest gets a verdict and the checks behind it: grid convergence, refinement
ratio, observed order, asymptotic range, coarser triplets, iterative convergence and error,
settings consistency, refined directions and refinement scope, each `pass`, `fail`, `n/a` or
`assumed`, with the numbers. Every warning that stops a clean pass is quoted. The exit code is 0
only when every QoI is a clean pass. When `study.toml` lists reference values, the report also
compares each with its QoI, in a section of its own; no comparison changes a verdict or the exit
code. The layout and the rules are in [docs/report.md](docs/report.md).

## GCI from numbers

The grid study is given finest grid first, as values with cell counts and the number of refined
directions, or with representative cell sizes:

```console
$ uv run foam-verify gci --values 6.063 5.972 5.863 --cells 18000 8000 4500 --dim 2 \
    --refined mesh --grid-sequence structured
$ uv run foam-verify gci --values 6.063 5.972 5.863 --cells 18000 8000 4500 --dim 2 \
    --refined mesh --grid-sequence structured --json
```

Two inputs are required. `--refined` (`mesh`, `core` or `boundary-layer`) states which part of the
mesh was refined, and so what the uncertainty covers. `--grid-sequence` (`structured` or
`unstructured`) states whether the levels refine one base grid systematically: an unstructured
sequence gets the safety factor 3 instead of 1.25, as ASME V&V 20 recommends.

The verdict is one of `monotonic_convergence`, `oscillatory_convergence`, `divergence`,
`degenerate`, `two_grid` or `order_unresolved`. Only a monotonic triplet with no warnings is a
clean pass, and the exit code is 0 only then. The maths, its sources and the conventions that are
this tool's own are in [docs/gci.md](docs/gci.md).

## Comparison with reference data

```console
$ uv run foam-verify compare --simulation 56.8997 --uncertainty 0.0108 --reference 56.9083 --kind exact
```

The comparison error E = S - D is judged against the uncertainty that applies, and the kind of
reference, which `--kind` states, decides what E can show. Against an `exact` solution of the
same equations, E is the numerical error itself, so the comparison checks whether the numerical
uncertainty bounds it: on the duct, |E| is 80% of U_num. Against another numerical solution
(`code`), E is the difference of two numerical errors. Only an `experiment` validates the model,
following ASME V&V 20 and the algorithm of Eça, Dowding and Roache (2020). Every uncertainty is
a 95% expanded uncertainty; with experimental data, the standard uncertainty is given too, with
its divisor. The rules and their sources are in [docs/compare.md](docs/compare.md).

A study can list its reference values in `study.toml`, as `[[reference]]` tables with the QoI,
the kind, the value and its source, and `foam-verify report` then makes each comparison: the
duct against its exact f Re, and the cavity against Ghia et al.'s Table I and Marchi et al.'s
1024 x 1024 solution.

## MCP server

```console
$ uv run --extra mcp foam-verify mcp --root studies
```

`foam-verify mcp` serves these checks to an MCP client, such as Claude Code or Claude Desktop,
over stdio, as seven read-only tools: `list_studies`, `study_summary`, `grid_convergence`,
`iterative_convergence`, `settings_consistency`, `compare_reference` and
`verification_report`. Each returns JSON with the verdict, the numbers behind it and the
reasons. The tools read only under the `--root` folders: every path is resolved, symlinks
followed, and must lie under a root, and no file above the size cap (64 MiB by default) is read.
They write nothing, start no process and use no network. Setup for clients, the tools and the
sandbox are in [docs/mcp.md](docs/mcp.md).

## Iterative convergence

Residuals are not the quantity you report. For a study, foam-verify also reads the history of
each QoI on every level and asks whether the value itself has stopped moving: `converged`,
`oscillating` or `drifting`, with the iterative uncertainty u_it, half the range over the last
window of samples. On the levels behind the headline result, u_it must be at most a hundredth of
the GCI uncertainty (two orders of magnitude, as ASME V&V 20 asks), or iterative error
contaminates the grid study. The method, its sources and this
tool's own conventions are in [docs/iterative.md](docs/iterative.md).

## Settings consistency

The levels of a grid study should differ only in the mesh. foam-verify compares their schemes,
solver settings, physical properties, boundary conditions and near-wall layer settings entry by
entry, and names any difference by file and key:

```text
system/fvSchemes: divSchemes/div(phi,U): 'Gauss linear' on 160x160, 80x80, 40x40; 'Gauss upwind' on 20x20
```

Any difference blocks a clean verdict, except run controls in `controlDict` such as a time step
that shrinks with the mesh, which are listed as notes. What is compared, and why, is in
[docs/consistency.md](docs/consistency.md).

## Development

```console
$ make setup     # uv sync
$ make ci        # ruff + pytest
$ make reports   # regenerate the reports under studies/
```

## Author

[Chris Skarakis](https://www.linkedin.com/in/chris-skarakis-511276217/)
