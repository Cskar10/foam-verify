# Verification report: pitzDaily

foam-verify 0.0.1, from `study.toml`: 4 levels, finest first; refined = mesh; refined directions d = 2; formal order 2.

## Verdict

**Not a clean pass.** 0 of 3 quantities of interest are clean passes.

| QoI | Finest grid | Relative U | Grid convergence | Clean pass |
|---|---|---|---|---|
| `dp0` | 16.48 +/- 1.31 | 8.0% | monotonic, p = 0.8456 | no |
| `dp` | -3.61 +/- 1.51 | 42% | monotonic, p = 0.8204 | no |
| `xR/H` | 6.837916 | n/a | divergence, R = 0.9983 | no |

What stops a clean pass:

- `dp0`: coarser triplet (grids 2-4): divergence, so the grids are not all in the asymptotic range; leave out a level that is too coarse rather than accept grids 1-3 alone
- `dp`: asymptotic-range ratio GCI_32/(r21^p GCI_21) = 0.8846 is outside [0.9, 1.1]: the grids may not be in the asymptotic range
- `dp`: coarser triplet (grids 2-4): divergence, so the grids are not all in the asymptotic range; leave out a level that is too coarse rather than accept grids 1-3 alone
- `dp`: level 28k: the window holds 0 full cycle(s) of the oscillation; ITTC 7.5-03-02-01 takes the range over the last 2 periods, so u_it may understate the amplitude and drift cannot be told from a slow oscillation: widen the window
- `xR/H`: convergence ratio R = (phi2 - phi1)/(phi3 - phi2) = 0.9983: R >= ln r21 / ln r32 = 0.9922, monotonic divergence (Eca and Hoekstra 2014)
- `xR/H`: the solution is not grid-converged, so no GCI is given

## Levels

| Level | Folder | Cells | r to the next coarser |
|---|---|---|---|
| 139k | `n139k` | 139,025 | 1.494 |
| 62k | `n62k` | 62,257 | 1.499 |
| 28k | `n28k` | 27,703 | 1.505 |
| 12k | `n12k` | 12,225 |  |

## Settings consistency

**Pass.** The levels differ only in the mesh.

Compared on every level: `system/fvSchemes`, `system/fvSolution`, `constant/transportProperties`, `constant/turbulenceProperties`, `0/U`, `0/epsilon`, `0/k`, `0/nut`, `0/p`, `system/controlDict`.

## `dp0`

**Not a clean pass.** 16.48 +/- 1.31 (GCI, 8.0%); band 15.17 to 17.79.

From `postProcessing/pressureDrop/*/multiFieldValue.dat`, column `Group1`, mean over the window; window: the last 10% of the samples, at least 50.

| Check | Result | Detail |
|---|---|---|
| Grid convergence | pass | grids 1-3: convergence ratio R = 0.7054: monotonic convergence (0 < R < 0.9922) |
| Refinement ratio | pass | r21 = 1.494, r32 = 1.499; at least 1.3 (Celik et al. 2008, step 2) |
| Observed order | pass | p = 0.8456 (fixed-point iteration, 6 steps), within [0.5, 4] for a formal order of 2, so Fs = 1.25 |
| Asymptotic range | pass | GCI_32 / (r21^p GCI_21) = 1.026, within [0.9, 1.1] |
| Coarser triplets | fail | grids 2-4: divergence, R = 1.084 |
| Iterative convergence | pass | converged on every level (tol 0.001) |
| Iterative error | pass | largest u_it / U = 0.0031 (28k), within 1/10 (Celik et al. 2008, Appendix A) |
| Settings consistency | pass | the levels differ only in the mesh (10 files compared) |
| Refined directions | pass | dim = 2, with empty or wedge patches on every level: frontAndBack |
| Refinement scope | assumed | scope mesh: assumes every cell, near-wall layers included, was refined by the same ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells) |

| Level | Value | Iterative | Window | Relative range | Relative drift | u_it | u_it / U |
|---|---|---|---|---|---|---|---|
| 139k | 16.47793 | converged | 80 of 800, 7210 to 8000 | 0.00020 | -0.00013 | 0.0016 | 0.0012 |
| 62k | 16.05319 | converged | 80 of 800, 7210 to 8000 | 0.00024 | -2.1e-05 | 0.0019 | 0.0015 |
| 28k | 15.45108 | converged | 80 of 800, 7210 to 8000 | 0.00052 | -5.6e-05 | 0.0040 | 0.0031 |
| 12k | 14.89561 | converged | 80 of 800, 7210 to 8000 | 2.6e-05 | -1.2e-05 | 0.00020 | 0.00015 |

Richardson extrapolation, grids 1-3: phi_ext = 17.52805, e_a = 2.6%, e_ext = 6.0%, GCI_fine = 8.0%, GCI_32 = 11%, Fs = 1.25.

| Grids | Convergence | Result | Relative U |
|---|---|---|---|
| 1-3 | monotonic, p = 0.8456 | 16.48 +/- 1.31 | 8.0% |
| 2-4 | divergence, R = 1.084 | 16.05319 | n/a |

Notes:

- 4 grids: one result per consecutive triplet; the verdict is from grids 1-3.

## `dp`

**Not a clean pass.** -3.61 +/- 1.51 (GCI, 42%); band -5.12 to -2.10.

From `postProcessing/pressureDrop/*/multiFieldValue.dat`, column `Group0`, mean over the window; window: the last 10% of the samples, at least 50.

| Check | Result | Detail |
|---|---|---|
| Grid convergence | pass | grids 1-3: convergence ratio R = 0.7126: monotonic convergence (0 < R < 0.9922) |
| Refinement ratio | pass | r21 = 1.494, r32 = 1.499; at least 1.3 (Celik et al. 2008, step 2) |
| Observed order | pass | p = 0.8204 (fixed-point iteration, 6 steps), within [0.5, 4] for a formal order of 2, so Fs = 1.25 |
| Asymptotic range | fail | GCI_32 / (r21^p GCI_21) = 0.8846, outside [0.9, 1.1] |
| Coarser triplets | fail | grids 2-4: divergence, R = 1.033 |
| Iterative convergence | fail | converged on 139k, 62k, 12k; oscillating on 28k; warnings on 28k (tol 0.001) |
| Iterative error | pass | largest u_it / U = 0.0028 (28k), within 1/10 (Celik et al. 2008, Appendix A) |
| Settings consistency | pass | the levels differ only in the mesh (10 files compared) |
| Refined directions | pass | dim = 2, with empty or wedge patches on every level: frontAndBack |
| Refinement scope | assumed | scope mesh: assumes every cell, near-wall layers included, was refined by the same ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells) |

| Level | Value | Iterative | Window | Relative range | Relative drift | u_it | u_it / U |
|---|---|---|---|---|---|---|---|
| 139k | -3.607508 | converged | 80 of 800, 7210 to 8000 | 0.00093 | -0.00051 | 0.0017 | 0.0011 |
| 62k | -4.078260 | converged | 80 of 800, 7210 to 8000 | 0.00095 | -0.00010 | 0.0019 | 0.0013 |
| 28k | -4.738841 | oscillating | 80 of 800, 7210 to 8000 | 0.0018 | -0.00013 | 0.0042 | 0.0028 |
| 12k | -5.378197 | converged | 80 of 800, 7210 to 8000 | 7.5e-05 | 3.5e-06 | 0.00020 | 0.00013 |

Richardson extrapolation, grids 1-3: phi_ext = -2.401496, e_a = 13%, e_ext = 50%, GCI_fine = 42%, GCI_32 = 51%, Fs = 1.25.

| Grids | Convergence | Result | Relative U |
|---|---|---|---|
| 1-3 | monotonic, p = 0.8204 | -3.61 +/- 1.51 | 42% |
| 2-4 | divergence, R = 1.033 | -4.078260 | n/a |

Notes:

- 4 grids: one result per consecutive triplet; the verdict is from grids 1-3.
- level 28k: oscillating, but u_it = 0.00421 is 0.00279 of U, below 1/10

## `xR/H`

**Not a clean pass.** 6.837916, with no uncertainty estimate.

From `postProcessing/lowerWallShear/*/wallShearStress_lowerWall.raw`, last change of sign of the x component along x, latest profile, times 39.3701; window: the last 100% of the samples, at least 11.

| Check | Result | Detail |
|---|---|---|
| Grid convergence | fail | grids 1-3: convergence ratio R = (phi2 - phi1)/(phi3 - phi2) = 0.9983: R >= ln r21 / ln r32 = 0.9922, monotonic divergence (Eca and Hoekstra 2014); the solution is not grid-converged, so no GCI is given |
| Refinement ratio | pass | r21 = 1.494, r32 = 1.499; at least 1.3 (Celik et al. 2008, step 2) |
| Observed order | n/a | not defined: divergence, R = 0.9983 |
| Asymptotic range | n/a | checked only for monotonic convergence |
| Coarser triplets | fail | grids 2-4: divergence, R = 1.645 |
| Iterative convergence | pass | converged on every level (tol 0.001) |
| Iterative error | n/a | no discretisation uncertainty U to compare with |
| Settings consistency | pass | the levels differ only in the mesh (10 files compared) |
| Refined directions | pass | dim = 2, with empty or wedge patches on every level: frontAndBack |
| Refinement scope | assumed | scope mesh: assumes every cell, near-wall layers included, was refined by the same ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells) |

| Level | Value | Iterative | Window | Relative range | Relative drift | u_it | u_it / U |
|---|---|---|---|---|---|---|---|
| 139k | 6.837916 | converged | 11 of 11, 6000 to 8000 | 0.00062 | 0.00018 | 0.0021 |  |
| 62k | 6.909065 | converged | 11 of 11, 6000 to 8000 | 8.4e-05 | -6.7e-06 | 0.00029 |  |
| 28k | 6.980334 | converged | 11 of 11, 6000 to 8000 | 0.00092 | 1.1e-05 | 0.0032 |  |
| 12k | 7.023653 | converged | 11 of 11, 6000 to 8000 | 3.3e-05 | -1.7e-05 | 0.00011 |  |

| Grids | Convergence | Result | Relative U |
|---|---|---|---|
| 1-3 | divergence, R = 0.9983 | 6.837916 | n/a |
| 2-4 | divergence, R = 1.645 | 6.909065 | n/a |

Notes:

- 4 grids: one result per consecutive triplet; the verdict is from grids 1-3.
- coarser triplet (grids 2-4): divergence
- level 139k: last crossing at x = 0.173683 (t = 8000)
- level 62k: last crossing at x = 0.17549 (t = 8000)
- level 28k: last crossing at x = 0.1773 (t = 8000)
- level 12k: last crossing at x = 0.178401 (t = 8000)

## Method

- Grid convergence after Celik et al. (2008), with the convergence types of Eça and Hoekstra (2014): Fs = 1.25 on three or more grids, and 3 on two grids or when p is outside [0.5, 4]; refinement ratios of at least 1.3; an asymptotic-range ratio within [0.9, 1.1]; with four or more grids, every coarser triplet converges monotonically too. An oscillatory triplet gets a spread bound and never a clean pass (foam-verify docs/gci.md).
- Iterative convergence of each QoI from its own history over the window given with it: converged when its relative range and relative drift are within tol, and u_it is half the range. On the grids behind the result, u_it must be at most U/10 (Celik et al. 2008, Appendix A; docs/iterative.md).
- Settings consistency: the schemes, solver settings, physical properties, boundary conditions and near-wall layer settings of the levels, compared entry by entry (docs/consistency.md).
- U is the uncertainty of the finest-grid value, and the band is that value +/- U. A QoI is a clean pass only when no check fails (docs/report.md).
