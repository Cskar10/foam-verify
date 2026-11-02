# Lid-driven cavity, Re = 100: the recognised benchmark

The `icoFoam` cavity at Re = 100 on four uniform grids, 20 x 20 to 160 x 160. There is no exact
solution; this study shows the GCI behaving on a standard benchmark with corner singularities.
foam-verify's report also compares seven QoI values with two published numerical solutions,
apart from the verdict: within the uncertainty against Marchi, Suero and Araki (2009), outside
it against Ghia, Ghia and Shin (1982) ([below](#against-two-reference-solutions)).

Velocities are in units of the lid speed U = 1 m/s; positions in units of the side L = 0.1 m.

| QoI | 160 x 160 | 80 x 80 | 40 x 40 | 20 x 20 |
|---|---|---|---|---|
| u at y = 0.5 | -0.2088918 | -0.2081288 | -0.2051463 | -0.1942651 |
| u at y = 0.4531 | -0.2136825 | -0.2128210 | -0.2095110 | -0.1977705 |
| u at y = 0.8516 | 0.2363930 | 0.2360915 | 0.2346121 | 0.2296808 |
| u_min, vertical centreline | -0.2137605 | -0.2129010 | -0.2095177 | -0.1979287 |
| v_max, horizontal centreline | 0.1793649 | 0.1787486 | 0.1760088 | 0.1667047 |
| v_min, horizontal centreline | -0.2535850 | -0.2529257 | -0.2491370 | -0.2369372 |

foam-verify on the three finest grids: every QoI converges monotonically and is a clean pass.

| QoI | p | Fine-grid result | Relative U | Extrapolated | Asymptotic ratio |
|---|---|---|---|---|---|
| u at y = 0.5 | 1.967 | -0.20889 +/- 0.00033 | 0.157% | -0.209154 | 1.0037 |
| u at y = 0.4531 | 1.942 | -0.21368 +/- 0.00038 | 0.177% | -0.213986 | 1.0040 |
| u at y = 0.8516 | 2.294 | 0.23639 +/- 0.00013 | 0.053% | 0.236470 | 1.0013 |
| u_min | 1.977 | -0.21376 +/- 0.00037 | 0.171% | -0.214053 | 1.0040 |
| v_max | 2.152 | 0.17936 +/- 0.00026 | 0.143% | 0.179544 | 1.0034 |
| v_min | 2.523 | -0.25359 +/- 0.00027 | 0.108% | -0.253724 | 1.0026 |

Where p is above 2 (u at y = 0.8516, v_max and v_min), the uncertainty uses p = 2, the formal
order, and is 1.15 to 1.58 times the GCI at the observed p; the extrapolated values and the
asymptotic ratios use the observed p ([docs/gci.md](../../docs/gci.md), Observed order above the
formal order).

- The fine-grid minimum of u lies at y = 0.4580, the maximum of v at x = 0.2374 and the minimum
  of v at x = 0.8113.
- On the coarser triplet (80, 40, 20) every QoI is also monotonic, with p between 1.69 and 1.87.
  The observed order moves to about 2 (1.94 to 2.52) on the finest triplet. A lower order on
  coarse grids is consistent with the two lid corners, where the velocity is discontinuous.
- `tests/test_studies.py` reads this folder back and checks the verdicts, the orders and the
  asymptotic ratios.
- foam-verify's full report on this study is [report.md](report.md) (JSON:
  [report.json](report.json)).

## Against two reference solutions

`study.toml` lists values from two published solutions as references of kind `code`, and
foam-verify's report compares each with the finest-grid value
([docs/compare.md](../../docs/compare.md)). The comparisons are no part of the verdict above.

### Marchi et al. (2009): within the uncertainty

Marchi, Suero and Araki (2009), J. Braz. Soc. Mech. Sci. & Eng. 31(3), 186-198, solved the
cavity with second-order finite volumes on grids up to 1024 x 1024 and up to nine Richardson
extrapolations. Their Table 6 (p. 194) gives the values at Re = 100, and Table 7 (p. 195) an
estimated error U for each. Four of them match QoIs here:

| QoI | 160 x 160, this study | Marchi et al. | E = S - D | \|E\| / U_val |
|---|---|---|---|---|
| u at y = 0.5 | -0.20889 +/- 0.00033 | -0.2091491418 +/- 8.6e-9 | 0.00026 | 0.78 |
| u_min | -0.21376 +/- 0.00037 | -0.2140417 +/- 1.6e-6 | 0.00028 | 0.77 |
| v_max | 0.17936 +/- 0.00026 | 0.179572814 +/- 2.7e-8 | -0.00021 | 0.81 |
| v_min | -0.25359 +/- 0.00027 | -0.253804 +/- 1.1e-5 | 0.00022 | 0.80 |

All four are within the uncertainty: |E| is 0.77 to 0.81 of U_val. Their estimated errors are 25
to 38,000 times smaller than U_num, so U_val is U_num to within 0.1%, and the comparison works
almost like the duct's check against its exact value: the GCI bands hold against a far more
accurate solution, with |E| at about 80% of U in both studies.

Taking their U as the 95% uncertainty U_D is our assumption. U is the difference between the
most extrapolated values on their two finest grids (their Eq. 13). On a problem with a known
solution it exceeded the true error for every variable, and they expect it to overestimate, but
they state no coverage for it. No reading of U changes these outcomes: U_val cannot fall below
U_num, and |E| is at most 0.81 U_num.

Their extrema are the extreme face values on each of their grids, extrapolated; the ones here are
fitted between probes. Both estimate the extremum of the continuous profile. Their profile points
are at sixteenths of L, so of the three Ghia points only y = 0.5 has a value from them.

### Ghia et al. (1982): outside the uncertainty

The three points are grid points of Ghia, Ghia and Shin (1982), J. Comput. Phys. 48, 387-411,
whose Table I (p. 398) gives u there for Re = 100:

| QoI | 160 x 160, this study | Ghia et al., 129 x 129 | E = S - D | E / \|D\| | \|E\| / U_num | U_D needed |
|---|---|---|---|---|---|---|
| u at y = 0.5 | -0.20889 +/- 0.00033 | -0.20581 | -0.00308 | -1.5% | 9.4 | 0.0031 |
| u at y = 0.4531 | -0.21368 +/- 0.00038 | -0.21090 | -0.00278 | -1.3% | 7.3 | 0.0028 |
| u at y = 0.8516 | 0.23639 +/- 0.00013 | 0.23151 | 0.00488 | 2.1% | 38.9 | 0.0049 |

All three differ from Ghia's values by 1.3 to 2.1%, 7 to 39 times the numerical uncertainty, so
each comparison is `outside_uncertainty`. Ghia et al. state no uncertainty for their values, so on
its own this comparison cannot say which solution is off: each E is judged against U_num alone,
with a warning, and the last column is the smallest 95% uncertainty that Ghia's values would need
for the two to agree, 1.3 to 2.1% of the value.

At y = 0.5, the one point both papers give, Marchi et al.'s value puts the difference on Ghia's
side: Ghia's value is 0.0033 (1.6%) from it, 13 times as far as this study's. At the other two
points, two observations point the same way:

- This study's own error estimate is much smaller. The Richardson-extrapolated values differ
  from the fine-grid ones by 0.03 to 0.14%, and from Ghia's by 1.4 to 2.1%.
- Ghia's values lie among this study's coarser levels: between 80 x 80 and 40 x 40 at y = 0.5
  and 0.4531, and between 40 x 40 and 20 x 20 at y = 0.8516.

Ghia et al. used second-order central differences, with first-order upwind differences for
convection and their second-order term added as a deferred correction (p. 393), on a uniform
129 x 129 grid. Their tables give values at their grid points only, so the extrema here have no
Ghia reference. Ghia's point n is at y = (n - 1)/128 of L, so the three points are y = 64/128,
58/128 and 109/128. `tests/test_studies.py` checks the numbers in this section and that each Ghia
value sits at its probe.

## Case

- Square cavity, side 0.1 m, one cell thick (`empty` front and back, so `dim = 2`), uniform
  N x N cells. Lid speed 1 m/s, nu = 0.001, so **Re = 100**. The `icoFoam` cavity tutorial uses
  nu = 0.01, which is Re = 10; Ghia's Re = 100 case needs nu = 0.001.
- The tutorial's schemes (Euler in time, `Gauss linear` in space, orthogonal Laplacian) and
  PISO with two correctors; p to 1e-10, U to 1e-12.
- The time step keeps the Courant number at 0.5 on every level, so it shrinks with the mesh.
  Every run goes to t = 10 s (100 L/U).
- QoIs are sampled with `probes` and `interpolationScheme cellPoint`, so every level is read at the
  same physical points rather than at its own cell centres, written to 12 digits:
  - u at three of Ghia's centreline points, y = 64/128, 58/128 and 109/128 of L, every 0.05 s
    (`postProcessing/ghiaPoints`);
  - the full profiles u(y) on the vertical centreline and v(x) on the horizontal one, 255 points
    at spacing L/256, every 0.05 s over the last 2.5 s, t = 7.5 to 10 s, 51 rows
    (`postProcessing/*Centreline`). foam-verify takes the extremum of each row by fitting a
    parabola through the lowest (or highest) probe and its two neighbours. The last row gives
    the value; every row gives the history for the iterative check.

## Steady state

The runs are transient, so the steady state is checked on the quantities themselves. On the
160 x 160 grid the three sampled QoIs are within 1e-6 of their final values from t = 2.6 s,
1e-8 from t = 3.45 s and 1e-10 from t = 5.0 s. Over the second half of the run they change by
less than 1e-10 (relative). The coarser grids settle at the same times or earlier.

foam-verify's iterative check ([docs/iterative.md](../../docs/iterative.md)) reads every QoI
over the same window, the last 50 samples, t = 7.55 to 10 s: the Ghia points from their 200
samples, the profile extrema from their 51 rows. Every QoI is converged on every level, and the
iterative uncertainty is at most 1.9e-9 of the GCI uncertainty, so iterative error does not
contaminate the grid study.

## Reproduce

From the repository root, with the pinned image in `studies/README.md`:

```console
$ python3 studies/cavity/generate.py setup
$ podman run --rm -v "$PWD":/work:z -w /work --entrypoint /bin/bash $IMG studies/cavity/run.sh
$ python3 studies/cavity/generate.py collect
```

The four levels run in parallel; 160 x 160 takes about 14 minutes, 80 x 80 about a minute, the coarser two seconds. `build/`
(the full cases, about 61 MB) is not committed. Each `nN/` keeps the inputs, the mesh `boundary`
file, the `owner` header, the function-object output and trimmed logs: 4.4 MB in all, almost all
of it the profile rows.
