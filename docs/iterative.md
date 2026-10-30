# Iterative convergence: method and conventions

`foam_verify.iterative` asks whether a reported quantity has stopped moving. Residuals are not
the quantity reported, so it reads the history of the QoI itself: iterations for a steady run,
time for a transient one. This page records the measures as implemented, where each comes from,
and the places where foam-verify makes its own choice.

## Sources

- ITTC (2008). Recommended Procedure 7.5-03-01-01, *Uncertainty Analysis in CFD: Verification
  and Validation Methodology and Procedures*, Revision 02. Section 4.1, page 5 of 12: iterative
  and parameter convergence studies, and the half-range bound for oscillatory convergence. Copy
  used: <https://www.ittc.info/media/4184/75-03-01-01.pdf> (sha256 `5d0576e3…007f`).
- ITTC (2024). The same procedure, Revision 05. Section 3.3, pages 7-8: iterative errors "must be
  accurately estimated or negligible" before a convergence study. The half-range formula is no
  longer stated, which is why Revision 02 is cited for it. Copy used:
  <https://www.ittc.info/media/11950/75-03-01-01.pdf> (sha256 `b8b2c8aa…e7a0`).
- ITTC (2024). Recommended Procedure 7.5-03-02-01, *Uncertainty Analysis in CFD, Examples for
  Resistance and Flow*, Revision 02. Section 2.3.1, pages 4-5: the Series 60 resistance example.
  Revision 00 (1999) has the same text. Copy used:
  <https://www.ittc.info/media/11954/75-03-02-01.pdf> (sha256 `dbfa1308…dd60`).
- Celik et al. (2008), the copy listed in [gci.md](gci.md): page 4 (the residual criterion) and
  Appendix A, page 14 (the margin over the discretisation error).
- Eça and Hoekstra (2014), the copy listed in [gci.md](gci.md): section 2.1, page 105.

## Why not residuals

Celik et al. (page 4) ask for "at least three (preferably four) orders of magnitude decrease in
the normalized residuals for each equation solved", and add: "This commonly-used criterion does
not always ensure adequate convergence; see Appendix A." For time-dependent problems they ask
for "sample convergence trends" of "selected, critically important, variables". foam-verify
checks those trends.

The square duct shows the gap ([studies/duct](../studies/duct/README.md)). `residualControl`
(1e-10) never stops the runs: Uy, Uz and p are zero to round-off, so their normalised residuals
divide noise by noise and stay between 0.016 and 0.55. By residuals the case never converges. By
the quantity reported it converged thousands of iterations before the end.

## The window

The last `window` fraction of the samples (default 0.1), but at least `min_samples` of them
(default 50), or all of them when there are fewer. This is the same window as a study QoI's
`window_mean` reduction, and `study.toml` sets both with the same keys.

- Fewer than `min_samples` samples: the window is the whole history, start-up included, and the
  result carries a warning.
- Fewer than `min_window` (3): `insufficient_data`. A QoI written only at the end of a run has
  one sample and cannot be judged.

The fraction and the minimum are foam-verify's choices. ITTC 7.5-03-02-01 takes the last two
periods of the oscillation; see below for how the window is checked against that.

## Measures

Over the window, with mean $\bar\phi$ and scale $s = \lvert\bar\phi\rvert$:

- relative range $(\phi_\max - \phi_\min)/s$;
- drift: the change of the trend across the window, slope times $(x_\text{last} - x_\text{first})$,
  signed and in the QoI's units, and the relative drift, drift$/s$. It is measured in $x$
  (iteration or time), so uneven sampling is handled;
- iterative uncertainty $u_\text{it} = \tfrac12(\phi_\max - \phi_\min)$, half the range.

Half the range is ITTC's bound for oscillatory convergence, $U_i = \tfrac12(S_U - S_L)$ from the
oscillation maxima $S_U$ and minima $S_L$ (7.5-03-01-01, 2008, section 4.1, which covers
iterative and parameter convergence studies alike). In 7.5-03-02-01 (section 2.3.1) the
iterative uncertainty "is estimated as half the range of the maximum and minimum values over the
last two periods of oscillation". That is a worked example, not a general rule.

A window mean that is zero to round-off ($\lvert\bar\phi\rvert \le 10^{-10}\max\lvert\phi\rvert$),
with samples that still vary, leaves the relative values undefined: the verdict is `no_scale`. The library takes a `reference`
magnitude to divide by instead. `study.toml` does not expose it yet, so a study QoI whose mean is
zero is reported as `no_scale`.

## The drift: least squares or cycle means

The plain estimate is the least-squares line through the window. A steady oscillation tilts that
line, by roughly its range divided by the number of periods, depending on where the window cuts
the phase: four periods of a 1% sine tilt it by about half the amplitude, five times the default
tolerance (`tests/test_iterative.py`). So once the window holds full cycles, the drift is the
trend of the cycle means instead:

- A cycle runs from one upward crossing of $+h$ to the next, where $h$ is half the amplitude of
  the residual about the trend. A crossing counts only after the residual has been below $-h$,
  so noise near the line does not split cycles. Crossing times are interpolated between samples.
- Each cycle's mean integrates $\phi$ piecewise-linearly between its crossings, so every cycle of
  a steady oscillation covers the same phase and has the same mean.
- The trend is a least-squares line through the cycle means, weighted by cycle length (a cycle
  mean's noise falls with its length). Cycles are found about the least-squares line, then again
  about the cycle-mean trend, so the crossing level does not creep along a tilted line.
- The cycle means are used with at least `min_periods` full cycles (default 2, ITTC's "last two
  periods"), and always at least two.

Two guards:

- **Noise.** With three or more cycle means, the scatter of the means about their trend gives
  the trend a standard error. A drift within twice that error (`drift_noise`) is not resolved: the
  QoI is not called drifting, and a warning blocks the clean pass instead ("the window cannot tell
  drift at tol from noise; widen it").
- **Consistency.** A trend cannot carry the QoI further across the window than its samples range.
  When the cycle-mean drift exceeds $\phi_\max - \phi_\min$, the cycles are noise and the trend
  through their means is an extrapolation. The least-squares line is kept. Converged noise
  written to a few digits shows it: a few short cycles late in the window give a cycle-mean drift
  3.3 times the range, which is 2.6 times the tolerance. The tests pin that case. They also check
  800 converged noisy histories, five of which were called drifting before this guard.

Both guards and the two-pass cycle search are foam-verify's own construction. The papers state
the half-range bound but not how to separate drift from oscillation.

## Verdicts

Default tolerance `tol` $= 10^{-3}$ on both relative measures; foam-verify's choice.

| Verdict | When | $u_\text{it}$ |
|---|---|---|
| `converged` | relative range at or below `tol`, drift at or below it (or not resolved) | half the range |
| `oscillating` | range above `tol`, drift at or below it (or not resolved) | half the range |
| `drifting` | drift above `tol` and resolved | none |
| `insufficient_data` | fewer than `min_window` samples in the window | none |
| `non_finite` | a NaN or infinite sample anywhere in the history | none |
| `no_scale` | window mean zero to round-off, no reference given | none |

- Only `converged` with no warnings is a clean pass. A drift that is not resolved carries a
  warning, so it is never one.
- A drifting QoI has no $u_\text{it}$: half the range would understate the error of a value that
  is still moving. Without resolved cycles, the result adds a note that a slow oscillation, with a
  period longer than half the window, also looks like drift.
- An oscillating QoI with fewer than `min_periods` full cycles in the window is warned about:
  $u_\text{it}$ may understate the amplitude. Widen the window.
- An oscillation can be physical rather than iterative. foam-verify cannot tell the two apart and
  says so in a note.

## Grid studies: is the GCI contaminated?

`check_contamination` compares $u_\text{it}$ on each level with the grid study's discretisation
uncertainty $U$, the fine-grid GCI result. Celik et al. (Appendix A): the iteration convergence
error "should be at least one order of magnitude smaller than the discretization error estimates
for each calculation". So the default `ratio` is 10, and a headline level fails when
$u_\text{it} > U/10$.

- Every headline level is compared with the fine-grid $U$, the smallest discretisation
  uncertainty. An iterative error on any level enters the differences the GCI is built from, so
  comparing each level with its own, larger, error would be weaker. This is foam-verify's choice,
  the conservative reading of "each calculation".
- The headline levels are the finest triplet, or both grids of a two-grid study. A failed verdict
  or a warning there blocks the clean pass. Coarser levels are reported in notes, as coarser
  triplets are in the GCI.
- Without a discretisation uncertainty (a divergent or degenerate study) there is nothing to
  compare with, and the check is not a clean pass.
- Eça and Hoekstra (2014, section 2.1) are stricter: the iterative error "should be two to three
  orders of magnitude smaller than the discretization error", after their 2009 study. Pass
  `ratio=100` or `1000` for that margin. In the ITTC example (7.5-03-02-01, section 2.3.1) the
  iterative uncertainties are about two orders below the grid uncertainty on grids 2-4 and one
  order below on grid 1, and are treated as negligible.

In a study, each `QoIResult` carries `iterative` (one result per level, finest first) and
`contamination`, next to `gci`. They are separate fields: a QoI's grid study is clean only when
`gci.clean_pass` and `contamination.clean_pass` both hold.

## Histories in a study

- Table QoIs: every row of every file matching `file`, joined in start-time order. Rows that a
  restart file covers again come from the restart file. `scale` is applied to the history as to
  the value.
- Profile QoIs: the value is the extremum of the last row; the history is the fitted extremum of
  every row. To be judged, a profile has to be written during the run, not only at the end.

## The committed studies

- Duct: f Re every 10 iterations, 800 samples; the window is the last 80 (iterations 7210 to
  8000). Every level is converged, with a relative range of at most 1.4e-12. The largest
  $u_\text{it}/U$ is 3.7e-9.
- Cavity: the Ghia points every 0.05 s (200 samples) and the profiles every 0.05 s from
  t = 7.5 s (51 rows). Both windows are the last 50 samples, t = 7.55 to 10 s. Every QoI is
  converged on every level. The largest $u_\text{it}/U$ is 1.9e-9.

`tests/test_studies.py` checks both.

## Not covered

- Inner iterations of a transient run. Celik et al. ask for iterative convergence "at every time
  step". foam-verify reads the QoI's history in time, which for the cavity is the approach to
  steady state, not the convergence of each PISO step.
- Celik's Appendix A estimate from the principal eigenvalue (after Ferziger). foam-verify uses
  the history of the QoI instead, the "other rational way" that the appendix allows.
- A reference magnitude for a zero-mean QoI in `study.toml`.
