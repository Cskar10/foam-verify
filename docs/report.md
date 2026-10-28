# Verification report: the verdict and the layout

`foam-verify report STUDY` reads a grid study (a folder holding `study.toml`) and prints what
foam-verify found as Markdown, or as JSON with `--json`. `--output DIR` writes both instead, as
`DIR/report.md` and `DIR/report.json`. The exit code is 0 when every quantity of interest is a
clean pass, 1 when any is not, and 2 for bad input.

```console
$ uv run foam-verify report studies/duct
$ uv run foam-verify report studies/duct --json
$ uv run foam-verify report studies/duct --output studies/duct
```

In Python, `foam_verify.report.verification_report(path)` returns the report, and
`render_markdown()` and `render_json()` give its two forms.

## The verdict

A QoI is a clean pass only when no check fails. The checks, in the order the report lists them:

| Check | Fails when | Source |
|---|---|---|
| Grid convergence | grids 1-3 do not converge monotonically: oscillatory, divergent, degenerate, two grids only, or no observed order | Celik et al. 2008; Eça and Hoekstra 2014 ([gci.md](gci.md)) |
| Refinement ratio | r21 or r32 is below 1.3 | Celik et al. 2008, step 2 |
| Observed order | p is outside [0.5, 2 × the formal order] | [gci.md](gci.md), safety factor and the order check |
| Asymptotic range | GCI_32 / (r21^p GCI_21) is outside [0.9, 1.1], or undefined | standard GCI practice |
| Coarser triplets | with four or more grids, a coarser triplet does not converge monotonically | [gci.md](gci.md), four or more grids |
| Iterative convergence | on grids 1-3 the QoI is drifting, has too few samples, has no scale or is not finite, or its check warns | [iterative.md](iterative.md) |
| Iterative error | u_it on any of grids 1-3 is above U/10 | Celik et al. 2008, Appendix A |
| Settings consistency | the levels differ in more than the mesh | [consistency.md](consistency.md) |
| Refined directions | the refined directions d disagree with the patches of the mesh (below) | below |
| Refinement scope | `refined = "core"` with total cell counts and no `layer_cells` | [gci.md](gci.md), refinement scope |

Each check is `pass`, `fail`, `n/a` or `assumed`. `n/a` means the check does not apply, such as
the asymptotic range of a divergent triplet, or the iterative error when there is no U to compare
it with. `assumed` means the method rests on a condition that foam-verify cannot see in the
files: the refinement scope that `study.toml` states, or the formal order that a two-grid study
takes for p.

The checks add no rule of their own. Each restates a condition that `foam_verify.gci`,
`foam_verify.iterative`, `foam_verify.consistency` or the study reader already applies, so the
table explains the verdict; it does not make it. If a warning ever comes up that no row covers,
an `Other` row fails with its text, so the table cannot show a clean slate for a QoI that is not
a clean pass. `tests/test_report.py` checks that a QoI is a clean pass exactly when no row fails
and nothing is listed against it.

The study is a clean pass when every QoI is. Under the verdict, the report quotes every reason
and warning that stops a clean pass, word for word: those of each QoI's grid study and iterative
check, and the study-wide ones (settings differences and dimension warnings), which stop every
QoI.

## Refined directions

The refinement ratio comes from the cell counts, $r = (N_1/N_2)^{1/d}$, so a wrong $d$ gives a
wrong $r$ and a wrong observed order. The study reader checks $d$ against the patches in
`constant/polyMesh/boundary` on every level:

- `empty` or `wedge` patches make a case 2-D. With `dim = 3` they are a warning.
- Two patches with one face per cell on every level, such as the two halves of a cyclic, mean
  the mesh is one cell across them, so that direction was never refined. With `dim = 2` and no
  `empty` or `wedge` patches, this confirms $d$ and is reported as a note; the square duct is
  such a case. With `dim = 3` it is a warning.
- `dim = 2` with neither is a warning: the reader cannot see which direction was left alone.
- Levels with different `empty` or `wedge` patches are a warning.

One face per cell on each of two patches is what a mesh one cell thick between them has; this
is foam-verify's test, not one from the papers. A warning blocks the clean pass of every QoI.

## What a report holds

The Markdown, top to bottom:

1. **Verdict:** the summary, one row per QoI (the finest-grid value +/- U, U relative to the
   value, the convergence of grids 1-3, clean pass or not) and what stops a clean pass.
2. **Levels:** cell counts and the refinement ratio to the next coarser level (with core cells
   or first-layer heights when the scope uses them), and the dimension notes and warnings.
3. **Settings consistency:** the files compared on every level and each difference, level by
   level.
4. **One section per QoI:** where its value is read from, the checks, the value and iterative
   convergence on each level, the Richardson numbers, and with four or more grids each triplet.
5. **Method:** the thresholds behind the checks.

Numbers are rounded only in the Markdown: U to three significant digits, and the value to the
decimal place where U ends. Values on each level have seven significant digits.

The JSON (`schema` 1) holds `tool`, `version`, `schema`, `study`, `clean_pass`, `summary`,
`layer_cells`, `criteria` (the GCI thresholds, the formal order among them) and `blocking` (the
study-wide items), then `qois`, one entry per QoI with `value`, `uncertainty`, `band`,
`relative_uncertainty`, `grid_verdict`, `method`, `checks`, `blocking` and its `definition` from
`study.toml`. Last comes `result`: everything `assess_study()` found, every triplet and every
level's iterative result, at full precision.

A report holds no absolute path and no time stamp, and its files end lines with `\n` on every
platform, so a study gives the same report on any machine. The reports on the committed studies
are `studies/*/report.md` and `report.json`. `make reports` regenerates them, and
`tests/test_report.py` fails when they no longer match the code.

## Not covered

- Comparison with reference data. The square duct's exact f Re and the cavity's Ghia et al.
  values are not in the reports yet; reference comparison (ASME V&V 20) is planned as its own
  check. The duct's comparison with the exact value is in [its README](../studies/duct/README.md).
- Settings that study.toml cannot change yet: the GCI thresholds, the iterative tolerance and the
  contamination margin are foam-verify's defaults, recorded in every report.
