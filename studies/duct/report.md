# Verification report: square-duct

foam-verify 0.0.1, from `study.toml`: 4 levels, finest first; refined = mesh; grid sequence structured; refined directions d = 2; formal order 2.

## Verdict

**Clean pass.** 1 of 1 quantity of interest is a clean pass.

| QoI | Finest grid | Relative U | Grid convergence | Clean pass |
|---|---|---|---|---|
| `fRe` | 56.8997 +/- 0.0108 | 0.019% | monotonic, p = 1.995 | yes |

## Levels

| Level | Folder | Cells | r to the next coarser |
|---|---|---|---|
| 160x160 | `n160` | 25,600 | 2.000 |
| 80x80 | `n80` | 6,400 | 2.000 |
| 40x40 | `n40` | 1,600 | 2.000 |
| 20x20 | `n20` | 400 |  |

- dim = 2 with no empty or wedge patches: patches inlet and outlet have one face per cell on every level, so the mesh is one cell across them and that direction is not refined

## Settings consistency

**Pass.** The levels differ only in the mesh.

Compared on every level: `system/fvSchemes`, `system/fvSolution`, `system/fvOptions`, `constant/transportProperties`, `constant/turbulenceProperties`, `0/U`, `0/p`, `system/controlDict`.

## `fRe`

**Clean pass.** 56.8997 +/- 0.0108 (GCI, 0.019%); band 56.8890 to 56.9105.

From `postProcessing/wallStress/*/surfaceFieldValue.dat`, column `areaAverage(wallShearStress)`, x component, last value, times -800; window: the last 10% of the samples, at least 50.

| Check | Result | Detail |
|---|---|---|
| Grid convergence | pass | grids 1-3: convergence ratio R = 0.2509: monotonic convergence (0 < R < 1) |
| Refinement ratio | pass | r21 = 2.000, r32 = 2.000; at least 1.3 (Celik et al. 2008, step 2) |
| Observed order | pass | p = 1.995 (closed form, equal ratios), within [0.5, 4] for a formal order of 2; Fs = 1.25 |
| Asymptotic range | pass | GCI_32 / (r21^p GCI_21) = 1.000, within [0.9, 1.1] |
| Coarser triplets | pass | grids 2-4: monotonic, p = 1.980 |
| Iterative convergence | pass | converged on every level (tol 0.001) |
| Iterative error | pass | largest u_it / U = 3.7e-09 (160x160), within 1/10 (Celik et al. 2008, Appendix A) |
| Settings consistency | pass | the levels differ only in the mesh (8 files compared) |
| Refined directions | pass | dim = 2 with no empty or wedge patches: patches inlet and outlet have one face per cell on every level, so the mesh is one cell across them and that direction is not refined |
| Refinement scope | assumed | scope mesh: assumes every cell, near-wall layers included, was refined by the same ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells) |
| Grid sequence | assumed | grid sequence structured: the levels refine one base grid systematically (the base grid may itself be unstructured), so Fs = 1.25 with three or more grids (ASME V&V 20, para. 2-4.1) |

| Level | Value | Iterative | Window | Relative range | Relative drift | u_it | u_it / U |
|---|---|---|---|---|---|---|---|
| 160x160 | 56.89972 | converged | 80 of 800, 7210 to 8000 | 1.4e-12 | -1.4e-12 | 4.0e-11 | 3.7e-09 |
| 80x80 | 56.87400 | converged | 80 of 800, 7210 to 8000 | 0 | 0 | 0 | 0 |
| 40x40 | 56.77150 | converged | 80 of 800, 7210 to 8000 | 0 | 0 | 0 | 0 |
| 20x20 | 56.36707 | converged | 80 of 800, 7210 to 8000 | 0 | 0 | 0 | 0 |

Richardson extrapolation, grids 1-3: phi_ext = 56.90834, e_a = 0.045%, e_ext = 0.015%, GCI_fine = 0.019%, GCI_32 = 0.075%, Fs = 1.25.

| Grids | Convergence | Result | Relative U |
|---|---|---|---|
| 1-3 | monotonic, p = 1.995 | 56.8997 +/- 0.0108 | 0.019% |
| 2-4 | monotonic, p = 1.980 | 56.8740 +/- 0.0435 | 0.076% |

Notes:

- 4 grids: one result per consecutive triplet; the verdict is from grids 1-3.

## Method

- Grid convergence after Celik et al. (2008), with the convergence types of Eça and Hoekstra (2014): Fs = 1.25 on three or more grids of a structured grid sequence, and 3 for an unstructured sequence (ASME V&V 20, para. 2-4.1), on two grids, or when p is outside [0.5, 4]; refinement ratios of at least 1.3; an asymptotic-range ratio within [0.9, 1.1]; with four or more grids, every coarser triplet converges monotonically too. Above the formal order, U uses the formal order (ASME V&V 20, Appendix C-4); the Richardson numbers and the checks keep the observed p. An oscillatory triplet gets a spread bound and never a clean pass (foam-verify docs/gci.md).
- Iterative convergence of each QoI from its own history over the window given with it: converged when its relative range and relative drift are within tol, and u_it is half the range. On the grids behind the result, u_it must be at most U/10 (Celik et al. 2008, Appendix A; docs/iterative.md).
- Settings consistency: the schemes, solver settings, physical properties, boundary conditions and near-wall layer settings of the levels, compared entry by entry (docs/consistency.md).
- U is the uncertainty of the finest-grid value, and the band is that value +/- U. A QoI is a clean pass only when no check fails (docs/report.md).
