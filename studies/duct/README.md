# Square duct: the proof case

Fully developed laminar flow in a square duct at Re = 100. The exact Darcy friction factor is
known from the series solution (Shah and London 1978), so this study asks the question every
GCI should answer: **does the fine-grid uncertainty band contain the exact value?**

It does.

| Grid | Cells | f Re | Error (exact - f Re) |
|---|---|---|---|
| 160 x 160 | 25,600 | 56.89972 | 0.00858 |
| 80 x 80 | 6,400 | 56.87400 | 0.03430 |
| 40 x 40 | 1,600 | 56.77150 | 0.13681 |
| 20 x 20 | 400 | 56.36707 | 0.54124 |

Exact: **56.90831** (`foam_verify.exact.rectangular_duct_fre(1.0)`).

foam-verify on the three finest grids: monotonic convergence (R = 0.251), observed order
p = 1.995 against a formal order of 2, asymptotic-range ratio 1.000, clean pass.

- Fine-grid result: **56.8997 +/- 0.0108** (GCI_fine = 0.019%), band 56.8890 to 56.9105.
- The actual error, 0.0086, is 80% of the stated uncertainty: the band holds, with modest margin.
- Richardson extrapolation: 56.90834, within 3.3e-5 of the exact value.
- The next triplet (80, 40, 20) also brackets the exact value: p = 1.980, error 79% of its band.

`tests/test_studies.py` reads this folder back and checks both the bracket and the force
balance below.

## Case

- Cross-section: the unit square in y-z (D_h = 1), uniform N x N cells. Along the flow (x): one
  cell of length 0.05 between a cyclic pair, the same on every level. So `dim = 2`. There are
  no `empty` patches, but the two cyclic halves have one face per cell on every level, which
  confirms that the mesh is one cell across the flow direction: foam-verify reports a note,
  not a warning.
- `simpleFoam`, laminar, nu = 0.01, SIMPLEC, `Gauss linear` everywhere. A `meanVelocityForce`
  source holds the bulk velocity at Ubar = 1 (Re = 100).
- QoI: f Re = 8 tau_w D_h / (nu Ubar) = 800 tau_w, from the area-averaged wall shear stress
  (`postProcessing/wallStress`). Cross-check: the force balance gives f Re = 200 G from the
  pressure-gradient source G (`nN/final/momentumSourceProperties`); the two agree to 1e-9 on
  every level.
- 8000 iterations on every level, function objects written every 10th. Over the last 2000
  iterations the QoI varies by at most 6e-12 (relative, on 160 x 160; exactly zero on the coarser
  levels). A 20,000-iteration run gave the same values to ten digits.

## Residuals are not the QoI

`residualControl` (1e-10) never stops these runs. The Ux initial residual falls to between 3e-16
and 6e-15, but Uy, Uz and p are zero up to round-off (about 1e-16), and their normalised residuals
divide noise by noise: after the first 100 iterations they stay between 0.016 and 0.55 on every
level (`postProcessing/residuals`, every 10th iteration). By residuals the case never
converges; by the quantity reported it converged thousands of iterations before the end.

foam-verify's iterative check ([docs/iterative.md](../../docs/iterative.md)) reads f Re over the
last 80 samples, iterations 7210 to 8000: converged on every level, with a relative range of at
most 1.4e-12. The iterative uncertainty is 3.7e-9 of the GCI uncertainty, so iterative error does
not contaminate the grid study.

## Reproduce

From the repository root, with the pinned image in `studies/README.md`:

```console
$ python3 studies/duct/generate.py setup
$ podman run --rm -v "$PWD":/work:z -w /work --entrypoint /bin/bash $IMG studies/duct/run.sh
$ python3 studies/duct/generate.py collect
```

`build/` (the full cases, about 37 MB) is not committed. Each `nN/` keeps the inputs, the mesh
`boundary` file, the `owner` header (cut after the header; only `nCells` is read), the
function-object output, trimmed logs and the final pressure gradient.
