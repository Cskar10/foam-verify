# foam-verify

Read-only verification of OpenFOAM results. It answers "can I trust this number?": grid
convergence index (GCI), iterative convergence of the quantities you report, settings consistency
across grid levels, and comparison with reference data, with the uncertainty stated. A CLI and a
Python library, with a read-only MCP server that gives the same checks to AI agents.

**Status: v0.1.0.** The GCI engine, the `study.toml` reader, the iterative convergence and
settings consistency checks, the comparison with reference data, the `report` command and the MCP
server, with 608 tests; three grid studies, and an agent evaluation of 144 scored runs on two
models, committed with their outputs.

## Does it help an AI agent judge a grid study?

Yes, on the evaluation committed here. Each agent gets one bundle, a grid study as foam-verify
reads it (`study.toml` and one OpenFOAM case per grid level, with its logs and function-object
output), and one question:

> Is the reported value of `<qoi>` converged and mesh-independent? Give the value with its
> uncertainty, or say why you can't.

In condition A the agent may read every file in the bundle and nothing else; in condition B it
also has foam-verify's MCP server. Of the twelve bundles, four are sound and eight are not, and
the labels were committed before any bundle was built or any agent saw one. Each bundle ran three
times in each condition, on two models:

| Model | Condition | Verdict right | False trust | Sound bundles rejected | No verdict | Median time |
|---|---|---|---|---|---|---|
| Claude Opus 5.5 | A, the files only | 29 of 36 | 7 of 24 | 0 of 12 | 0 | 46 s |
| Claude Opus 5.5 | B, with foam-verify | 36 of 36 | 0 of 24 | 0 of 12 | 0 | 17 s |
| Qwen3.8 27B, local | A, the files only | 4 of 36 | 0 of 24 | 0 of 12 | 32 | 30 min, the limit |
| Qwen3.8 27B, local | B, with foam-verify | 35 of 36 | 0 of 24 | 0 of 12 | 1 | 72 s |

False trust is the verdict trustworthy on a bundle labelled not trustworthy. A run that reaches
the 30-minute limit has no verdict, which is never right.

With foam-verify, the agents gave the right verdict in 71 of 72 runs and no wrong verdict; the
other run ran out of time. Without it, Claude Opus 5.5 called a broken study converged in 7 of 24
runs, and the local model rarely finished within 30 minutes.

- **Opus's misses repeat.** Without the tool it trusted b02, a study on two grids, and b03, with
  refinement ratios of about 1.10, in all three runs, and b05, whose 80 x 80 grid uses another
  convection scheme, in one. With the tool it trusted none. Its numbers were not the problem: on
  b02 and b03 its value and band held the exact f Re. Its verdict was: it called the value
  mesh-independent when the study cannot show that, and that is the error that matters when
  there is no exact answer to check against.
- **The local model is slow without the tool, not wrong.** It ran out of time in 32 of 36 runs.
  The four verdicts it gave were all right, too few to give an error rate.
- **The local model with foam-verify did better than Opus 5.5 without it:** 35 of 36 right and no
  false trust, against 29 of 36 and 7.
- **Nothing went the other way.** For neither model did any bundle score worse with the tool, and
  no sound bundle was rejected in any of the 144 runs: the zero false trust was not bought by
  rejecting everything.
- **The tool is also cheaper.** Opus's 36 runs with it cost $2.24 at API prices, against $12.65
  without.

Claude Opus 5.5 (`claude-opus-5-5`) ran through Claude Code 2.1.312 on 2 Nov 2026. Qwen3.8 27B
(Unsloth's UD-Q6_K GGUF) ran on 3 and 4 Nov through the same harness and sandbox, served by
llama.cpp b11678 on an RTX 5090 Laptop GPU (24 GB) at about 23 tokens a second. The labels, the
harness, the scorer's rules, every transcript and the scores are in [eval/](eval/README.md); what
this evaluation cannot show is under [Limits](#limits).

## Does the uncertainty band hold the exact answer?

Three grid studies, run in a pinned OpenFOAM v2512 container and committed with their outputs
under [`studies/`](studies/README.md), each with foam-verify's report beside it. Each was chosen to
show one thing:

| Study | Quantities of interest | Expected | foam-verify's verdict | Report |
|---|---|---|---|---|
| Square duct, fully developed laminar flow | f Re, known exactly | a clean pass whose band holds the exact value | clean pass: f Re = 56.8997 +/- 0.0108, band holds 56.9083 | [report](studies/duct/report.md) |
| Lid-driven cavity, Re = 100 | six velocities on the centrelines | a clean pass; published values within the uncertainty, or the difference explained | clean pass, all six | [report](studies/cavity/report.md) |
| `pitzDaily`, k-epsilon with wall functions | two pressure differences, reattachment length | a refusal if refinement moves y+ through the wall-function range | refused: none of the three converges with the mesh | [report](studies/pitzDaily/report.md) |

**Rerun from scratch.** On 4 Nov 2026 all twelve cases ran again from a fresh clone, in the same
pinned image, following each study's README. Apart from the dates, host names, process IDs and
run times in the solver logs, every committed output came back byte-identical, and the three
reports regenerated unchanged.

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
it. Details in [the cavity's README](studies/cavity/README.md#against-two-reference-solutions).

**`pitzDaily` shows the other half of the job: refusing.** Refining the mesh moves the walls
through the switch of the wall function at y+ = 11.53, so the levels do not solve the same
equations. The total-pressure loss converges monotonically on the three finest grids, and on its
own that triplet would pass at +/- 8%; the coarser triplet diverges, and foam-verify refuses the
clean pass. Details in [the study's README](studies/pitzDaily/README.md). foam-verify passed the
loss at first: see [What broke](#what-broke).

## Reproduce

Three commands give the headline numbers from the committed outputs and transcripts, with git,
[uv](https://docs.astral.sh/uv/) and Python 3.11 or later:

```console
$ git clone https://github.com/Cskar10/foam-verify && cd foam-verify
$ uv run foam-verify report studies/duct      # the duct's verdict and band
$ python3 eval/score.py                       # the evaluation's scores, from the transcripts
```

`eval/score.py` writes `eval/runs/scores.md` and `scores.jsonl` again, and `git status` then shows
no change. To rerun the duct's OpenFOAM cases with the pinned image, three more commands and
about 7 minutes: [studies/duct/README.md](studies/duct/README.md#reproduce). To run the agents
again, with Claude Code and a Claude login, or llama-server for a local model:
[eval/README.md](eval/README.md#running-the-agents).

## What broke

- **foam-verify passed `pitzDaily`'s pressure loss at first.** The three finest grids converge
  monotonically and gave 16.48 +/- 1.31 (8%), a clean pass under the rule foam-verify had then,
  while the coarser triplet diverges. With four or more grids, a coarser triplet that does not
  converge monotonically now blocks the clean pass ([docs/gci.md](docs/gci.md)).
- **The iterative check called converged noise drifting** in 5 of 800 synthetic histories: a few
  short noise cycles late in the window moved the cycle mean further than the samples range. In
  that case the check now falls back to least squares; over 3,456 test series this changed no
  correct verdict ([docs/iterative.md](docs/iterative.md)).
- **OpenFOAM's `icoFoam` cavity tutorial runs at Re = 10, not 100** (nu = 0.01, L = 0.1, U = 1).
  The study sets nu = 0.001 to match Ghia et al.'s Re = 100.
- **The duct's residuals never converged.** Uy, Uz and p are zero up to round-off, so their
  normalised residuals divide noise by noise and stay between 0.016 and 0.55, while f Re had
  settled thousands of iterations before the end. foam-verify judges the quantity reported, not
  the residuals.
- **An absolute `file` pattern for a QoI in `study.toml` crashed the CLI** with a traceback. The
  manifest now refuses it when it loads.
- **A test passed locally and failed in CI.** The test that checks the labels against the commit
  that froze them found no such commit in GitHub's shallow checkout, so CI failed on two pushes;
  the workflow now fetches the full history.
- **The local model needed two workarounds.** Qwen's chat template refused the system message
  that Claude Code sends after the question, so for local models the harness has Claude Code put
  those notes into the question. In one run Claude Code's compaction of the session came back
  empty; that run was set aside and the slot run again, as the scorer's rules allow.

## Limits

- **The GCI is an estimate under assumptions:** a smooth solution, and grids in the asymptotic
  range. Each report says which checks held; `pitzDaily` shows what happens when they don't.
- **One OpenFOAM build.** Every study and bundle ran on OpenFOAM v2512 (openfoam.com) from one
  pinned image. Function-object output differs between versions, and between openfoam.com and
  openfoam.org; only this build's is tested.
- **A small evaluation.** Twelve bundles, one question, and labels written by the author. Three
  runs of one bundle are not independent, so Opus's gain rests on three bundles, b02, b03 and
  b05: three better and none worse, which chance alone gives one time in eight. The local
  model's gain covers all twelve bundles, but it mostly measures that the model cannot finish
  alone within 30 minutes on this hardware.
- **Only faults foam-verify checks for.** The broken bundles fail on iterative convergence, two
  grids, the refinement ratio, grid convergence or settings. The evaluation shows that agents use
  the tool and report what it finds; it does not show that the tool catches faults outside that
  list, or how it does on studies built by others.
- **foam-verify was never wrong here.** With the tool, both models mostly reported its result, in
  a median of 3 or 4 turns, so a bug in it would likely pass straight through. Its correctness
  rests on the tests and the published reference values, not on the evaluation.
- **Models change.** Another model, or another version of these two, may answer differently.
  Every transcript is committed, so the answers can be read, not just counted.

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

## Licence

MIT ([LICENSE](LICENSE)). The `cavity` and `pitzDaily` studies are built from OpenFOAM v2512's
tutorials by the generator scripts under `studies/`; OpenFOAM itself (GPL-3.0) is not distributed
here, only run from its public image. The reference values are quoted, with page numbers, from the
papers named in [studies/README.md](studies/README.md#reference-values). Qwen3.8 27B is
Apache-2.0; only its answers are committed.

## Author

[Chris Skarakis](https://www.linkedin.com/in/chris-skarakis-511276217/)

Built with AI assistance; the tests and the published reference values carry the claims.
