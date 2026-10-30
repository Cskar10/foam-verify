"""Iterative convergence of a QoI history: converged, oscillating and drifting series."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable

import pytest

from foam_verify.iterative import (
    IterativeResult,
    Options,
    Verdict,
    check_contamination,
    iterative_convergence,
    window_size,
)

N = 1000  # samples; the default window is the last 100 (x = 900 to 999)

WAVES: dict[str, Callable[[float], float]] = {
    "sine": lambda u: math.sin(2 * math.pi * u),
    "square": lambda u: 1.0 if u % 1 < 0.5 else -1.0,
    "sawtooth": lambda u: 2 * (u % 1) - 1,
    "triangle": lambda u: 4 * abs(u % 1 - 0.5) - 1,
}


def half_range(res: IterativeResult) -> float:
    assert res.maximum is not None and res.minimum is not None
    return 0.5 * (res.maximum - res.minimum)


def sine(amplitude: float, period: float, drift_per_sample: float = 0.0) -> list[float]:
    return [
        1 + amplitude * math.sin(2 * math.pi * i / period) + drift_per_sample * i for i in range(N)
    ]


# --- converged --------------------------------------------------------------------------


def test_settled_exponential_is_converged() -> None:
    res = iterative_convergence([2 + 0.5 * math.exp(-i / 50) for i in range(N)])
    assert res.verdict is Verdict.CONVERGED and res.clean_pass
    assert res.samples == N and res.window == 100 and res.window_x == (900, 999)
    assert res.uncertainty is not None and res.uncertainty < 1e-8
    assert res.uncertainty == pytest.approx(half_range(res))
    assert res.warnings == ()


def test_round_off_noise_is_converged() -> None:
    rng = random.Random(1)
    res = iterative_convergence([56.9 + 1e-12 * rng.gauss(0, 1) for _ in range(N)])
    assert res.verdict is Verdict.CONVERGED and res.clean_pass
    assert res.relative_range is not None and res.relative_range < 1e-12


def test_noise_in_a_few_short_cycles_is_not_drift() -> None:
    # A converged value written to four decimals: the noise forms a few short cycles late in
    # the window, and the trend of their means, extrapolated across the window, would move 3.3
    # times as far as the samples range (a drift of 2.6e-3, above tol). No trend carries the
    # QoI further than its samples range, so the least-squares line is kept.
    rng = random.Random(33)
    res = iterative_convergence([round(1 + 4e-4 * rng.uniform(-1, 1), 4) for _ in range(200)])
    assert res.verdict is Verdict.CONVERGED and res.clean_pass
    assert res.drift_method == "least_squares" and res.cycles is not None and res.cycles >= 2
    assert res.drift is not None and abs(res.drift) < 0.3 * 2 * half_range(res)


def test_noise_below_tol_is_never_drifting() -> None:
    # 800 converged histories, noise range about 0.8 tol, full precision and four decimals.
    # Extrapolated cycle means called five of them drifting.
    for seed in range(400):
        rng = random.Random(seed)
        noisy = [1 + 4e-4 * rng.uniform(-1, 1) for _ in range(200)]
        for values in (noisy, [round(v, 4) for v in noisy]):
            assert iterative_convergence(values).verdict is Verdict.CONVERGED, seed


def test_constant_history_has_zero_uncertainty() -> None:
    res = iterative_convergence([3.0] * N)
    assert res.verdict is Verdict.CONVERGED and res.clean_pass
    assert res.uncertainty == 0 and res.relative_range == 0 and res.relative_drift == 0


# --- oscillating ------------------------------------------------------------------------


@pytest.mark.parametrize("phase", [k / 8 for k in range(8)])
@pytest.mark.parametrize("wave", sorted(WAVES))
def test_steady_oscillation_is_oscillating_at_any_phase(wave: str, phase: float) -> None:
    # Four periods of 25 samples in the window, amplitude 1% of the mean.
    f = WAVES[wave]
    res = iterative_convergence([1 + 0.01 * f(i / 25 + phase) for i in range(N)])
    assert res.verdict is Verdict.OSCILLATING and not res.clean_pass
    assert res.drift_method == "cycle_means" and res.cycles is not None and res.cycles >= 2
    assert res.relative_drift is not None and abs(res.relative_drift) < 1e-5
    assert res.uncertainty == pytest.approx(half_range(res))
    assert res.uncertainty == pytest.approx(0.01, rel=0.05)
    assert any("half the range" in note for note in res.notes)


def test_least_squares_alone_would_call_a_steady_sine_drifting() -> None:
    # Why cycle means: the least-squares line through four periods of a steady sine tilts by
    # about half its amplitude, five times tol here.
    values = sine(0.01, 25)
    t = list(range(900, N))
    w = values[900:]
    tm, ym = sum(t) / len(t), sum(w) / len(w)
    slope = sum((a - tm) * (b - ym) for a, b in zip(t, w, strict=True)) / sum(
        (a - tm) ** 2 for a in t
    )
    assert abs(slope * 99) > 4e-3
    assert iterative_convergence(values).verdict is Verdict.OSCILLATING


def test_large_oscillation_keeps_a_flat_trend() -> None:
    # +-20%: the crossing level is refined about the cycle-mean trend, so it does not creep.
    for k in range(16):
        res = iterative_convergence(
            [1 + 0.2 * math.sin(2 * math.pi * (i / 25 + k / 16)) for i in range(N)]
        )
        assert res.verdict is Verdict.OSCILLATING
        assert res.relative_drift is not None and abs(res.relative_drift) < 1e-5


def test_damped_oscillation_about_a_fixed_value_is_oscillating() -> None:
    values = [1 + 0.05 * math.exp(-i / 300) * math.sin(2 * math.pi * i / 25) for i in range(N)]
    res = iterative_convergence(values)
    assert res.verdict is Verdict.OSCILLATING
    assert res.uncertainty == pytest.approx(half_range(res))


def test_oscillation_with_too_few_cycles_warns() -> None:
    res = iterative_convergence(sine(0.01, 66.7))  # 1.5 periods in the window
    assert res.verdict is Verdict.OSCILLATING and not res.clean_pass
    assert res.drift_method == "least_squares"
    assert any("full cycle" in w and "ITTC 7.5-03-02-01" in w for w in res.warnings)


# --- drifting ---------------------------------------------------------------------------


def test_linear_drift_is_drifting() -> None:
    res = iterative_convergence([1 + 2e-5 * i for i in range(N)])
    assert res.verdict is Verdict.DRIFTING and not res.clean_pass
    assert res.drift == pytest.approx(2e-5 * 99)
    assert res.uncertainty is None
    assert "still changing" in res.reasons[0]


def test_slow_exponential_approach_is_drifting() -> None:
    res = iterative_convergence([2 + 0.5 * math.exp(-i / 400) for i in range(N)])
    assert res.verdict is Verdict.DRIFTING
    assert res.relative_drift is not None and res.relative_drift < -1e-3
    assert res.drift_method == "least_squares"
    assert any("slow oscillation" in note for note in res.notes)


@pytest.mark.parametrize("wave", sorted(WAVES))
def test_drift_under_an_oscillation_is_drifting(wave: str) -> None:
    # 3e-5 per sample under a 1% oscillation: 0.3% across the window, less than the amplitude.
    f = WAVES[wave]
    res = iterative_convergence([1 + 0.01 * f(i / 25) + 3e-5 * i for i in range(N)])
    assert res.verdict is Verdict.DRIFTING
    assert res.drift_method == "cycle_means"
    assert res.drift == pytest.approx(3e-5 * 99, rel=0.05)


def test_drift_is_measured_in_x_with_uneven_sampling() -> None:
    rng = random.Random(3)
    xs = sorted(rng.uniform(0, 500) for _ in range(N))
    res = iterative_convergence([5 + 0.01 * x for x in xs], xs)
    assert res.verdict is Verdict.DRIFTING
    assert res.window_x == (xs[-100], xs[-1])
    assert res.drift == pytest.approx(0.01 * (xs[-1] - xs[-100]), rel=1e-9)


def test_noisy_drift_within_its_standard_error_is_not_resolved() -> None:
    # Noise of 1e-3 (tol) on a constant: the cycle-mean trend is 1.6e-3, inside twice its
    # standard error, so the window cannot tell drift from noise.
    rng = random.Random(13)
    res = iterative_convergence([1 + 1e-3 * rng.gauss(0, 1) for _ in range(N)])
    assert res.verdict is Verdict.OSCILLATING and not res.clean_pass
    assert res.relative_drift is not None and abs(res.relative_drift) > 1e-3
    assert res.drift is not None and res.drift_noise is not None
    assert abs(res.drift) <= res.drift_noise
    assert any("cannot tell drift" in w for w in res.warnings)


# --- data that cannot be judged ---------------------------------------------------------


def test_short_history_is_judged_with_a_warning() -> None:
    res = iterative_convergence([1.0] * 20)
    assert res.verdict is Verdict.CONVERGED and not res.clean_pass
    assert res.window == 20
    assert any("fewer than min_samples" in w for w in res.warnings)


@pytest.mark.parametrize("values", [[], [1.0], [1.0, 1.0]])
def test_too_few_samples_is_insufficient_data(values: list[float]) -> None:
    res = iterative_convergence(values)
    assert res.verdict is Verdict.INSUFFICIENT_DATA and not res.clean_pass
    assert res.uncertainty is None
    assert "not only at the end" in res.reasons[0]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_sample_is_reported(bad: float) -> None:
    values = [1.0] * 10
    values[6] = bad
    res = iterative_convergence(values, [0.1 * i for i in range(10)])
    assert res.verdict is Verdict.NON_FINITE
    assert "sample 7 of 10 (x = 0.6)" in res.reasons[0]


def test_zero_mean_needs_a_reference() -> None:
    values = [0.01 * math.sin(2 * math.pi * i / 25) for i in range(N)]
    res = iterative_convergence(values)
    assert res.verdict is Verdict.NO_SCALE and res.uncertainty is None
    res = iterative_convergence(values, reference=0.5)
    assert res.verdict is Verdict.OSCILLATING
    assert res.scale == 0.5
    assert res.relative_range == pytest.approx(0.02 / 0.5, rel=0.01)


THREE = [1.0, 1.0, 1.0]


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: iterative_convergence(THREE, [1.0, 2.0]), "one entry per value"),
        (lambda: iterative_convergence(THREE, [0.0, 2.0, 1.0]), "non-decreasing"),
        (lambda: iterative_convergence(THREE, [0.0, math.nan, 1.0]), "finite"),
        (lambda: iterative_convergence(THREE, reference=0.0), "reference"),
        (lambda: iterative_convergence(THREE, options=Options(window=0)), "window"),
        (lambda: iterative_convergence(THREE, options=Options(min_window=1)), "min_window"),
        (lambda: iterative_convergence(THREE, options=Options(tol=0)), "tol"),
        (lambda: iterative_convergence(THREE, options=Options(min_periods=-1)), "non-negative"),
    ],
)
def test_bad_input_raises(call: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        call()


def test_window_size() -> None:
    assert window_size(1000, 0.1, 50) == 100
    assert window_size(200, 0.1, 50) == 50
    assert window_size(30, 0.1, 50) == 30


def test_result_serialises() -> None:
    res = iterative_convergence(sine(0.01, 25))
    data = json.loads(json.dumps(res.to_dict()))
    assert data["verdict"] == "oscillating"
    assert data["window_x"] == [900, 999]


# --- contamination of the grid study ----------------------------------------------------


def converged(u_it: float) -> IterativeResult:
    """A converged history whose half range is u_it, around 1."""
    return iterative_convergence([1 + u_it * (-1) ** i for i in range(N)])


def test_small_iterative_uncertainty_is_clean() -> None:
    results = [converged(1e-6), converged(1e-7), converged(0.0)]
    check = check_contamination(results, 1e-3, names=["fine", "medium", "coarse"])
    assert check.clean_pass and check.warnings == ()
    assert check.worst_level == "fine"
    assert check.worst_ratio == pytest.approx(1e-3)
    assert "largest u_it / U" in check.notes[-1]


def test_large_iterative_uncertainty_contaminates() -> None:
    results = [converged(1e-6), converged(2e-4), converged(1e-6)]
    check = check_contamination(results, 1e-3, names=["fine", "medium", "coarse"])
    assert not check.clean_pass
    assert check.worst_level == "medium" and check.worst_ratio == pytest.approx(0.2)
    assert any("level medium" in w and "ASME V&V 20, para. 2-4" in w for w in check.warnings)


def test_default_margin_is_two_orders() -> None:
    # ASME V&V 20, para. 2-4: 2 to 3 orders "to guarantee a negligible influence". Celik et al.
    # (2008, Appendix A) ask for one, which ratio=10 gives.
    results = [converged(5e-5), converged(0.0), converged(0.0)]
    strict = check_contamination(results, 1e-3)
    assert strict.ratio == 100.0 and not strict.clean_pass
    assert strict.worst_ratio == pytest.approx(0.05)
    assert any("more than 1/100" in w for w in strict.warnings)
    assert check_contamination(results, 1e-3, ratio=10.0).clean_pass


def test_oscillating_level_below_the_ratio_is_noted_not_blocked() -> None:
    osc = iterative_convergence(sine(0.01, 25))
    check = check_contamination([osc, converged(0.0)], 1.0, names=["fine", "coarse"])
    assert check.clean_pass
    assert any("level fine: oscillating, but" in note for note in check.notes)


def test_only_headline_levels_block() -> None:
    drifting = iterative_convergence([1 + 2e-5 * i for i in range(N)])
    good = converged(1e-9)
    names = ["1", "2", "3", "4"]
    check = check_contamination([good, good, good, drifting], 1e-3, names=names, used=3)
    assert check.clean_pass
    assert any("level 4 (not in the headline result): drifting" in n for n in check.notes)
    check = check_contamination([good, drifting, good, good], 1e-3, names=names, used=3)
    assert not check.clean_pass
    assert any(w.startswith("level 2: drifting") for w in check.warnings)


def test_headline_warnings_block() -> None:
    short = iterative_convergence([1.0] * 20)
    check = check_contamination([short, converged(0.0)], 1.0)
    assert not check.clean_pass
    assert any("level 1: only 20 samples" in w for w in check.warnings)


def test_no_discretisation_uncertainty_is_not_a_clean_pass() -> None:
    check = check_contamination([converged(0.0), converged(0.0)], None)
    assert not check.clean_pass and check.worst_ratio is None
    assert "no discretisation uncertainty" in check.notes[-1]


def test_contamination_arguments_are_checked() -> None:
    with pytest.raises(ValueError, match="ratio"):
        check_contamination([converged(0.0)], 1.0, ratio=1.0)
    with pytest.raises(ValueError, match="names"):
        check_contamination([converged(0.0)], 1.0, names=["a", "b"])
