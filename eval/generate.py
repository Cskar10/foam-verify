"""Evaluation bundles: the new runs they need, and the bundles themselves.

    python3 eval/generate.py setup     # writes the new runs' cases under eval/build/
    bash eval/run.sh                   # inside the pinned container (see studies/README.md)
    python3 eval/generate.py collect   # assembles eval/bundles/bNN

The labels (eval/labels.toml) were committed before this file. Each new run is one of the
committed studies' cases with one thing changed, written by that study's own generator
(studies/<case>/generate.py) with the setting overridden, so everything else stays as committed:

- cavity-t1: the cavity's four levels to endTime 1 s instead of 10 s;
- cavity-lu80: the cavity's 80x80 level with div(phi,U) Gauss linearUpwind grad(U);
- duct-r11: the duct at 145x145, 132x132 and 120x120, refinement ratios of about 1.1;
- pitz-rc: pitzDaily's four levels with the tutorial's residualControl restored, and the pressure
  drop, its inputs and the residuals written every iteration.

A bundle is a grid study as foam-verify reads it: study.toml with the one QoI asked about, and a
case folder per level, from a new run (trimmed as the studies trim theirs) or copied from the
committed study. Nothing in a bundle says what its label is: no report, README, reference value
or telling comment, and neutral names. Standard library only, so it runs on any host Python 3.11+.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STUDIES = ROOT / "studies"
BUILD = HERE / "build"
BUNDLES = HERE / "bundles"


def study_generator(case: str) -> ModuleType:
    """A fresh copy of studies/<case>/generate.py, so that overriding a setting changes no other."""
    path = STUDIES / case / "generate.py"
    spec = importlib.util.spec_from_file_location(f"generate_{case}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replaced(text: str, old: str, new: str) -> str:
    """text with old replaced exactly once, so that a changed generator cannot slip by."""
    if text.count(old) != 1:
        raise SystemExit(f"expected one {old!r}, found {text.count(old)}")
    return text.replace(old, new)


def cavity_t1() -> ModuleType:
    m = study_generator("cavity")
    m.END_TIME = 1
    return m


def cavity_lu80() -> ModuleType:
    m = study_generator("cavity")
    m.LEVELS = (80,)
    m.SCHEMES = replaced(
        m.SCHEMES, "div(phi,U)      Gauss linear;", "div(phi,U)      Gauss linearUpwind grad(U);"
    )
    return m


def duct_r11() -> ModuleType:
    m = study_generator("duct")
    m.LEVELS = (145, 132, 120)
    return m


TUTORIAL_RESIDUAL_CONTROL = """    consistent      yes;

    residualControl
    {
        p               1e-2;
        U               1e-3;
        "(k|epsilon|omega|f|v2)" 1e-3;
    }
}"""


def pitz_rc() -> ModuleType:
    m = study_generator("pitzDaily")
    m.SOLUTION = replaced(m.SOLUTION, "    consistent      yes;\n}", TUTORIAL_RESIDUAL_CONTROL)
    # The pressure drop, its inlet and outlet inputs and the residuals: every iteration.
    for key, count in (("writeInterval   ", 4), ("executeInterval ", 1)):
        every = f"{key}{m.SAMPLE_EVERY};"
        if m.CONTROL.count(every) != count:
            raise SystemExit(f"expected {count} {every!r} in the pitzDaily controlDict")
        m.CONTROL = m.CONTROL.replace(every, f"{key}1;")
    return m


RUNS = {
    "cavity-t1": cavity_t1,
    "cavity-lu80": cavity_lu80,
    "duct-r11": duct_r11,
    "pitz-rc": pitz_rc,
}


def setup() -> None:
    for run, make in RUNS.items():
        m = make()
        m.BUILD = BUILD / run
        m.setup()


# --- bundles ----------------------------------------------------------------------------

CAVITY_HEAD = """\
# Lid-driven cavity, Re = 100, icoFoam. Velocities are in units of the lid speed (1 m/s); probe
# coordinates are in metres (L = 0.1).
name = "lid-driven-cavity"
dim = 2
formal_order = 2
refined = "mesh"
grid_sequence = "structured"
"""

DUCT_HEAD = """\
# Square duct, fully developed laminar flow, Re = 100.
name = "square-duct"
dim = 2            # the cross-section is refined; the one cyclic cell along the flow is not
formal_order = 2
refined = "mesh"
grid_sequence = "structured"
"""

PITZ_HEAD = """\
# pitzDaily: the backward-facing step, simpleFoam, k-epsilon with wall functions. Pressures are
# kinematic (m^2/s^2).
name = "pitzDaily"
dim = 2            # one cell thick, empty front and back
formal_order = 2
refined = "mesh"
grid_sequence = "structured"
"""

QOIS = {
    "u(y=0.5)": """\
# u on the vertical centreline at y = 64/128 of L.
[[qoi]]
name = "u(y=0.5)"
file = "postProcessing/ghiaPoints/*/U"
column = "0"
component = "x"
""",
    "u(y=0.8516)": """\
# u on the vertical centreline at y = 109/128 of L.
[[qoi]]
name = "u(y=0.8516)"
file = "postProcessing/ghiaPoints/*/U"
column = "2"
component = "x"
""",
    "v_min": """\
# The minimum of v on the horizontal centreline (255 probes, spacing L/256, parabola at the
# minimum).
[[qoi]]
name = "v_min"
file = "postProcessing/horizontalCentreline/*/U"
profile = "min"
axis = "x"
component = "y"
""",
    "u_min": """\
# The minimum of u on the vertical centreline (255 probes, spacing L/256, parabola at the
# minimum).
[[qoi]]
name = "u_min"
file = "postProcessing/verticalCentreline/*/U"
profile = "min"
axis = "y"
component = "x"
""",
    "v_max": """\
# The maximum of v on the horizontal centreline (255 probes, spacing L/256, parabola at the
# maximum).
[[qoi]]
name = "v_max"
file = "postProcessing/horizontalCentreline/*/U"
profile = "max"
axis = "x"
component = "y"
""",
    "fRe": """\
# Darcy f Re = 8 tau_w D_h / (nu Ubar) = 800 tau_w with D_h = 1, nu = 0.01, Ubar = 1. With
# this function object's sign convention the x component is negative for flow along +x, hence
# the minus sign.
[[qoi]]
name = "fRe"
file = "postProcessing/wallStress/*/surfaceFieldValue.dat"
column = "areaAverage(wallShearStress)"
component = "x"
reduction = "last"
scale = -800.0
""",
    "dp0": """\
# Total-pressure loss: inlet minus outlet area averages of p + |U|^2/2, the mean over the last
# 10% of the samples.
[[qoi]]
name = "dp0"
file = "postProcessing/pressureDrop/*/multiFieldValue.dat"
column = "Group1"
reduction = "window_mean"
""",
    "xR/H": """\
# Reattachment length in step heights (H = 25.4 mm): the last change of sign of the lower-wall
# shear stress along x, from the 11 samples written over the last 2000 iterations.
[[qoi]]
name = "xR/H"
file = "postProcessing/lowerWallShear/*/wallShearStress_lowerWall.raw"
profile = "last_crossing"
axis = "x"
component = "x"
scale = 39.37007874015748
window = 1.0
min_samples = 11
""",
    "dp": """\
# Static pressure difference, inlet minus outlet area averages, the mean over the last 10% of
# the samples.
[[qoi]]
name = "dp"
file = "postProcessing/pressureDrop/*/multiFieldValue.dat"
column = "Group0"
reduction = "window_mean"
""",
}


@dataclass(frozen=True)
class Level:
    """One level of a bundle: its name, its folder, and where it comes from: a new run's
    folder under eval/build/<run>/, or the committed study's when run is None."""

    name: str
    folder: str
    run: str | None = None


@dataclass(frozen=True)
class Bundle:
    id: str
    study: str  # the committed study it is built from, under studies/
    head: str
    qoi: str
    levels: tuple[Level, ...]


def square(n: int, run: str | None = None) -> Level:
    """An n x n level of the cavity or the duct."""
    return Level(f"{n}x{n}", f"n{n}", run)


def pitz(cells: str, run: str | None = None) -> Level:
    return Level(cells, f"n{cells}", run)


DUCT_LEVELS = tuple(square(n) for n in (160, 80, 40, 20))
CAVITY_LEVELS = DUCT_LEVELS
PITZ_LEVELS = tuple(pitz(c) for c in ("139k", "62k", "28k", "12k"))

BUNDLE_LIST = (
    Bundle(
        "b01",
        "cavity",
        CAVITY_HEAD,
        "u(y=0.8516)",
        tuple(square(n, "cavity-t1") for n in (160, 80, 40, 20)),
    ),
    Bundle("b02", "duct", DUCT_HEAD, "fRe", DUCT_LEVELS[:2]),
    Bundle(
        "b03",
        "duct",
        DUCT_HEAD,
        "fRe",
        (square(160), *(square(n, "duct-r11") for n in (145, 132, 120))),
    ),
    Bundle("b04", "pitzDaily", PITZ_HEAD, "dp0", PITZ_LEVELS[1:]),
    Bundle(
        "b05",
        "cavity",
        CAVITY_HEAD,
        "v_min",
        (square(160), square(80, "cavity-lu80"), square(40), square(20)),
    ),
    Bundle("b06", "duct", DUCT_HEAD, "fRe", DUCT_LEVELS),
    Bundle("b07", "cavity", CAVITY_HEAD, "u(y=0.5)", CAVITY_LEVELS[:3]),
    Bundle("b08", "pitzDaily", PITZ_HEAD, "dp0", PITZ_LEVELS),
    Bundle("b09", "cavity", CAVITY_HEAD, "v_max", CAVITY_LEVELS),
    Bundle(
        "b10",
        "cavity",
        CAVITY_HEAD,
        "u(y=0.5)",
        (square(160, "cavity-t1"), square(80), square(40), square(20)),
    ),
    Bundle("b11", "duct", DUCT_HEAD, "fRe", DUCT_LEVELS[:3]),
    Bundle(
        "b12",
        "pitzDaily",
        PITZ_HEAD,
        "dp",
        tuple(pitz(c, "pitz-rc") for c in ("139k", "62k", "28k", "12k")),
    ),
)


# Two pilot bundles, for trying the agent harness (eval/run_agents.py) and the scorer before
# any scored run. Their QoIs are ones no evaluation bundle asks about, so the pilot shows
# nothing of the evaluation's answers. They are not part of the evaluation.
PILOT = HERE / "pilot" / "bundles"
PILOT_LIST = (
    Bundle("p01", "cavity", CAVITY_HEAD, "u_min", CAVITY_LEVELS),
    Bundle("p02", "pitzDaily", PITZ_HEAD, "xR/H", PITZ_LEVELS),
)


def manifest(bundle: Bundle) -> str:
    levels = "".join(
        f'\n[[levels]]\nname = "{lv.name}"\npath = "{lv.folder}"\n' for lv in bundle.levels
    )
    return f"{bundle.head}{levels}\n{QOIS[bundle.qoi]}"


def collect_level(bundle: Bundle, level: Level, dest: Path) -> None:
    if level.run is None:
        shutil.copytree(STUDIES / bundle.study / level.folder, dest / level.folder)
        return
    m = RUNS[level.run]()
    m.BUILD = BUILD / level.run
    m.HERE = dest
    if bundle.study in ("cavity", "duct"):
        m.LEVELS = (int(level.folder.removeprefix("n")),)
    else:  # pitzDaily names its levels by cell count; its generator by refinement step
        m.LEVELS = tuple(k for k in m.LEVELS if m.name(k) == level.folder)
    m.collect()


def collect() -> None:
    for bundle, root in [(b, BUNDLES) for b in BUNDLE_LIST] + [(b, PILOT) for b in PILOT_LIST]:
        missing = [
            f"{lv.run}/{lv.folder}"
            for lv in bundle.levels
            if lv.run is not None and not (BUILD / lv.run / lv.folder / "postProcessing").is_dir()
        ]
        if missing:
            print(f"{bundle.id}: not run yet: {', '.join(missing)}")
            continue
        dest = root / bundle.id
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for level in bundle.levels:
            collect_level(bundle, level, dest)
        (dest / "study.toml").write_text(manifest(bundle))
        print(f"{bundle.id}: {len(bundle.levels)} levels, qoi {bundle.qoi}")


if __name__ == "__main__":
    commands = {"setup": setup, "collect": collect}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: python3 {Path(__file__).name} setup|collect")
    commands[sys.argv[1]]()
