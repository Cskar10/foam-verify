# Grid convergence: method and conventions

`foam_verify.gci` follows Celik et al. (2008). This page records the formulas as implemented,
where each comes from, and the places where foam-verify makes its own choice. Grid 1 is the
finest throughout.

## Sources

- Celik, I. B., Ghia, U., Roache, P. J. and Freitas, C. J. (2008). Procedure for Estimation and
  Reporting of Uncertainty Due to Discretization in CFD Applications. *J. Fluids Eng.* 130(7)
  078001. Copy used: the ASME JFE editorial-policy PDF
  (`jfenumaccuracy.pdf`, sha256 `3e22d96c…2397`), pages 3-7.
- Eça, L. and Hoekstra, M. (2014). A procedure for the estimation of the numerical uncertainty
  of CFD calculations based on grid refinement studies. *J. Comput. Phys.* 262, 104-130. Copy
  used: MARIN's author PDF (sha256 `089dd9bb…7b92`), sections 2-3 and Appendix A.
- Roache, P. J. (1994). Perspective: A Method for Uniform Reporting of Grid Refinement Studies.
  *J. Fluids Eng.* 116, 405-413. Source of Fs = 3 for two grids. Not yet re-read for this code;
  the value is the one Celik et al. and Eça and Hoekstra both use for unreliable estimates, and
  ASME V&V 20 (below) gives the same history: Fs = 3 for two-grid studies, Fs = 1.25 "only when
  using at least three grid solutions and the observed p".
- ASME V&V 20-2009 (reaffirmed 2021). *Standard for Verification and Validation in Computational
  Fluid Dynamics and Heat Transfer.* American Society of Mechanical Engineers. Para. 2-4.1
  (pp. 12-14): the five-step GCI procedure and the choice of Fs; Appendix C-4 (pp. 82-83): the
  least-squares GCI and the limit on p. Not redistributed here.

## Refinement scope (asked first)

Richardson extrapolation assumes one cell size h for the whole mesh, refined by the same ratio
everywhere (Celik et al. 2008, step 2; Eça and Hoekstra 2014, section 2: geometrically similar
grids). Practical studies often refine only part of the mesh, so the CLI requires `--refined`:

- `mesh`: every cell, near-wall layers included. The only scope the papers' procedure covers in
  full.
- `core`: the core volume only, with identical near-wall layers on every level. The uncertainty
  then covers the core discretisation only; the layers' own error is fixed across levels, so
  Richardson extrapolation cannot see it and it needs a separate boundary-layer study. With total
  cell counts, give `--layer-cells` (the fixed layer cell count): otherwise r is computed from
  cells that were not refined, understates the core ratio, and a warning blocks the clean pass. The warning is attached only to
  results with an uncertainty estimate; a divergent or degenerate verdict does not depend on r's size.
- `boundary-layer`: wall-normal layer refinement only, with the core fixed. Cell counts do not
  measure this, so `--h` (first-layer heights) is required; the growth ratio and the
  layer-to-core transition ratio should be the same on every level, and $d$ is irrelevant.

The scope is reported with every result. This is foam-verify's convention for making the
assumption explicit; neither paper defines partial-scope studies.

## Grid sequence (asked first)

The safety factor Fs = 1.25 rests on empirical studies of grids refined systematically. ASME V&V
20 (para. 2-4.1) recommends it "with three-grid studies involving structured grid refinement";
the base grid may itself be unstructured, as long as the sequence refines it systematically. For
unstructured refinement, where r is well defined only for geometrically similar grids and the
observed p scatters, it recommends the more conservative Fs = 3 until the data show otherwise.
So the CLI requires `--grid-sequence` and `study.toml` requires `grid_sequence`:

- `structured`: every level refines one base grid systematically, with geometrically similar
  cells, such as a block mesh whose cell counts are all scaled by the same factor. Fs = 1.25 with
  three or more grids.
- `unstructured`: anything else, for example each level meshed afresh by a mesh generator at its
  own cell size. Fs = 3 (`fs_fallback`), with three grids or more.

foam-verify cannot tell the two apart from the files, so the sequence is stated, never checked,
and the report marks it "assumed". It changes Fs only: the verdicts and the other checks are the
same for both. In the Python API, `grid_convergence` defaults to `structured`, Celik et al.'s
setting.

## Formulas (Celik et al. 2008)

| Quantity | Implementation | Source |
|---|---|---|
| Refinement ratio | $r_{21} = h_2/h_1 = (N_1/N_2)^{1/d}$ | Eqs. 1-2, same domain on every level |
| Ratio check | warn if $r < 1.3$ | step 2 |
| Observed order | $p = \lvert \ln\lvert\varepsilon_{32}/\varepsilon_{21}\rvert + q(p)\rvert / \ln r_{21}$, $q(p) = \ln\frac{r_{21}^p - s}{r_{32}^p - s}$, $s = \operatorname{sign}(\varepsilon_{32}/\varepsilon_{21})$ | Eq. 3 |
| Extrapolated value | $\phi_\text{ext}^{21} = (r_{21}^p\phi_1 - \phi_2)/(r_{21}^p - 1)$ | Eq. 4 |
| Errors | $e_a^{21} = \lvert(\phi_1-\phi_2)/\phi_1\rvert$, $e_\text{ext}^{21} = \lvert(\phi_\text{ext}^{21}-\phi_1)/\phi_\text{ext}^{21}\rvert$ | Eqs. 5-6 |
| Fine-grid GCI | $\text{GCI}^{21} = F_s e_a^{21}/(r_{21}^p - 1)$, $F_s = 1.25$ | Eq. 7 |
| Coarse GCI | $\text{GCI}^{32} = F_s e_a^{32}/(r_{32}^p - 1)$, $e_a^{32} = \lvert(\phi_2-\phi_3)/\phi_2\rvert$ | Eq. 7 applied to grids 2-3 |
| Asymptotic check | $\text{GCI}^{32}/(r_{21}^p\,\text{GCI}^{21})$, warn outside 0.9-1.1 | standard GCI practice |

The absolute uncertainty reported is $U = F_s\lvert\phi_1-\phi_2\rvert/(r_{21}^p-1)$, which equals
$\text{GCI}^{21}\lvert\phi_1\rvert$ but stays defined when $\phi_1 = 0$. When p is above the formal
order, U uses the formal order instead (see Observed order above the formal order).

## Convergence type

The convergence ratio is $R = \varepsilon_{21}/\varepsilon_{32} = (\phi_2-\phi_1)/(\phi_3-\phi_2)$
(Eça and Hoekstra 2014, Eq. 2).

| Condition | Verdict | Uncertainty |
|---|---|---|
| a difference is zero to round-off ($\le 10^{-10}\max\lvert\phi\rvert$) | `degenerate` | none |
| $0 < R < \ln r_{21}/\ln r_{32}$ | `monotonic_convergence` | GCI |
| $R \ge \ln r_{21}/\ln r_{32}$ | `divergence` (monotonic) | none |
| $-1 < R < 0$ | `oscillatory_convergence` | spread bound |
| $R \le -1$ | `divergence` (oscillatory) | none |

### The monotonic threshold for unequal ratios

Eça and Hoekstra's classification (0 < R < 1 for monotonic convergence) is stated for equal
refinement ratios. With unequal ratios it misclassifies exact data: for
$\phi = 1 + 0.5h^2$ on $h = 1, 2, 2.6$ ($r_{21} = 2$, $r_{32} = 1.3$), $R = 1.45$.

For $\phi = \phi_0 + c h^p$, Eça and Hoekstra's Eq. 3 gives
$R(p) = (r_{21}^p - 1)/\left(r_{21}^p(r_{32}^p - 1)\right)$. Writing
$f(p) = -\ln R = p\ln r_{21} + \ln(r_{32}^p - 1) - \ln(r_{21}^p - 1)$ and
$g(a) = a/(1 - e^{-a})$, which increases with slope between 0 and 1,

$$f'(p) = \ln r_{21} + \frac{g(p\ln r_{32}) - g(p\ln r_{21})}{p} \ge \min(\ln r_{21}, \ln r_{32}) > 0.$$

So $R$ falls strictly as $p$ grows, and $p > 0$ (convergence) exactly when
$R < \lim_{p\to 0} R(p) = \ln r_{21}/\ln r_{32}$. For equal ratios this is $R < 1$. For
alternating data, $\lvert\varepsilon_{32}/\varepsilon_{21}\rvert = r_{21}^p(r_{32}^p+1)/(r_{21}^p+1)$
is also strictly increasing in $p$ and equals 1 at $p = 0$, so $\lvert R\rvert < 1$ holds for any
ratios. This threshold is foam-verify's derivation, tested in `tests/test_gci_property.py`; it is
not stated in either paper.

## Solving for the observed order

- Equal ratios: $q = 0$ and $p$ is closed-form (`p_solver = "closed_form"`).
- Otherwise Celik's fixed-point iteration runs first, from the first term (`"fixed_point"`). It
  converges for all three Table 1 columns, but **it diverges for many legitimate studies with
  unequal ratios** (for example $r_{21} = 1.3$, $r_{32} = 2$): the fixed-point map's slope
  exceeds 1. Its outer absolute value also admits a spurious fixed point. Its answer is
  therefore checked against Eq. 3 without the absolute value.
- If the check fails or the iteration diverges, bisection on that signed equation takes over
  (`"bisection"`). By the monotonicity above its root is unique, and for a convergent triplet it
  is bracketed on $(0, \infty)$.
- The iteration count is reported either way. If both fail the verdict is `order_unresolved`.

## Safety factor and the order check

$F_s = 1.25$ for three or more grids of a structured grid sequence, and $F_s = 3$ for an
unstructured one (see Grid sequence). If the observed order is outside
$[0.5, 2p_\text{formal}]$, $F_s = 3$ and a warning blocks the clean pass. The lower limit matches
Eça and Hoekstra's acceptable range; their upper limit for a second-order method is about 2.1
(Appendix A), tighter than the default here. Both limits are options.

## Observed order above the formal order (foam-verify's convention)

An observed order above the formal one makes $r^p - 1$ larger and the GCI smaller: the estimate
then leans on an error cancellation that the scheme's formal order does not promise. ASME V&V 20
(Appendix C-4) recommends limiting the maximum p used in the GCI to the theoretical p. It states
this with the least-squares GCI for noisy p, and Celik et al. (2008) do not cap p. foam-verify
applies the limit to every triplet as its own conservative convention: U uses
$\min(p, p_\text{formal})$ (option `cap_order`, on by default), and `order_used` in the result
records the order behind U.

Only U and its band use the capped order. The Richardson numbers (p, $\phi_\text{ext}$,
$e_\text{ext}$, $\text{GCI}^{21}$, $\text{GCI}^{32}$) and every check keep the observed p. The
asymptotic-range ratio asks whether the data follow the observed p; computed with a capped p it
becomes about $r_{21}^{\,p - p_\text{formal}}$ instead of 1. On the cavity study that would fail three
QoIs whose ratios are 1.001 to 1.003, with 1.12, 1.23 and 1.44 for p = 2.15, 2.29 and 2.52. With
the cap in U only their verdicts stand and their bands widen by 15 to 58%.

## Two grids

The observed order cannot be estimated. The GCI uses the formal order with $F_s = 3$
(`two_grid`, method `assumed_order_gci`) and is never a clean pass.

## Oscillatory triplets: the spread bound (foam-verify's convention)

Celik et al. still compute a GCI for oscillatory data (Table 1, column 3); Eça and Hoekstra
class oscillatory convergence as anomalous and use $F_s = 3$ with a least-squares fit, which
needs at least four grids. For a triplet foam-verify reports

$$U = 3\,\Delta_\phi, \qquad \Delta_\phi = \frac{\phi_\max - \phi_\min}{n_g - 1},$$

where $\Delta_\phi$ is Eça and Hoekstra's data-range parameter (Eq. 19) and 3 is their
unreliable-estimate safety factor. The combination is ours, not theirs. Rationale: for ideal
alternating convergence with ratio $R \in (-1, 0)$, the fine-grid error is
$\lvert\varepsilon_{21}\rvert\,\lvert R\rvert/(1 - R) < \tfrac12\lvert\varepsilon_{21}\rvert$, so
$U = 1.5(\phi_\max - \phi_\min)$ is at least three times the worst case. Celik's Richardson
numbers are still returned, marked `richardson_used = false`.

## Four or more grids

One result per consecutive triplet. The top-level verdict and uncertainty are from grids 1-3.

If a coarser triplet does not converge monotonically, the grids are not all in the asymptotic
range, and the uncertainty from grids 1-3 rests on that range. When grids 1-3 give an
uncertainty, a warning then blocks the clean pass; when they give none (divergent, degenerate),
the coarser verdict is a note. A level that is simply too coarse can be left out of the study,
where the choice is visible, rather than accepted silently. This is foam-verify's convention:
Celik et al. describe three grids. The `pitzDaily` study shows why it matters: its finest
triplet converges monotonically at p = 0.85 while the coarser one diverges, because refining
moves the walls through the wall-function switch. The least-squares fit of Eça and Hoekstra is
a planned extension.

## Celik et al. Table 1 reproduction

All 21 printed values (3 columns × r21, r32, p, φ_ext, e_a, e_ext, GCI) are checked to their
printed precision in `tests/test_gci_celik.py`. 20 reproduce. The exception is column 2's
$e_\text{ext}^{21}$, printed as 0.9%: Eq. 6 gives
$\lvert 10.8801 - 10.7880\rvert/10.8801 = 0.85\%$. Dividing by $\phi_1$ instead gives 0.854%,
which rounds to the printed 0.9%, so the entry looks computed with the wrong denominator.
foam-verify follows Eq. 6.
