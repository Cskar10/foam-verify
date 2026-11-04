# Verification report: lid-driven-cavity-re100

foam-verify 0.1.0, from `study.toml`: 4 levels, finest first; refined = mesh; grid sequence structured; refined directions d = 2; formal order 2.

## Verdict

**Clean pass.** 6 of 6 quantities of interest are clean passes.

| QoI | Finest grid | Relative U | Grid convergence | Clean pass |
|---|---|---|---|---|
| `u(y=0.5)` | -0.208892 +/- 0.000328 | 0.16% | monotonic, p = 1.967 | yes |
| `u(y=0.4531)` | -0.213682 +/- 0.000379 | 0.18% | monotonic, p = 1.942 | yes |
| `u(y=0.8516)` | 0.236393 +/- 0.000126 | 0.053% | monotonic, p = 2.294 | yes |
| `u_min` | -0.213760 +/- 0.000366 | 0.17% | monotonic, p = 1.977 | yes |
| `v_max` | 0.179365 +/- 0.000257 | 0.14% | monotonic, p = 2.152 | yes |
| `v_min` | -0.253585 +/- 0.000275 | 0.11% | monotonic, p = 2.523 | yes |

## Reference comparison

Apart from the verdict: the comparison error E = S - D sets the finest-grid value S against a reference value D, every uncertainty at 95%. The verdict says whether S is converged; this says how far it is from D (foam-verify docs/compare.md).

| QoI | Reference | Kind | D +/- U_D | E = S - D | E / \|D\| | \|E\| / U | Outcome |
|---|---|---|---|---|---|---|---|
| `u(y=0.5)` | Ghia et al. (1982) | code | -0.20581 | -0.00308 | -1.5% | 9.4 U_num | outside uncertainty |
| `u(y=0.4531)` | Ghia et al. (1982) | code | -0.2109 | -0.00278 | -1.3% | 7.34 U_num | outside uncertainty |
| `u(y=0.8516)` | Ghia et al. (1982) | code | 0.23151 | 0.00488 | 2.1% | 38.9 U_num | outside uncertainty |
| `u(y=0.5)` | Marchi et al. (2009) | code | -0.2091491 +/- 8.6e-09 | 0.000257 | 0.12% | 0.785 U_val | within uncertainty |
| `u_min` | Marchi et al. (2009) | code | -0.2140417 +/- 1.6e-06 | 0.000281 | 0.13% | 0.769 U_val | within uncertainty |
| `v_max` | Marchi et al. (2009) | code | 0.1795728 +/- 2.7e-08 | -0.000208 | -0.12% | 0.81 U_val | within uncertainty |
| `v_min` | Marchi et al. (2009) | code | -0.253804 +/- 1.1e-05 | 0.000219 | 0.086% | 0.797 U_val | within uncertainty |

- `u(y=0.5)` against Ghia, Ghia and Shin (1982), J. Comput. Phys. 48, 387-411, Table I (p. 398), Re = 100, y = 0.5000 (grid point 65 of 129): E = S - D = -0.00308 is beyond the simulation's numerical uncertainty (|E| = 9.4 U_num); the reference states no uncertainty, and would need one of at least 0.00306 for the two to agree
- `u(y=0.4531)` against Ghia, Ghia and Shin (1982), J. Comput. Phys. 48, 387-411, Table I (p. 398), Re = 100, y = 0.4531 (grid point 59 of 129): E = S - D = -0.00278 is beyond the simulation's numerical uncertainty (|E| = 7.34 U_num); the reference states no uncertainty, and would need one of at least 0.00276 for the two to agree
- `u(y=0.8516)` against Ghia, Ghia and Shin (1982), J. Comput. Phys. 48, 387-411, Table I (p. 398), Re = 100, y = 0.8516 (grid point 110 of 129): E = S - D = 0.00488 is beyond the simulation's numerical uncertainty (|E| = 38.9 U_num); the reference states no uncertainty, and would need one of at least 0.00488 for the two to agree
- `u(y=0.5)` against Marchi, Suero and Araki (2009), J. Braz. Soc. Mech. Sci. & Eng. 31(3), 186-198, Tables 6 and 7 (pp. 194-195), Re = 100, u(0.5;0.5): E = S - D = 0.000257, |E| = 0.785 U_val: the two solutions agree within their numerical uncertainties; U_val = sqrt(U_num^2 + U_input^2 + U_D^2) = 0.000328 (Eça, Dowding and Roache 2020, Eq. 15: independent errors)
- `u_min` against Marchi, Suero and Araki (2009), J. Braz. Soc. Mech. Sci. & Eng. 31(3), 186-198, Tables 6 and 7 (pp. 194-195), Re = 100, umin: E = S - D = 0.000281, |E| = 0.769 U_val: the two solutions agree within their numerical uncertainties; U_val = sqrt(U_num^2 + U_input^2 + U_D^2) = 0.000366 (Eça, Dowding and Roache 2020, Eq. 15: independent errors)
- `v_max` against Marchi, Suero and Araki (2009), J. Braz. Soc. Mech. Sci. & Eng. 31(3), 186-198, Tables 6 and 7 (pp. 194-195), Re = 100, vmax: E = S - D = -0.000208, |E| = 0.81 U_val: the two solutions agree within their numerical uncertainties; U_val = sqrt(U_num^2 + U_input^2 + U_D^2) = 0.000257 (Eça, Dowding and Roache 2020, Eq. 15: independent errors)
- `v_min` against Marchi, Suero and Araki (2009), J. Braz. Soc. Mech. Sci. & Eng. 31(3), 186-198, Tables 6 and 7 (pp. 194-195), Re = 100, vmin: E = S - D = 0.000219, |E| = 0.797 U_val: the two solutions agree within their numerical uncertainties; U_val = sqrt(U_num^2 + U_input^2 + U_D^2) = 0.000275 (Eça, Dowding and Roache 2020, Eq. 15: independent errors)

Warnings:

- Ghia et al. (1982) on `u(y=0.5)`, `u(y=0.4531)`, `u(y=0.8516)`: the reference states no uncertainty, so U_val is incomplete

Notes:

- Ghia et al. (1982) on `u(y=0.5)`, `u(y=0.4531)`, `u(y=0.8516)`; Marchi et al. (2009) on `u(y=0.5)`, `u_min`, `v_max`, `v_min`: a code reference makes this a code-to-code comparison: E is the difference of two numerical errors and says nothing about the model

## Levels

| Level | Folder | Cells | r to the next coarser |
|---|---|---|---|
| 160x160 | `n160` | 25,600 | 2.000 |
| 80x80 | `n80` | 6,400 | 2.000 |
| 40x40 | `n40` | 1,600 | 2.000 |
| 20x20 | `n20` | 400 |  |

## Settings consistency

**Pass.** No difference blocks a clean pass; the differences below are noted.

Compared on every level: `system/fvSchemes`, `system/fvSolution`, `constant/transportProperties`, `0/U`, `0/p`, `system/controlDict`.

| File | Entry | 160x160 | 80x80 | 40x40 | 20x20 | Blocks |
|---|---|---|---|---|---|---|
| `system/controlDict` | `deltaT` | 0.0003125 | 0.000625 | 0.00125 | 0.0025 | no |

## `u(y=0.5)`

**Clean pass.** -0.208892 +/- 0.000328 (GCI, 0.16%); band -0.209220 to -0.208564.

From `postProcessing/ghiaPoints/*/U`, column `0`, x component, last value; window: the last 10% of the samples, at least 50.

| Check | Result | Detail |
|---|---|---|
| Grid convergence | pass | grids 1-3: convergence ratio R = 0.2558: monotonic convergence (0 < R < 1) |
| Refinement ratio | pass | r21 = 2.000, r32 = 2.000; at least 1.3 (Celik et al. 2008, step 2) |
| Observed order | pass | p = 1.967 (closed form, equal ratios), within [0.5, 4] for a formal order of 2; Fs = 1.25 |
| Asymptotic range | pass | GCI_32 / (r21^p GCI_21) = 1.004, within [0.9, 1.1] |
| Coarser triplets | pass | grids 2-4: monotonic, p = 1.867 |
| Iterative convergence | pass | converged on every level (tol 0.001) |
| Iterative error | pass | largest u_it / U = 1.5e-09 (40x40), within 1/100 (ASME V&V 20, para. 2-4) |
| Settings consistency | pass | no difference blocks (6 files compared); noted: system/controlDict deltaT |
| Refined directions | pass | dim = 2, with empty or wedge patches on every level: frontAndBack |
| Refinement scope | assumed | scope mesh: assumes every cell, near-wall layers included, was refined by the same ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells) |
| Grid sequence | assumed | grid sequence structured: the levels refine one base grid systematically (the base grid may itself be unstructured), so Fs = 1.25 with three or more grids (ASME V&V 20, para. 2-4.1) |

| Level | Value | Iterative | Window | Relative range | Relative drift | u_it | u_it / U |
|---|---|---|---|---|---|---|---|
| 160x160 | -0.2088918 | converged | 50 of 200, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 80x80 | -0.2081288 | converged | 50 of 200, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 40x40 | -0.2051463 | converged | 50 of 200, 7.55 to 10 | 4.9e-12 | 1.1e-12 | 5.0e-13 | 1.5e-09 |
| 20x20 | -0.1942651 | converged | 50 of 200, 7.55 to 10 | 5.1e-12 | -1.7e-12 | 5.0e-13 | 1.5e-09 |

Richardson extrapolation, grids 1-3: phi_ext = -0.2091541, e_a = 0.37%, e_ext = 0.13%, GCI_fine = 0.16%, GCI_32 = 0.62%, Fs = 1.25.

| Grids | Convergence | Result | Relative U |
|---|---|---|---|
| 1-3 | monotonic, p = 1.967 | -0.208892 +/- 0.000328 | 0.16% |
| 2-4 | monotonic, p = 1.867 | -0.20813 +/- 0.00141 | 0.68% |

Notes:

- 4 grids: one result per consecutive triplet; the verdict is from grids 1-3.

## `u(y=0.4531)`

**Clean pass.** -0.213682 +/- 0.000379 (GCI, 0.18%); band -0.214061 to -0.213304.

From `postProcessing/ghiaPoints/*/U`, column `1`, x component, last value; window: the last 10% of the samples, at least 50.

| Check | Result | Detail |
|---|---|---|
| Grid convergence | pass | grids 1-3: convergence ratio R = 0.2603: monotonic convergence (0 < R < 1) |
| Refinement ratio | pass | r21 = 2.000, r32 = 2.000; at least 1.3 (Celik et al. 2008, step 2) |
| Observed order | pass | p = 1.942 (closed form, equal ratios), within [0.5, 4] for a formal order of 2; Fs = 1.25 |
| Asymptotic range | pass | GCI_32 / (r21^p GCI_21) = 1.004, within [0.9, 1.1] |
| Coarser triplets | pass | grids 2-4: monotonic, p = 1.827 |
| Iterative convergence | pass | converged on every level (tol 0.001) |
| Iterative error | pass | largest u_it / U = 1.3e-09 (40x40), within 1/100 (ASME V&V 20, para. 2-4) |
| Settings consistency | pass | no difference blocks (6 files compared); noted: system/controlDict deltaT |
| Refined directions | pass | dim = 2, with empty or wedge patches on every level: frontAndBack |
| Refinement scope | assumed | scope mesh: assumes every cell, near-wall layers included, was refined by the same ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells) |
| Grid sequence | assumed | grid sequence structured: the levels refine one base grid systematically (the base grid may itself be unstructured), so Fs = 1.25 with three or more grids (ASME V&V 20, para. 2-4.1) |

| Level | Value | Iterative | Window | Relative range | Relative drift | u_it | u_it / U |
|---|---|---|---|---|---|---|---|
| 160x160 | -0.2136825 | converged | 50 of 200, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 80x80 | -0.2128210 | converged | 50 of 200, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 40x40 | -0.2095110 | converged | 50 of 200, 7.55 to 10 | 4.8e-12 | 3.6e-12 | 5.0e-13 | 1.3e-09 |
| 20x20 | -0.1977705 | converged | 50 of 200, 7.55 to 10 | 5.1e-12 | 1.4e-12 | 5.0e-13 | 1.3e-09 |

Richardson extrapolation, grids 1-3: phi_ext = -0.2139856, e_a = 0.40%, e_ext = 0.14%, GCI_fine = 0.18%, GCI_32 = 0.68%, Fs = 1.25.

| Grids | Convergence | Result | Relative U |
|---|---|---|---|
| 1-3 | monotonic, p = 1.942 | -0.213682 +/- 0.000379 | 0.18% |
| 2-4 | monotonic, p = 1.827 | -0.21282 +/- 0.00162 | 0.76% |

Notes:

- 4 grids: one result per consecutive triplet; the verdict is from grids 1-3.

## `u(y=0.8516)`

**Clean pass.** 0.236393 +/- 0.000126 (GCI, 0.053%); band 0.236267 to 0.236519.

From `postProcessing/ghiaPoints/*/U`, column `2`, x component, last value; window: the last 10% of the samples, at least 50.

| Check | Result | Detail |
|---|---|---|
| Grid convergence | pass | grids 1-3: convergence ratio R = 0.2039: monotonic convergence (0 < R < 1) |
| Refinement ratio | pass | r21 = 2.000, r32 = 2.000; at least 1.3 (Celik et al. 2008, step 2) |
| Observed order | pass | p = 2.294 (closed form, equal ratios), within [0.5, 4] for a formal order of 2; Fs = 1.25; U uses p = 2, the formal order (ASME V&V 20, Appendix C-4) |
| Asymptotic range | pass | GCI_32 / (r21^p GCI_21) = 1.001, within [0.9, 1.1] |
| Coarser triplets | pass | grids 2-4: monotonic, p = 1.737 |
| Iterative convergence | pass | converged on every level (tol 0.001) |
| Iterative error | pass | largest u_it / U = 0 (160x160), within 1/100 (ASME V&V 20, para. 2-4) |
| Settings consistency | pass | no difference blocks (6 files compared); noted: system/controlDict deltaT |
| Refined directions | pass | dim = 2, with empty or wedge patches on every level: frontAndBack |
| Refinement scope | assumed | scope mesh: assumes every cell, near-wall layers included, was refined by the same ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells) |
| Grid sequence | assumed | grid sequence structured: the levels refine one base grid systematically (the base grid may itself be unstructured), so Fs = 1.25 with three or more grids (ASME V&V 20, para. 2-4.1) |

| Level | Value | Iterative | Window | Relative range | Relative drift | u_it | u_it / U |
|---|---|---|---|---|---|---|---|
| 160x160 | 0.2363930 | converged | 50 of 200, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 80x80 | 0.2360915 | converged | 50 of 200, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 40x40 | 0.2346121 | converged | 50 of 200, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 20x20 | 0.2296808 | converged | 50 of 200, 7.55 to 10 | 4.4e-12 | -7.1e-13 | 5.0e-13 | 4.0e-09 |

Richardson extrapolation, grids 1-3 (at the observed order; U uses p = 2): phi_ext = 0.2364703, e_a = 0.13%, e_ext = 0.033%, GCI_fine = 0.041%, GCI_32 = 0.20%, Fs = 1.25.

| Grids | Convergence | Result | Relative U |
|---|---|---|---|
| 1-3 | monotonic, p = 2.294 | 0.236393 +/- 0.000126 | 0.053% |
| 2-4 | monotonic, p = 1.737 | 0.236091 +/- 0.000792 | 0.34% |

Notes:

- observed order p = 2.294 is above the formal order 2, so the uncertainty uses p = 2 (ASME V&V 20, Appendix C-4); the Richardson numbers and the asymptotic-range check use the observed p
- 4 grids: one result per consecutive triplet; the verdict is from grids 1-3.

## `u_min`

**Clean pass.** -0.213760 +/- 0.000366 (GCI, 0.17%); band -0.214126 to -0.213395.

From `postProcessing/verticalCentreline/*/U`, minimum of the x component along y, latest profile; window: the last 10% of the samples, at least 50.

| Check | Result | Detail |
|---|---|---|
| Grid convergence | pass | grids 1-3: convergence ratio R = 0.254: monotonic convergence (0 < R < 1) |
| Refinement ratio | pass | r21 = 2.000, r32 = 2.000; at least 1.3 (Celik et al. 2008, step 2) |
| Observed order | pass | p = 1.977 (closed form, equal ratios), within [0.5, 4] for a formal order of 2; Fs = 1.25 |
| Asymptotic range | pass | GCI_32 / (r21^p GCI_21) = 1.004, within [0.9, 1.1] |
| Coarser triplets | pass | grids 2-4: monotonic, p = 1.776 |
| Iterative convergence | pass | converged on every level (tol 0.001) |
| Iterative error | pass | largest u_it / U = 1.3e-09 (160x160), within 1/100 (ASME V&V 20, para. 2-4) |
| Settings consistency | pass | no difference blocks (6 files compared); noted: system/controlDict deltaT |
| Refined directions | pass | dim = 2, with empty or wedge patches on every level: frontAndBack |
| Refinement scope | assumed | scope mesh: assumes every cell, near-wall layers included, was refined by the same ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells) |
| Grid sequence | assumed | grid sequence structured: the levels refine one base grid systematically (the base grid may itself be unstructured), so Fs = 1.25 with three or more grids (ASME V&V 20, para. 2-4.1) |

| Level | Value | Iterative | Window | Relative range | Relative drift | u_it | u_it / U |
|---|---|---|---|---|---|---|---|
| 160x160 | -0.2137605 | converged | 50 of 51, 7.55 to 10 | 4.4e-12 | -2.3e-12 | 4.7e-13 | 1.3e-09 |
| 80x80 | -0.2129010 | converged | 50 of 51, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 40x40 | -0.2095177 | converged | 50 of 51, 7.55 to 10 | 4.1e-12 | 2.7e-12 | 4.3e-13 | 1.2e-09 |
| 20x20 | -0.1979287 | converged | 50 of 51, 7.55 to 10 | 1.0e-12 | 1.6e-13 | 1.0e-13 | 2.8e-10 |

Richardson extrapolation, grids 1-3: phi_ext = -0.2140532, e_a = 0.40%, e_ext = 0.14%, GCI_fine = 0.17%, GCI_32 = 0.68%, Fs = 1.25.

| Grids | Convergence | Result | Relative U |
|---|---|---|---|
| 1-3 | monotonic, p = 1.977 | -0.213760 +/- 0.000366 | 0.17% |
| 2-4 | monotonic, p = 1.776 | -0.21290 +/- 0.00174 | 0.82% |

Notes:

- 4 grids: one result per consecutive triplet; the verdict is from grids 1-3.
- level 160x160: min at y = 0.0457961 (t = 10)
- level 80x80: min at y = 0.0459923 (t = 10)
- level 40x40: min at y = 0.0451648 (t = 10)
- level 20x20: min at y = 0.0450426 (t = 10)

## `v_max`

**Clean pass.** 0.179365 +/- 0.000257 (GCI, 0.14%); band 0.179108 to 0.179622.

From `postProcessing/horizontalCentreline/*/U`, maximum of the y component along x, latest profile; window: the last 10% of the samples, at least 50.

| Check | Result | Detail |
|---|---|---|
| Grid convergence | pass | grids 1-3: convergence ratio R = 0.2249: monotonic convergence (0 < R < 1) |
| Refinement ratio | pass | r21 = 2.000, r32 = 2.000; at least 1.3 (Celik et al. 2008, step 2) |
| Observed order | pass | p = 2.152 (closed form, equal ratios), within [0.5, 4] for a formal order of 2; Fs = 1.25; U uses p = 2, the formal order (ASME V&V 20, Appendix C-4) |
| Asymptotic range | pass | GCI_32 / (r21^p GCI_21) = 1.003, within [0.9, 1.1] |
| Coarser triplets | pass | grids 2-4: monotonic, p = 1.764 |
| Iterative convergence | pass | converged on every level (tol 0.001) |
| Iterative error | pass | largest u_it / U = 1.9e-09 (160x160), within 1/100 (ASME V&V 20, para. 2-4) |
| Settings consistency | pass | no difference blocks (6 files compared); noted: system/controlDict deltaT |
| Refined directions | pass | dim = 2, with empty or wedge patches on every level: frontAndBack |
| Refinement scope | assumed | scope mesh: assumes every cell, near-wall layers included, was refined by the same ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells) |
| Grid sequence | assumed | grid sequence structured: the levels refine one base grid systematically (the base grid may itself be unstructured), so Fs = 1.25 with three or more grids (ASME V&V 20, para. 2-4.1) |

| Level | Value | Iterative | Window | Relative range | Relative drift | u_it | u_it / U |
|---|---|---|---|---|---|---|---|
| 160x160 | 0.1793649 | converged | 50 of 51, 7.55 to 10 | 5.3e-12 | 7.1e-12 | 4.8e-13 | 1.9e-09 |
| 80x80 | 0.1787486 | converged | 50 of 51, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 40x40 | 0.1760088 | converged | 50 of 51, 7.55 to 10 | 2.1e-12 | 5.7e-14 | 1.8e-13 | 7.1e-10 |
| 20x20 | 0.1667047 | converged | 50 of 51, 7.55 to 10 | 6.5e-12 | -4.4e-12 | 5.4e-13 | 2.1e-09 |

Richardson extrapolation, grids 1-3 (at the observed order; U uses p = 2): phi_ext = 0.1795437, e_a = 0.34%, e_ext = 0.10%, GCI_fine = 0.12%, GCI_32 = 0.56%, Fs = 1.25.

| Grids | Convergence | Result | Relative U |
|---|---|---|---|
| 1-3 | monotonic, p = 2.152 | 0.179365 +/- 0.000257 | 0.14% |
| 2-4 | monotonic, p = 1.764 | 0.17875 +/- 0.00143 | 0.80% |

Notes:

- observed order p = 2.152 is above the formal order 2, so the uncertainty uses p = 2 (ASME V&V 20, Appendix C-4); the Richardson numbers and the asymptotic-range check use the observed p
- 4 grids: one result per consecutive triplet; the verdict is from grids 1-3.
- level 160x160: max at x = 0.023744 (t = 10)
- level 80x80: max at x = 0.0237692 (t = 10)
- level 40x40: max at x = 0.0248082 (t = 10)
- level 20x20: max at x = 0.0249271 (t = 10)

## `v_min`

**Clean pass.** -0.253585 +/- 0.000275 (GCI, 0.11%); band -0.253860 to -0.253310.

From `postProcessing/horizontalCentreline/*/U`, minimum of the y component along x, latest profile; window: the last 10% of the samples, at least 50.

| Check | Result | Detail |
|---|---|---|
| Grid convergence | pass | grids 1-3: convergence ratio R = 0.174: monotonic convergence (0 < R < 1) |
| Refinement ratio | pass | r21 = 2.000, r32 = 2.000; at least 1.3 (Celik et al. 2008, step 2) |
| Observed order | pass | p = 2.523 (closed form, equal ratios), within [0.5, 4] for a formal order of 2; Fs = 1.25; U uses p = 2, the formal order (ASME V&V 20, Appendix C-4) |
| Asymptotic range | pass | GCI_32 / (r21^p GCI_21) = 1.003, within [0.9, 1.1] |
| Coarser triplets | pass | grids 2-4: monotonic, p = 1.687 |
| Iterative convergence | pass | converged on every level (tol 0.001) |
| Iterative error | pass | largest u_it / U = 0 (160x160), within 1/100 (ASME V&V 20, para. 2-4) |
| Settings consistency | pass | no difference blocks (6 files compared); noted: system/controlDict deltaT |
| Refined directions | pass | dim = 2, with empty or wedge patches on every level: frontAndBack |
| Refinement scope | assumed | scope mesh: assumes every cell, near-wall layers included, was refined by the same ratio (Celik et al. 2008, step 2: systematic refinement, geometrically similar cells) |
| Grid sequence | assumed | grid sequence structured: the levels refine one base grid systematically (the base grid may itself be unstructured), so Fs = 1.25 with three or more grids (ASME V&V 20, para. 2-4.1) |

| Level | Value | Iterative | Window | Relative range | Relative drift | u_it | u_it / U |
|---|---|---|---|---|---|---|---|
| 160x160 | -0.2535850 | converged | 50 of 51, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 80x80 | -0.2529257 | converged | 50 of 51, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 40x40 | -0.2491370 | converged | 50 of 51, 7.55 to 10 | 0 | 0 | 0 | 0 |
| 20x20 | -0.2369372 | converged | 50 of 51, 7.55 to 10 | 9.8e-13 | 1.4e-13 | 1.2e-13 | 4.2e-10 |

Richardson extrapolation, grids 1-3 (at the observed order; U uses p = 2): phi_ext = -0.2537239, e_a = 0.26%, e_ext = 0.055%, GCI_fine = 0.068%, GCI_32 = 0.39%, Fs = 1.25.

| Grids | Convergence | Result | Relative U |
|---|---|---|---|
| 1-3 | monotonic, p = 2.523 | -0.253585 +/- 0.000275 | 0.11% |
| 2-4 | monotonic, p = 1.687 | -0.25293 +/- 0.00213 | 0.84% |

Notes:

- observed order p = 2.523 is above the formal order 2, so the uncertainty uses p = 2 (ASME V&V 20, Appendix C-4); the Richardson numbers and the asymptotic-range check use the observed p
- 4 grids: one result per consecutive triplet; the verdict is from grids 1-3.
- level 160x160: min at x = 0.0811304 (t = 10)
- level 80x80: min at x = 0.0812033 (t = 10)
- level 40x40: min at x = 0.0822341 (t = 10)
- level 20x20: min at x = 0.0802133 (t = 10)

## Method

- Grid convergence after Celik et al. (2008), with the convergence types of Eça and Hoekstra (2014): Fs = 1.25 on three or more grids of a structured grid sequence, and 3 for an unstructured sequence (ASME V&V 20, para. 2-4.1), on two grids, or when p is outside [0.5, 4]; refinement ratios of at least 1.3; an asymptotic-range ratio within [0.9, 1.1]; with four or more grids, every coarser triplet converges monotonically too. Above the formal order, U uses the formal order (ASME V&V 20, Appendix C-4); the Richardson numbers and the checks keep the observed p. An oscillatory triplet gets a spread bound and never a clean pass (foam-verify docs/gci.md).
- Iterative convergence of each QoI from its own history over the window given with it: converged when its relative range and relative drift are within tol, and u_it is half the range. On the grids behind the result, u_it must be at most U/100 (ASME V&V 20, para. 2-4; docs/iterative.md).
- Settings consistency: the schemes, solver settings, physical properties, boundary conditions and near-wall layer settings of the levels, compared entry by entry (docs/consistency.md).
- U is the uncertainty of the finest-grid value, and the band is that value +/- U. A QoI is a clean pass only when no check fails (docs/report.md).
- Reference comparison, apart from the verdict: |E| against U_num for an exact reference (a code-verification check); against U_val = sqrt(U_num^2 + U_input^2 + U_D^2) for a code or experimental reference, or U_num alone, with a warning, when a code reference states no uncertainty; for an experiment, the case of Eça, Dowding and Roache (2020) with their constant C (ASME V&V 20; docs/compare.md).
