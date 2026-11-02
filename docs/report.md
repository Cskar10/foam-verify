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
| Observed order | p is outside [0.5, 2 × the formal order]; above the formal order U uses the formal order, which fails nothing | [gci.md](gci.md), safety factor and the order check; ASME V&V 20, App. C-4 |
| Asymptotic range | GCI_32 / (r21^p GCI_21) is outside [0.9, 1.1], or undefined | standard GCI practice |
| Coarser triplets | with four or more grids, a coarser triplet does not converge monotonically | [gci.md](gci.md), four or more grids |
| Iterative convergence | on grids 1-3 the QoI is drifting, has too few samples, has no scale or is not finite, or its check warns | [iterative.md](iterative.md) |
| Iterative error | u_it on any of grids 1-3 is above U/100 | ASME V&V 20, para. 2-4 (Celik et al. 2008, Appendix A, ask for U/10) |
| Settings consistency | the levels differ in more than the mesh | [consistency.md](consistency.md) |
| Refined directions | the refined directions d disagree with the patches of the mesh (below) | below |
| Refinement scope | `refined = "core"` with total cell counts and no `layer_cells` | [gci.md](gci.md), refinement scope |
| Grid sequence | never: it is stated in `study.toml` and decides the safety factor, Fs = 3 for an unstructured sequence | ASME V&V 20, para. 2-4.1 ([gci.md](gci.md), grid sequence) |

Each check is `pass`, `fail`, `n/a` or `assumed`. `n/a` means the check does not apply, such as
the asymptotic range of a divergent triplet, or the iterative error when there is no U to compare
it with. `assumed` means the method rests on a condition that foam-verify cannot see in the
files: the refinement scope and the grid sequence that `study.toml` states, or the formal order
that a two-grid study takes for p.

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

A comparison with reference data is not a check. When `study.toml` lists reference values, the
report compares each with its QoI in a section of its own, and no comparison changes a verdict
or the exit code ([compare.md](compare.md), In a study).

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
2. **Reference comparison,** when `study.toml` lists references: one row per reference with its
   label (its source when it has none), kind, D (+/- U_D when it states one), E = S - D,
   E / |D|, |E| as a multiple of the uncertainty it is judged against (U_num or U_val, named) and
   the outcome; then each comparison's reasons and source, and the warnings and notes, each once
   after the references and QoIs it applies to.
3. **Levels:** cell counts and the refinement ratio to the next coarser level (with core cells
   or first-layer heights when the scope uses them), and the dimension notes and warnings.
4. **Settings consistency:** the files compared on every level and each difference, level by
   level.
5. **One section per QoI:** where its value is read from, the checks, the value and iterative
   convergence on each level, the Richardson numbers, and with four or more grids each triplet.
6. **Method:** the thresholds behind the checks, and the comparison rules when there are
   references.

Numbers are rounded only in the Markdown: U to three significant digits, and the value to the
decimal place where U ends. Values on each level have seven significant digits.

The JSON (`schema` 1) holds `tool`, `version`, `schema`, `study`, `clean_pass`, `summary`,
`layer_cells`, `criteria` (the GCI thresholds, the formal order among them) and `blocking` (the
study-wide items), then `qois`, one entry per QoI with `value`, `uncertainty`, `band`,
`relative_uncertainty`, `grid_verdict`, `method`, `checks`, `blocking` and its `definition` from
`study.toml`. Then `comparisons`, one entry per reference in the manifest's order (empty when
there are none), each with the `qoi`, the `label` and the `comparison` that `foam_verify.compare`
gives:
`kind`, `outcome`, `simulation`, `reference`, `error`, the uncertainties, `ratio`, `needed`, the
experiment fields, `reasons`, `warnings`, `notes` and `source`. Last comes `result`: everything
`assess_study()` found, every triplet and every level's iterative result, at full precision.

A report holds no absolute path and no time stamp, and its files end lines with `\n` on every
platform, so a study gives the same report on any machine. The reports on the committed studies
are `studies/*/report.md` and `report.json`. `make reports` regenerates them, and
`tests/test_report.py` fails when they no longer match the code.

## Not covered

- Settings that study.toml cannot change yet: the GCI thresholds, the iterative tolerance and the
  contamination margin are foam-verify's defaults, recorded in every report.
