# Reference comparison: method and conventions

`foam_verify.compare` compares a simulation value with a reference value and says what the
difference can and cannot show. This page records the rules as implemented, where each comes
from, and the places where foam-verify makes its own choice.

```console
$ uv run foam-verify compare --simulation 56.8997 --uncertainty 0.0108 --reference 56.9083 --kind exact
$ uv run foam-verify compare --simulation 12.0 --uncertainty 0.6 --reference 7.0 --kind experiment \
    --reference-uncertainty 0.8 --json
```

The exit code is 0 when the comparison error is within the uncertainty that applies, 1
otherwise, and 2 for bad input.

## Sources

- ASME V&V 20-2009 (reaffirmed 2021), the edition listed in [gci.md](gci.md). Para. 1-1:
  validation needs experimental data. Para. 1-5: the comparison error and its error sources.
  Para. 1-6: code verification evaluates error against a known benchmark solution, solution
  verification estimates it. Para. 2-4.1: the GCI is a 95% uncertainty; eqs. 2-4-13 and 2-4-14
  convert it to a standard uncertainty. Section 6: interpreting E and the validation uncertainty.
- Eça, L., Dowding, K. and Roache, P. J. (2020). On the interpretation and scope of the V&V 20
  standard for verification and validation in computational fluid dynamics and heat transfer.
  Proceedings of the ASME V&V Symposium, VVS2020-13077; Sandia report SAND2020-3788C, public at
  <https://www.osti.gov/biblio/1774746>. Eq. 15 (combining 95% uncertainties) and the
  algorithmic version of the outcome, pages 5-6. The three authors served on the V&V 20
  committee.

## The comparison error

$E = S - D$, the simulation value minus the reference value (V&V 20, eq. 1-5-1), and $E/\lvert
D\rvert$ when $D \neq 0$. $S$ is the finest-grid value of a grid study and $U_\text{num}$ its
uncertainty, the study's U.

## Three kinds of reference

What $E$ means depends on what the reference is, so every comparison states its kind:

| Kind | What it is | What E is | Judged against |
|---|---|---|---|
| `exact` | an exact or analytical solution of the same equations | the numerical error itself | $U_\text{num}$ |
| `code` | another numerical solution of the same equations | the difference of two numerical errors | $U_\text{val}$, or $U_\text{num}$ when the reference states no uncertainty |
| `experiment` | measured data | numerical, input and experimental errors and the model error | $U_\text{val}$, with the outcome below |

Only an experiment validates a model in V&V 20's sense (para. 1-1). An exact reference makes the
comparison a code-verification check (para. 1-6): it tests whether the stated numerical
uncertainty bounds the actual error. A code reference says nothing about the model, since both
solutions solve the same equations.

## Uncertainties at 95%

Every uncertainty in a comparison is a 95% expanded uncertainty. $U_\text{num}$ is the grid
study's U as it is: V&V 20 (para. 2-4.1) treats the GCI as a 95% uncertainty, set empirically,
with no error distribution assumed, and keeping every component at 95% needs no further
assumption. Independent components combine as

$$U_\text{val} = \sqrt{U_\text{num}^2 + U_\text{input}^2 + U_D^2}$$

(Eça, Dowding and Roache 2020, Eq. 15). Correlated errors (V&V 20, section 5, cases 2 to 4) are
not handled.

Reporting at 95% only is foam-verify's convention. A standard uncertainty needs an assumed
error distribution, and the divisor it brings changes $u_\text{num}$ by a factor of 1.74 between
the standard's two choices, so it is given only where it is needed: with experimental data,
whose uncertainty is usually stated as a standard uncertainty (below).

## Exact references

The reference has no uncertainty ($U_D = 0$) and solves the same equations with the same inputs,
so the model and input errors are zero and $E$ is the numerical error. The outcome is
`within_uncertainty` when $\lvert E\rvert \le U_\text{num}$, the numerical uncertainty bounds the
actual error, and `outside_uncertainty` otherwise: the uncertainty was not conservative here. The
square duct gives $E = -0.00858$ with $U_\text{num} = 0.0108$: $\lvert E\rvert = 0.797\,U_\text{num}$.

## Code references

With the reference's 95% uncertainty $U_D$ given, $U_\text{val} = \sqrt{U_\text{num}^2 + U_D^2}$, and
the two solutions agree when $\lvert E\rvert \le U_\text{val}$. Many published numerical solutions,
Ghia et al.'s cavity values among them, state no uncertainty. $E$ is then judged against
$U_\text{num}$ alone, with a warning that $U_\text{val}$ is incomplete, and when $\lvert E\rvert >
U_\text{num}$ the result gives the smallest $U_D$ that would reconcile the two,
$\sqrt{E^2 - U_\text{num}^2}$. Both rules are foam-verify's.

## Experiments

The experiment's 95% uncertainty $U_D$ is required: V&V 20 cannot be applied without it. The
input uncertainty $U_\text{input}$ defaults to zero, which treats the simulation inputs as exact,
so any error from them counts as model error (V&V 20, para. 1-5); the result says so.

The outcome follows Eça, Dowding and Roache's algorithmic version of V&V 20's interpretation,
with a constant $C$:

| Case | Condition | Model error | Outcome |
|---|---|---|---|
| 1 | $\lvert E\rvert > C\,U_\text{val}$ | $\delta_\text{model} = E$ | `model_error` |
| 3a | $U_\text{val} \le \lvert E\rvert \le C\,U_\text{val}$ | $\lvert\delta_\text{model}\rvert < \lvert E\rvert + U_\text{val}$, sign of $E$ | `outside_uncertainty` |
| 3b | $U_\text{val}/C \le \lvert E\rvert < U_\text{val}$ | $\lvert\delta_\text{model}\rvert < \lvert E\rvert + U_\text{val}$, sign unknown | `within_uncertainty` |
| 2 | $\lvert E\rvert < U_\text{val}/C$ | $\lvert\delta_\text{model}\rvert < U_\text{val}$, sign unknown | `within_uncertainty` |

$C$ is "typically equal to 10 (one order of magnitude)", the default here; for problems without
high-risk decisions they cite 7 from Roache (`--c 7`). At $\lvert E\rvert = U_\text{val}$ their Figure
1 gives case 3a; at $\lvert E\rvert = U_\text{val}/C$, case 3b. They stress that validation is not a
pass/fail exercise: the outcome estimates the model error, and whether it is acceptable is a
separate engineering decision.

With experimental data the standard uncertainty is given as well, with its divisor:

| U_num from | Divisor | Basis |
|---|---|---|
| a GCI (monotonic convergence) | 1.15 | V&V 20, eq. 2-4-14: the error is roughly Gaussian about the extrapolated value, $k$ = 1.1 to 1.15; 1.15 is the conservative end |
| a spread bound (oscillatory convergence) | 2 | V&V 20, eq. 2-4-13: Gaussian about the fine-grid value. The spread bound itself is foam-verify's convention ([gci.md](gci.md)), so applying this divisor to it is too |
| two grids (assumed-order GCI) | 1.15 | the standard gives none; 1.15 gives the larger, conservative $u_\text{num}$ (foam-verify's choice) |

When the experiment also states its standard uncertainty $u_D$ and $U_\text{input}$ is zero,
$u_\text{val} = \sqrt{u_\text{num}^2 + u_D^2}$ is given too.

## No numerical uncertainty

A divergent or degenerate grid study has no $U_\text{num}$. The comparison still gives $E$, with
the outcome `no_uncertainty`: $E$ alone cannot be judged.

## In a study

A study lists its reference values in `study.toml`, one `[[reference]]` table each, and
`foam-verify report` compares each with its QoI's finest-grid value and U:

```toml
[[reference]]
qoi = "u(y=0.5)"           # the name of a [[qoi]]
kind = "code"              # exact | code | experiment
label = "Marchi et al. (2009)"   # optional: how the report names it
value = -0.2091491418
uncertainty = 8.6e-9       # U_D at 95%
source = "Marchi, Suero and Araki (2009), J. Braz. Soc. Mech. Sci. & Eng. 31(3), 186-198, Tables 6 and 7, Re = 100"
```

`qoi`, `kind`, `value` and `source` are required: a reference that does not say where it comes
from cannot be checked. The optional keys follow the rules above. `uncertainty` is $U_D$ at 95%,
optional for a code reference and required for an experiment; `standard_uncertainty` ($u_D$),
`input_uncertainty` ($U_\text{input}$ at 95%) and `c` apply to experiments only. `label` is a
short name for the report's table, the source by default. A QoI can have several references, or
none; the labels tell them apart. A reference that breaks a rule stops the study from loading,
with the reason.

A published error estimate is not always a 95% uncertainty. When a reference states its error
some other way, say how it was turned into `uncertainty` in a comment beside it, as the cavity's
`study.toml` does for Marchi et al.'s estimates.

The report lists the comparisons in a section of their own, after the verdict, and in its JSON
as `comparisons` ([report.md](report.md)). They are no part of the verdict, and never change the
exit code: the verdict says whether a value is converged, the comparison how far it is from a
reference. Folding one into the other would make a code-to-code disagreement look like a
convergence failure, and a lucky agreement look like verification. Keeping them apart is
foam-verify's convention.

The committed studies:

- The square duct against its exact f Re, kind `exact`: $\lvert E\rvert = 0.797\,U_\text{num}$,
  within the uncertainty.
- The cavity's u at the centre and its three extrema against Marchi et al. (2009), kind `code`
  with $U_D$ from their error estimates: $\lvert E\rvert$ = 0.77 to 0.81 $U_\text{val}$, within
  the uncertainty.
- The cavity's three points against Ghia et al.'s Table I, kind `code`: $\lvert E\rvert$ = 7 to
  39 $U_\text{num}$, outside the uncertainty. Ghia et al. state no uncertainty, so this comparison
  alone cannot say which solution carries the difference. At y = 0.5, Marchi et al.'s value
  puts it on Ghia's side. The
  [cavity README](../studies/cavity/README.md#against-two-reference-solutions) discusses both.

## Not covered

- Correlated errors between the simulation and the experiment (V&V 20, section 5, cases 2-4).
- Propagating input uncertainty through the simulation (V&V 20, section 3): $U_\text{input}$ is
  given, not computed.
