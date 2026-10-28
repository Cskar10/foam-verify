# pitzDaily: the case where things go wrong

The OpenFOAM v2512 `pitzDaily` tutorial, `simpleFoam` with standard k-epsilon and wall functions,
on four meshes that are each about 1.5 times finer per direction than the last. The case is the
backward-facing step of Pitz and Daily (1983): step height H = 25.4 mm, inlet velocity 10 m/s,
nu = 1e-5, so Re_H = 25,400. This study checks the numerical error of the tutorial's model as the
mesh is refined; it does not compare with the experiment.

Pressures are kinematic (m^2/s^2); the reattachment length is in step heights.

| QoI | 139k cells | 62k | 28k | 12k (tutorial mesh) |
|---|---|---|---|---|
| total-pressure loss, inlet - outlet | 16.4779 | 16.0532 | 15.4511 | 14.8956 |
| static pressure difference, inlet - outlet | -3.6075 | -4.0783 | -4.7388 | -5.3782 |
| reattachment length x_R/H | 6.8379 | 6.9091 | 6.9803 | 7.0237 |

None of the three settles as the mesh is refined. From the coarsest level to the finest, the loss
changes by +3.7%, +3.9% and +2.6% per level, the reattachment length by -0.6%, -1.0% and -1.0%.
In the asymptotic range of a second-order scheme each change would be 1.5^2 = 2.25 times smaller
than the one before; here the changes grow, or shrink by a factor of 1.4 at most.

foam-verify on the four levels:

| QoI | Finest triplet (139k, 62k, 28k) | Coarser triplet | Clean pass |
|---|---|---|---|
| total-pressure loss | monotonic, p = 0.85: 16.48 +/- 1.31 (GCI 8.0%) | divergence | no |
| static pressure difference | monotonic, p = 0.82; asymptotic-range ratio 0.885, outside [0.9, 1.1] | divergence | no |
| reattachment length | divergence: R = 0.998 against the threshold 0.992 | divergence (R = 1.65) | no |

The settings consistency check passes (the levels differ only in `blockMeshDict`), and the
iterative check finds every QoI converged or oscillating far below the grid differences (below).

## Why: refining moves the walls onto a different wall function

The wall function for nut switches rather than blends. In v2512, `nutkWallFunction` defaults
to `blending stepwise`: a wall face whose y+ is above 11.53 gets the log-law turbulent viscosity,
and a face at or below it gets none, so its shear stress is the laminar one across the first
cell. The 11.53 is where the viscous and log laws
meet for kappa = 0.41 and E = 9.8, computed by `wallFunctionCoefficients.C`; the switch is in
`nutkWallFunctionFvPatchScalarField.C`.

| Level | Cells | r to the next coarser | Lower wall: mean y+ (max) | at or below 11.53 | Upper wall: mean y+ | at or below 11.53 |
|---|---|---|---|---|---|---|
| 139k | 139,025 | 1.494 | 3.2 (7.0) | 100% | 3.4 | 100% |
| 62k | 62,257 | 1.499 | 4.3 (8.5) | 100% | 4.8 | 100% |
| 28k | 27,703 | 1.505 | 9.1 (16.2) | 52% | 7.0 | 99% |
| 12k | 12,225 | | 15.0 (26.1) | 35% | 9.4 | 74% |

y+ is from `postProcessing/yPlus` at the last iteration (the wall function's own, k-based y+); the
shares are of the wall faces in the final `yPlus` field. Already on the tutorial mesh a third of
the lower wall and three quarters of the upper wall are below the switch; from 62k on, all of
both. So the levels do not solve one set of equations ever more finely: the wall model itself
changes between 12k and 62k, and the grid study's premise does not hold.

The total-pressure loss shows what a three-grid study would miss. Its finest triplet is
monotonic with p = 0.85, far from the formal order of 2 but inside the range [0.5, 4] that
foam-verify accepts, with an asymptotic-range ratio of 1.026: on its own it would pass, at
+/- 8%. It straddles the change of wall model, though, and the coarser triplet diverges. With
four or more grids a coarser triplet that does not converge blocks the clean pass
([docs/gci.md](../../docs/gci.md), Four or more grids), so foam-verify refuses one here.

## Iterative convergence

The tutorial's `residualControl` stops its run after about 285 iterations. It is removed here, and
every level runs 8000. The SIMPLE iterations never settle to round-off: the pressures keep
oscillating irregularly, by about 1e-4 of their value on 12k and by up to a few 1e-3 on the finer
levels. On 139k the loss also has bursts of up to 0.8% between iterations 3000 and 7000, which
die away again. The pressure QoIs are therefore window means over the last 10% of
the run (80 samples, 800 iterations), and the reattachment length is sampled 11 times over the last
2000 iterations.

- Over those windows every QoI is `converged` on every level, except the static pressure
  difference on 28k, which is `oscillating` (relative range 1.8e-3, no full cycle in the window).
- The iterative uncertainties are at most 0.3% of the GCI uncertainty where there is one, so
  iterative error does not explain the trends. On 139k the 1000-iteration means of the loss are
  16.475 to 16.479 from iteration 4000 on.

## Case

- The tutorial's geometry, gradings (including the multi-section gradings across the channel),
  schemes (`linearUpwind` for U, `limitedLinear 1` for k and epsilon), solvers, relaxation (0.9)
  and boundary conditions. Only k, epsilon, nut, U and p are written: the tutorial's omega and
  nuTilda files are not used by k-epsilon.
- Levels: every block's cell count is the tutorial's times 1.5^k, k = 0 to 3, rounded half up
  (18, 180, 25 cells along x and 27, 30 across become 61, 608, 84 and 91, 101 on 139k). Blocks
  that share an edge keep sharing a count, so the meshes stay conformal. The rounding moves a
  block's own ratio from 1.5 by at most 1.8%; the representative ratios from the cell counts are
  in the table above. Maximum non-orthogonality is 5.95 to 5.97 degrees and maximum skewness 0.26
  on every level (`log.checkMesh`).
- QoIs, written by function objects in `system/controlDict`:
  - the pressure differences by `multiFieldValue` (`subtract`) over two `surfaceFieldValue` area
    averages, as in v2512's `pressureDifferencePatch` template, every 10 iterations
    (`postProcessing/pressureDrop`, Group0 = p, Group1 = total pressure). The total pressure is
    the `pressure` function object with `mode total` and `rhoInf 1`, kinematic like p;
  - the lower-wall shear stress, sampled by `surfaces` with `surfaceFormat raw` on the `lowerWall`
    patch, face values, every 200 iterations over the last 2000 (`postProcessing/lowerWallShear`).
    The reattachment point is its last change of sign along x (`profile = "last_crossing"`),
    interpolated between face centres. The patch also holds the vertical step face at x = 0,
    where the shear stress is small and changes sign; the last crossing is downstream of it.

## Reproduce

From the repository root, with the pinned image in `studies/README.md`:

```console
$ python3 studies/pitzDaily/generate.py setup
$ podman run --rm -v "$PWD":/work:z -w /work --entrypoint /bin/bash $IMG studies/pitzDaily/run.sh
$ python3 studies/pitzDaily/generate.py collect
```

The four levels run in parallel; 139k takes about 18 minutes, 12k about 2. `build/` (the full
cases) is not committed. Each `nNk/` keeps the inputs, the mesh `boundary` file, the `owner`
header, the function-object output and trimmed logs: 3.1 MB in all.

Pitz, R. W. and Daily, J. W. (1983). Combustion in a turbulent mixing layer formed at a
rearward-facing step. *AIAA Journal* 21(11), 1565-1570.
