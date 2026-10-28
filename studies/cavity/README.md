# Lid-driven cavity, Re = 100: the recognised benchmark

The `icoFoam` cavity at Re = 100 on four uniform grids, 20 x 20 to 160 x 160. There is no exact
solution; this study shows the GCI behaving on a standard benchmark with corner singularities.
The comparison with Ghia, Ghia and Shin (1982) is a separate step (`validate`, week 3), and is
labelled code-to-code: Ghia's values are themselves a 129 x 129 numerical solution.

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

| QoI | p | Fine-grid result | GCI_fine | Extrapolated | Asymptotic ratio |
|---|---|---|---|---|---|
| u at y = 0.5 | 1.967 | -0.20889 +/- 0.00033 | 0.157% | -0.209154 | 1.0037 |
| u at y = 0.4531 | 1.942 | -0.21368 +/- 0.00038 | 0.177% | -0.213986 | 1.0040 |
| u at y = 0.8516 | 2.294 | 0.23639 +/- 0.00010 | 0.041% | 0.236470 | 1.0013 |
| u_min | 1.977 | -0.21376 +/- 0.00037 | 0.171% | -0.214053 | 1.0040 |
| v_max | 2.152 | 0.17936 +/- 0.00022 | 0.125% | 0.179544 | 1.0034 |
| v_min | 2.523 | -0.25359 +/- 0.00017 | 0.068% | -0.253724 | 1.0026 |

- The fine-grid minimum of u lies at y = 0.4580, the maximum of v at x = 0.2374 and the minimum
  of v at x = 0.8113.
- On the coarser triplet (80, 40, 20) every QoI is also monotonic, with p between 1.69 and 1.87.
  The observed order moves to about 2 (1.94 to 2.52) on the finest triplet. A lower order on
  coarse grids is consistent with the two lid corners, where the velocity is discontinuous.
- `tests/test_studies.py` reads this folder back and checks the verdicts, the orders and the
  asymptotic ratios.
- foam-verify's full report on this study is [report.md](report.md) (JSON:
  [report.json](report.json)).

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
iterative uncertainty is at most 2.1e-9 of the GCI uncertainty, so iterative error does not
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
