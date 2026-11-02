"""Grid studies on disk: the study.toml manifest, mesh headers and function-object output.

A study is a folder holding study.toml and one OpenFOAM case per grid level. Everything here
reads; nothing writes, runs a solver or leaves the study folder. Cell counts come from the
note in the header of constant/polyMesh/owner, and quantities of interest from the tables
that function objects write under postProcessing/. Each QoI's history on every level is also
checked for iterative convergence over the QoI's window (window, min_samples), and its
iterative uncertainty compared with the grid study's discretisation uncertainty. The levels'
settings are compared too (foam_verify.consistency): they should differ only in the mesh. And
the refined directions d are checked against the patches of every level: empty and wedge
patches, and pairs of patches with one face per cell, which a mesh one cell across has.

study.toml, levels finest first:

    name = "square-duct"
    dim = 2                    # refined directions
    formal_order = 2           # optional, default 2
    refined = "mesh"           # mesh | core | boundary-layer
    grid_sequence = "structured"  # structured | unstructured: how the levels were generated
    layer_cells = 0            # core only: fixed layer cells, optional

    [[levels]]
    name = "160"
    path = "n160"              # case folder, relative to study.toml
    first_layer_height = 1e-3  # boundary-layer studies only

    [[qoi]]
    name = "fRe"
    file = "postProcessing/wall/*/surfaceFieldValue.dat"   # relative to each case, glob
    column = "areaAverage(wallShearStress)"                # header name, or 0-based index
    component = "x"            # vectors only: x | y | z | 0 | 1 | 2
    reduction = "last"         # last | window_mean
    window = 0.1               # window_mean and the iterative check: last fraction of samples...
    min_samples = 50           # ...but at least this many
    scale = 1.0                # multiplies the reduced value (unit or non-dimensional factor)

A QoI can instead come from a sampled profile: a probes function object with one point per
column, or the raw files of a surfaces function object (surfaceFormat raw), one per time
folder. The value comes from the last row or the latest file; every row or file in turn is
the history the iterative check reads. Give profile and axis instead of column:

    [[qoi]]
    name = "u_min"
    file = "postProcessing/centreline/*/U"
    profile = "min"            # min | max | first_crossing | last_crossing
    axis = "y"                 # coordinate along the profile: x | y | z
    component = "x"

min and max fit a parabola through the discrete extremum and its two neighbours, so the value
moves smoothly with the field rather than jumping from point to point. first_crossing and
last_crossing are the coordinate where the values change sign, interpolated between the two
points that bracket it: the reattachment point behind a step is the last change of sign of the
wall shear stress, say.

A study can also give reference values for its QoIs. compare_references() sets each against
the QoI's finest-grid value and U (foam_verify.compare); the report lists the comparisons
apart from its verdict:

    [[reference]]
    qoi = "dp"                 # the name of a [[qoi]]
    kind = "experiment"        # exact | code | experiment
    value = 12.4
    source = "rig test report, run 7"   # where the value comes from
    uncertainty = 0.6          # U_D at 95%: none for exact, optional for code, required here
    standard_uncertainty = 0.3     # experiment only, optional: u_D
    input_uncertainty = 0.0    # experiment only, optional: U_input at 95%
    c = 10                     # experiment only, optional: Eça, Dowding and Roache's C

A QoI can have several references, or none.
"""

from __future__ import annotations

import gzip
import math
import re
import tomllib
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, cast

from .compare import (
    DEFAULT_C,
    Comparison,
    Reference,
    ReferenceKind,
    check_reference,
    compare_result,
)
from .consistency import ConsistencyResult, settings_consistency
from .gci import GCIResult, GridSequence, Options, Scope, grid_convergence
from .iterative import (
    ContaminationCheck,
    IterativeResult,
    check_contamination,
    iterative_convergence,
)
from .iterative import Options as IterativeOptions

MANIFEST = "study.toml"
REDUCTIONS = ("last", "window_mean")
EXTREMA = ("min", "max")
CROSSINGS = ("first_crossing", "last_crossing")
PROFILES = EXTREMA + CROSSINGS
_COMPONENTS = {"x": 0, "y": 1, "z": 2, "0": 0, "1": 1, "2": 2}
_TWO_D_PATCHES = ("empty", "wedge")
_TOKEN = re.compile(r"\([^()]*\)|\S+")
_PROBE = re.compile(r"#\s*Probe\s+(\d+)\s*\(([^()]*)\)")


class StudyError(ValueError):
    """The study folder, its manifest or a file it points to is unusable."""


@dataclass(frozen=True)
class Level:
    name: str
    path: Path
    first_layer_height: float | None = None


@dataclass(frozen=True)
class QoI:
    name: str
    file: str
    column: str | int | None
    component: int | None = None
    reduction: str = "last"
    window: float = 0.1
    min_samples: int = 50
    scale: float = 1.0
    profile: str | None = None
    axis: int | None = None


@dataclass(frozen=True)
class QoIReference:
    """A reference value for one QoI, as study.toml gives it, with the options to compare."""

    qoi: str
    reference: Reference
    input_uncertainty: float = 0.0
    c: float = DEFAULT_C


@dataclass(frozen=True)
class Study:
    root: Path
    name: str
    dim: int
    formal_order: float
    scope: Scope
    grid_sequence: GridSequence
    layer_cells: float | None
    levels: tuple[Level, ...]
    qois: tuple[QoI, ...]
    references: tuple[QoIReference, ...] = ()


@dataclass(frozen=True)
class Series:
    """One QoI column over time or iterations, from one or more function-object files."""

    x: tuple[float, ...]
    y: tuple[float, ...]
    files: tuple[str, ...]


@dataclass(frozen=True)
class LevelInfo:
    name: str
    path: str
    cells: int
    two_d_patches: tuple[str, ...]
    first_layer_height: float | None


@dataclass(frozen=True)
class QoIResult:
    name: str
    values: tuple[float, ...]
    samples: tuple[int, ...]
    notes: tuple[str, ...]
    gci: GCIResult
    # Iterative convergence of the QoI's history on each level, finest first, and the check
    # of its iterative uncertainty against the grid study's discretisation uncertainty.
    iterative: tuple[IterativeResult, ...] = ()
    contamination: ContaminationCheck | None = None


@dataclass(frozen=True)
class StudyResult:
    name: str
    root: str
    dim: int
    scope: Scope
    grid_sequence: GridSequence
    levels: tuple[LevelInfo, ...]
    qois: tuple[QoIResult, ...]
    warnings: tuple[str, ...]
    # Do the levels differ only in the mesh? Their settings compared entry by entry.
    consistency: ConsistencyResult | None = None
    # What the mesh checks confirmed, such as a direction that is one cell across.
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QoIComparison:
    """One QoI's finest-grid value and U set against one of its references."""

    qoi: str
    comparison: Comparison


def gci_options(study: Study) -> Options:
    """The GCI options a study is judged by: the defaults, at the study's formal order."""
    return Options(formal_order=study.formal_order)


def iterative_options(qoi: QoI) -> IterativeOptions:
    """The iterative-convergence options for one QoI: its window, the default tolerance."""
    return IterativeOptions(window=qoi.window, min_samples=qoi.min_samples)


# --- manifest ---------------------------------------------------------------------------


def _inside(path: Path, root: Path, what: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise StudyError(f"{what} {path} is outside {root}")
    return resolved


def _check_keys(table: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise StudyError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _positive(value: Any, key: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise StudyError(f"{where}: {key} must be a positive number, got {value!r}")
    return float(value)


def _parse_level(item: object, root: Path, i: int) -> Level:
    where = f"levels[{i}]"
    if not isinstance(item, dict):
        raise StudyError(f"{where} must be a table")
    raw = cast(dict[str, Any], item)
    _check_keys(raw, {"name", "path", "first_layer_height"}, where)
    if not isinstance(raw.get("path"), str):
        raise StudyError(f"{where}: path is required")
    path = _inside(root / raw["path"], root, f"{where} path")
    if not path.is_dir():
        raise StudyError(f"{where}: case folder {raw['path']} does not exist")
    height = raw.get("first_layer_height")
    return Level(
        name=str(raw.get("name", raw["path"])),
        path=path,
        first_layer_height=None
        if height is None
        else _positive(height, "first_layer_height", where),
    )


def _parse_qoi(item: object, i: int) -> QoI:
    where = f"qoi[{i}]"
    if not isinstance(item, dict):
        raise StudyError(f"{where} must be a table")
    raw = cast(dict[str, Any], item)
    allowed = {
        "name",
        "file",
        "column",
        "component",
        "reduction",
        "window",
        "min_samples",
        "scale",
        "profile",
        "axis",
    }
    _check_keys(raw, allowed, where)
    for key in ("name", "file"):
        if key not in raw:
            raise StudyError(f"{where}: {key} is required")
    profile = raw.get("profile")
    axis = None
    column = raw.get("column")
    if profile is None:
        if "axis" in raw:
            raise StudyError(f"{where}: axis applies only to a profile qoi")
        if isinstance(column, bool) or not isinstance(column, str | int):
            raise StudyError(f"{where}: column is required: a header name or a 0-based index")
    else:
        if profile not in PROFILES:
            raise StudyError(f"{where}: profile must be one of {', '.join(PROFILES)}")
        if column is not None:
            raise StudyError(f"{where}: a profile qoi uses every probe column; drop column")
        if raw.get("reduction", "last") != "last":
            raise StudyError(f"{where}: a profile qoi is read at its last row; drop reduction")
        if str(raw.get("axis")) not in ("x", "y", "z"):
            raise StudyError(f"{where}: axis must be x, y or z for a profile qoi")
        axis = _COMPONENTS[str(raw["axis"])]
    component = raw.get("component")
    if component is not None:
        if str(component) not in _COMPONENTS:
            raise StudyError(f"{where}: component must be x, y, z or 0, 1, 2")
        component = _COMPONENTS[str(component)]
    reduction = raw.get("reduction", "last")
    if reduction not in REDUCTIONS:
        raise StudyError(f"{where}: reduction must be one of {', '.join(REDUCTIONS)}")
    window = _positive(raw.get("window", 0.1), "window", where)
    if window > 1:
        raise StudyError(f"{where}: window is a fraction of the samples, at most 1")
    min_samples = raw.get("min_samples", 50)
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 1:
        raise StudyError(f"{where}: min_samples must be a positive integer")
    scale = raw.get("scale", 1.0)
    if isinstance(scale, bool) or not isinstance(scale, int | float) or not math.isfinite(scale):
        raise StudyError(f"{where}: scale must be a finite number")
    return QoI(
        name=str(raw["name"]),
        file=str(raw["file"]),
        column=column,
        component=component,
        reduction=reduction,
        window=window,
        min_samples=min_samples,
        scale=float(scale),
        profile=None if profile is None else str(profile),
        axis=axis,
    )


def _number(value: Any, key: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise StudyError(f"{where}: {key} must be a finite number, got {value!r}")
    return float(value)


def _optional_number(raw: dict[str, Any], key: str, where: str) -> float | None:
    return None if key not in raw else _number(raw[key], key, where)


def _parse_reference(item: object, i: int, qois: set[str]) -> QoIReference:
    where = f"reference[{i}]"
    if not isinstance(item, dict):
        raise StudyError(f"{where} must be a table")
    raw = cast(dict[str, Any], item)
    allowed = {
        "qoi",
        "kind",
        "value",
        "source",
        "uncertainty",
        "standard_uncertainty",
        "input_uncertainty",
        "c",
    }
    _check_keys(raw, allowed, where)
    for key in ("qoi", "kind", "value", "source"):
        if key not in raw:
            raise StudyError(f"{where}: {key} is required")
    qoi = raw["qoi"]
    if not isinstance(qoi, str) or qoi not in qois:
        raise StudyError(f"{where}: qoi {qoi!r} is not the name of a [[qoi]]")
    try:
        kind = ReferenceKind(raw["kind"])
    except ValueError as exc:
        raise StudyError(f"{where}: kind must be exact, code or experiment") from exc
    source = raw["source"]
    if not isinstance(source, str) or not source.strip():
        raise StudyError(f"{where}: source must say where the value comes from")
    if "c" in raw and kind is not ReferenceKind.EXPERIMENT:
        raise StudyError(f"{where}: c applies to experiments only")
    reference = Reference(
        value=_number(raw["value"], "value", where),
        kind=kind,
        uncertainty=_optional_number(raw, "uncertainty", where),
        standard_uncertainty=_optional_number(raw, "standard_uncertainty", where),
        source=source.strip(),
    )
    input_uncertainty = _number(raw.get("input_uncertainty", 0.0), "input_uncertainty", where)
    c = _number(raw.get("c", DEFAULT_C), "c", where)
    try:
        check_reference(reference, input_uncertainty=input_uncertainty, c=c)
    except ValueError as exc:
        raise StudyError(f"{where}: {exc}") from exc
    return QoIReference(qoi, reference, input_uncertainty, c)


def load_study(path: str | Path) -> Study:
    """Read study.toml (or the folder holding it) and check that every case folder exists."""
    path = Path(path)
    manifest = path / MANIFEST if path.is_dir() else path
    root = manifest.parent
    try:
        raw = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StudyError(f"no {MANIFEST} at {manifest}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise StudyError(f"{manifest}: {exc}") from exc
    allowed = {
        "name",
        "dim",
        "formal_order",
        "refined",
        "grid_sequence",
        "layer_cells",
        "levels",
        "qoi",
        "reference",
    }
    _check_keys(raw, allowed, MANIFEST)

    dim = raw.get("dim")
    if isinstance(dim, bool) or dim not in (1, 2, 3):
        raise StudyError(f"{MANIFEST}: dim (refined directions) must be 1, 2 or 3")
    dim = cast(int, dim)
    if "refined" not in raw:
        raise StudyError(f"{MANIFEST}: refined is required: mesh, core or boundary-layer")
    try:
        scope = Scope(str(raw["refined"]).replace("-", "_"))
    except ValueError as exc:
        raise StudyError(f"{MANIFEST}: refined must be mesh, core or boundary-layer") from exc
    if "grid_sequence" not in raw:
        raise StudyError(
            f"{MANIFEST}: grid_sequence is required: structured (every level refines one base "
            "grid systematically) or unstructured"
        )
    try:
        grid_sequence = GridSequence(str(raw["grid_sequence"]))
    except ValueError as exc:
        raise StudyError(f"{MANIFEST}: grid_sequence must be structured or unstructured") from exc
    formal_order = _positive(raw.get("formal_order", 2.0), "formal_order", MANIFEST)
    layer_cells = raw.get("layer_cells")
    if layer_cells is not None:
        if scope is not Scope.CORE:
            raise StudyError(f"{MANIFEST}: layer_cells applies only to refined = core")
        if isinstance(layer_cells, bool) or not isinstance(layer_cells, int) or layer_cells < 0:
            raise StudyError(f"{MANIFEST}: layer_cells must be a non-negative integer")

    raw_levels = raw.get("levels", [])
    if not isinstance(raw_levels, list) or len(cast(list[Any], raw_levels)) < 2:
        raise StudyError(f"{MANIFEST}: a grid study needs at least two [[levels]], finest first")
    levels = tuple(_parse_level(lv, root, i) for i, lv in enumerate(cast(list[Any], raw_levels)))
    if len({lv.name for lv in levels}) != len(levels):
        raise StudyError(f"{MANIFEST}: level names must be unique")
    if scope is Scope.BOUNDARY_LAYER and any(lv.first_layer_height is None for lv in levels):
        raise StudyError(
            f"{MANIFEST}: refined = boundary-layer needs first_layer_height on every level: "
            "cell counts do not measure wall-normal refinement"
        )

    raw_qois = raw.get("qoi", [])
    if not isinstance(raw_qois, list) or not raw_qois:
        raise StudyError(f"{MANIFEST}: at least one [[qoi]] is required")
    qois = tuple(_parse_qoi(q, i) for i, q in enumerate(cast(list[Any], raw_qois)))
    if len({q.name for q in qois}) != len(qois):
        raise StudyError(f"{MANIFEST}: qoi names must be unique")

    raw_references = raw.get("reference", [])
    if not isinstance(raw_references, list):
        raise StudyError(f"{MANIFEST}: reference must be an array of tables, [[reference]]")
    names = {q.name for q in qois}
    references = tuple(
        _parse_reference(r, i, names) for i, r in enumerate(cast(list[Any], raw_references))
    )

    return Study(
        root=root.resolve(),
        name=str(raw.get("name", root.resolve().name)),
        dim=dim,
        formal_order=formal_order,
        scope=scope,
        grid_sequence=grid_sequence,
        layer_cells=None if layer_cells is None else float(layer_cells),
        levels=levels,
        qois=qois,
        references=references,
    )


# --- mesh headers -----------------------------------------------------------------------


def _read_head(path: Path, size: int = 4096) -> str:
    gz = path.with_name(path.name + ".gz")
    if path.is_file():
        with path.open("rb") as fh:
            data = fh.read(size)
    elif gz.is_file():
        with gzip.open(gz, "rb") as fh:
            data = fh.read(size)
    else:
        raise StudyError(f"{path} not found")
    return data.decode("latin-1")


def cell_count(case: Path) -> int:
    """nCells from the note in the header of constant/polyMesh/owner (ascii or binary)."""
    owner = case / "constant" / "polyMesh" / "owner"
    match = re.search(r"nCells:\s*(\d+)", _read_head(owner))
    if match is None:
        raise StudyError(f"{owner}: no nCells note in the header")
    return int(match.group(1))


def _strip_comments(text: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)


def _patches(case: Path) -> dict[str, tuple[str, int | None]]:
    """Patch name to (type, nFaces), from constant/polyMesh/boundary."""
    boundary = case / "constant" / "polyMesh" / "boundary"
    text = _strip_comments(_read_head(boundary, 1 << 20))
    patches: dict[str, tuple[str, int | None]] = {}
    for name, body in re.findall(r"([^\s{};()]+)\s*\{([^{}]*)\}", text):
        match = re.search(r"\btype\s+([^\s;]+)\s*;", body)
        if match and name != "FoamFile":
            faces = re.search(r"\bnFaces\s+(\d+)\s*;", body)
            patches[name] = (match.group(1), None if faces is None else int(faces.group(1)))
    return patches


def patch_types(case: Path) -> dict[str, str]:
    """Patch name to type, from constant/polyMesh/boundary."""
    return {name: kind for name, (kind, _) in _patches(case).items()}


def patch_faces(case: Path) -> dict[str, int]:
    """Patch name to its number of faces, from constant/polyMesh/boundary."""
    return {name: n for name, (_, n) in _patches(case).items() if n is not None}


# --- function-object tables -------------------------------------------------------------


def _start_time(path: Path) -> float:
    try:
        return float(path.parent.name)
    except ValueError:
        return math.inf


def _column_index(header: list[str], column: str | int | None, path: Path) -> int:
    if column is None:
        raise StudyError(f"{path}: no column given")
    if isinstance(column, int):
        if column < 0 or (header and column >= len(header)):
            raise StudyError(f"{path}: column {column} is out of range")
        return column
    if column not in header:
        listed = ", ".join(header) if header else "none"
        raise StudyError(f"{path}: no column {column!r} (header columns: {listed})")
    return header.index(column)


def _value(token: str, component: int | None, path: Path, line: int) -> float:
    if token.startswith("("):
        parts = token[1:-1].split()
        if component is None:
            raise StudyError(f"{path}:{line}: the column holds vectors; set component")
        if component >= len(parts):
            raise StudyError(f"{path}:{line}: component {component} out of range")
        token = parts[component]
    elif component is not None:
        raise StudyError(f"{path}:{line}: component is set but the column holds scalars")
    try:
        return float(token)
    except ValueError as exc:
        raise StudyError(f"{path}:{line}: {token!r} is not a number") from exc


def _read_table(path: Path, qoi: QoI) -> tuple[list[float], list[float]]:
    header: list[str] = []
    xs: list[float] = []
    ys: list[float] = []
    index: int | None = None
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            header = stripped.lstrip("#").split()
            continue
        if index is None:
            index = _column_index(header, qoi.column, path)
            if index == 0:
                raise StudyError(f"{path}: column 0 is the time or iteration column")
        tokens = _TOKEN.findall(stripped)
        if index >= len(tokens):
            raise StudyError(f"{path}:{n}: only {len(tokens)} columns")
        xs.append(_value(tokens[0], None, path, n))
        ys.append(_value(tokens[index], qoi.component, path, n))
    return xs, ys


def read_series(case: Path, qoi: QoI) -> Series:
    """The QoI column from every file matching qoi.file, joined in start-time order.

    A restart writes a new folder under postProcessing/<name>/<startTime>/; rows that a later
    file covers again are taken from the later file.
    """
    case = case.resolve()
    files = sorted(
        (_inside(p, case, "qoi file") for p in case.glob(qoi.file) if p.is_file()),
        key=lambda p: (_start_time(p), str(p)),
    )
    if not files:
        raise StudyError(f"{case}: no file matches {qoi.file!r} for qoi {qoi.name}")
    xs: list[float] = []
    ys: list[float] = []
    for path in files:
        fx, fy = _read_table(path, qoi)
        if fx:
            while xs and xs[-1] >= fx[0]:
                xs.pop()
                ys.pop()
        xs.extend(fx)
        ys.extend(fy)
    if not ys:
        raise StudyError(f"{case}: {qoi.file!r} has no data rows for qoi {qoi.name}")
    return Series(tuple(xs), tuple(ys), tuple(str(p.relative_to(case)) for p in files))


def reduce_series(series: Series, qoi: QoI) -> tuple[float, int, str | None]:
    """(value, samples used, note). window_mean averages the last window of samples."""
    n = len(series.y)
    if qoi.reduction == "last":
        return qoi.scale * series.y[-1], 1, None
    want = max(math.ceil(qoi.window * n), qoi.min_samples)
    note = None
    if want > n:
        note = f"window_mean wanted {want} samples but the series has {n}; all were used"
        want = n
    window = series.y[-want:]
    return qoi.scale * math.fsum(window) / want, want, note


@dataclass(frozen=True)
class Profile:
    """Values along a line or a surface at one time: coordinates along the axis, sorted."""

    coords: tuple[float, ...]
    values: tuple[float, ...]
    time: float
    file: str


def _profile_row(path: Path, coords: dict[int, float], n: int, row: str, qoi: QoI) -> Profile:
    tokens = _TOKEN.findall(row)
    if len(tokens) - 1 != len(coords):
        raise StudyError(f"{path}:{n}: {len(tokens) - 1} values for {len(coords)} probes")
    points = sorted(
        (coords[i], _value(tok, qoi.component, path, n)) for i, tok in enumerate(tokens[1:])
    )
    if len({c for c, _ in points}) != len(points):
        raise StudyError(f"{path}: two probes share a coordinate along the profile axis")
    return Profile(
        coords=tuple(c for c, _ in points),
        values=tuple(v for _, v in points),
        time=_value(tokens[0], None, path, n),
        file=str(path),
    )


def _read_raw(path: Path, qoi: QoI) -> Profile:
    """A raw surface file (surfaceFormat raw): x y z and the field's components, per face.

    Its folder name is its time. Faces may share a coordinate along the axis (a wall across
    it, say): they are kept, in the order written.
    """
    axis = qoi.axis if qoi.axis is not None else 0
    time = _start_time(path)
    if not math.isfinite(time):
        raise StudyError(
            f"{path}: a raw surface file's folder is its time, not {path.parent.name!r}"
        )
    width: int | None = None
    points: list[tuple[float, float]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if width is None:
            width = len(parts) - 3
            if width < 1:
                raise StudyError(f"{path}:{n}: expected x y z and the field's values")
            if (width > 1) != (qoi.component is not None):
                need = "set component" if width > 1 else "component is set but it is a scalar"
                raise StudyError(f"{path}: the field has {width} component(s); {need}")
            if qoi.component is not None and qoi.component >= width:
                raise StudyError(f"{path}: component {qoi.component} out of range")
        if len(parts) != width + 3:
            raise StudyError(f"{path}:{n}: {len(parts)} columns, expected {width + 3}")
        try:
            points.append((float(parts[axis]), float(parts[3 + (qoi.component or 0)])))
        except ValueError as exc:
            raise StudyError(f"{path}:{n}: not a number") from exc
    if not points:
        raise StudyError(f"{path}: no data rows")
    points.sort(key=lambda p: p[0])
    return Profile(
        coords=tuple(c for c, _ in points),
        values=tuple(v for _, v in points),
        time=time,
        file=str(path),
    )


def _read_profiles(path: Path, qoi: QoI, *, last_only: bool = False) -> list[Profile]:
    if path.suffix == ".raw":
        return [_read_raw(path, qoi)]
    axis = qoi.axis if qoi.axis is not None else 0
    coords: dict[int, float] = {}
    rows: list[tuple[int, str]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        match = _PROBE.match(stripped)
        if match:
            parts = match.group(2).split()
            if axis >= len(parts):
                raise StudyError(f"{path}:{n}: probe location has no axis {axis}")
            coords[int(match.group(1))] = float(parts[axis])
        elif stripped and not stripped.startswith("#"):
            if last_only:
                rows.clear()
            rows.append((n, stripped))
    if not coords:
        raise StudyError(f"{path}: no '# Probe i (x y z)' lines: not a probes file")
    if not rows:
        raise StudyError(f"{path}: no data rows")
    return [_profile_row(path, coords, n, row, qoi) for n, row in rows]


def _profile_files(case: Path, qoi: QoI) -> list[Path]:
    files = sorted(
        (_inside(p, case, "qoi file") for p in case.glob(qoi.file) if p.is_file()),
        key=lambda p: (_start_time(p), str(p)),
    )
    if not files:
        raise StudyError(f"{case}: no file matches {qoi.file!r} for qoi {qoi.name}")
    return files


def read_profile(case: Path, qoi: QoI) -> Profile:
    """The last row of the latest file matching qoi.file: of a probes file, or a raw surface."""
    case = case.resolve()
    latest = _profile_files(case, qoi)[-1]
    (profile,) = _read_profiles(latest, qoi, last_only=True)
    return replace(profile, file=str(latest.relative_to(case)))


def read_profiles(case: Path, qoi: QoI) -> tuple[Profile, ...]:
    """Every row of every file matching qoi.file, joined in start-time order.

    As in read_series, rows that a later (restart) file covers again come from that file.
    """
    case = case.resolve()
    profiles: list[Profile] = []
    for path in _profile_files(case, qoi):
        rows = [replace(p, file=str(path.relative_to(case))) for p in _read_profiles(path, qoi)]
        while profiles and profiles[-1].time >= rows[0].time:
            profiles.pop()
        profiles.extend(rows)
    return tuple(profiles)


def profile_extremum(profile: Profile, kind: str) -> tuple[float, float, str | None]:
    """(value, location, note): the parabola through the discrete extremum and its neighbours.

    At the end of the profile there is no neighbour on one side, so the probe value itself is
    returned with a note.
    """
    if kind not in EXTREMA:
        raise ValueError(f"kind must be min or max, got {kind!r}")
    x, y = profile.coords, profile.values
    pick = min if kind == "min" else max
    i = pick(range(len(y)), key=y.__getitem__)
    if i == 0 or i == len(y) - 1:
        note = f"profile {kind} is at the end of the sampled line; no parabola fit"
        return y[i], x[i], note
    x0, x1, x2 = x[i - 1], x[i], x[i + 1]
    y0, y1, y2 = y[i - 1], y[i], y[i + 1]
    d01 = (y1 - y0) / (x1 - x0)
    a = ((y2 - y1) / (x2 - x1) - d01) / (x2 - x0)
    if a == 0:
        return y1, x1, f"profile {kind}: three collinear probes, no parabola fit"
    # y = y0 + d01 (s - x0) + a (s - x0)(s - x1); vertex where dy/ds = 0
    s = 0.5 * (x0 + x1) - d01 / (2.0 * a)
    return y0 + d01 * (s - x0) + a * (s - x0) * (s - x1), s, None


def profile_crossing(profile: Profile, kind: str) -> float | None:
    """Where the values change sign along the axis, first or last; None if they never do.

    The crossing is interpolated linearly between the two points that bracket it. Values of
    exactly zero are passed over, so a sign change through a zero is found between its
    neighbours.
    """
    if kind not in CROSSINGS:
        raise ValueError(f"kind must be first_crossing or last_crossing, got {kind!r}")
    points = [(c, v) for c, v in zip(profile.coords, profile.values, strict=True) if v]
    found = [
        x0 + (x1 - x0) * y0 / (y0 - y1)
        for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False)
        if (y0 < 0) != (y1 < 0)
    ]
    if not found:
        return None
    return found[0] if kind == "first_crossing" else found[-1]


def _qoi_value(
    case: Path, qoi: QoI, axis_names: str = "xyz"
) -> tuple[float, int, list[str], Series]:
    """(value, samples used, notes, history): the history is scaled like the value."""
    if qoi.profile is None:
        series = read_series(case, qoi)
        value, used, note = reduce_series(series, qoi)
        history = replace(series, y=tuple(qoi.scale * v for v in series.y))
        return value, used, [] if note is None else [note], history
    kind = qoi.profile
    profiles = read_profiles(case, qoi)
    profile = profiles[-1]
    axis = axis_names[qoi.axis if qoi.axis is not None else 0]
    files = tuple(dict.fromkeys(p.file for p in profiles))
    if kind in CROSSINGS:
        positions: list[float] = []
        for p in profiles:
            where = profile_crossing(p, kind)
            if where is None:
                raise StudyError(
                    f"qoi {qoi.name}: {p.file} (t = {p.time:g}): the values never change sign"
                )
            positions.append(where)
        notes = [f"{kind.replace('_', ' ')} at {axis} = {positions[-1]:.6g} (t = {profile.time:g})"]
        history = Series(
            x=tuple(p.time for p in profiles),
            y=tuple(qoi.scale * v for v in positions),
            files=files,
        )
        return qoi.scale * positions[-1], len(profile.values), notes, history
    if len(set(profile.coords)) != len(profile.coords):
        raise StudyError(
            f"qoi {qoi.name}: {profile.file}: points share a coordinate along {axis}, so the "
            f"profile {kind} cannot be fitted"
        )
    value, where, note = profile_extremum(profile, kind)
    notes = [f"{kind} at {axis} = {where:.6g} (t = {profile.time:g})"]
    if note:
        notes.append(note)
    history = Series(
        x=tuple(p.time for p in profiles),
        y=tuple(qoi.scale * profile_extremum(p, kind)[0] for p in profiles),
        files=files,
    )
    return qoi.scale * value, len(profile.values), notes, history


def _iterative(history: Series, qoi: QoI, level: str) -> IterativeResult:
    try:
        return iterative_convergence(history.y, history.x, options=iterative_options(qoi))
    except ValueError as exc:
        raise StudyError(f"qoi {qoi.name}, level {level}: {exc}") from exc


# --- the study --------------------------------------------------------------------------


def _listing(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _dimension_checks(
    study: Study, infos: list[LevelInfo], faces: list[dict[str, int]]
) -> tuple[list[str], list[str]]:
    """(warnings, notes): the refined directions d against the patches of every level."""
    warnings: list[str] = []
    notes: list[str] = []
    two_d = any(info.two_d_patches for info in infos)
    # Patches with one face per cell on every level, such as the two halves of a cyclic: the
    # mesh is one cell across them, so that direction was not refined.
    thin = sorted(
        name
        for name in faces[0]
        if all(f.get(name) == info.cells for f, info in zip(faces, infos, strict=True))
    )
    one_cell = (
        f"patches {_listing(thin)} have one face per cell on every level, so the mesh is one "
        "cell across them and that direction is not refined"
        if len(thin) >= 2
        else ""
    )
    if two_d and study.dim == 3:
        warnings.append(
            "dim = 3 but the mesh has empty or wedge patches, which make a case 2-D; check dim"
        )
    if study.dim == 3 and not two_d and one_cell:
        warnings.append(f"dim = 3 but {one_cell}; check dim")
    if study.dim == 2 and not two_d:
        if one_cell:
            notes.append(f"dim = 2 with no empty or wedge patches: {one_cell}")
        else:
            warnings.append(
                "dim = 2 with no empty or wedge patches: assumed one cell across a cyclic or "
                "symmetric direction that was not refined; check that this holds on every level"
            )
    if len({info.two_d_patches for info in infos}) > 1:
        warnings.append("the levels have different empty or wedge patches")
    return warnings, notes


def assess_study(study: Study) -> StudyResult:
    """Cell counts, QoI values, and the grid and iterative convergence of each QoI."""
    infos: list[LevelInfo] = []
    faces: list[dict[str, int]] = []
    for lv in study.levels:
        patches = _patches(lv.path)
        two_d = tuple(sorted(name for name, (t, _) in patches.items() if t in _TWO_D_PATCHES))
        infos.append(
            LevelInfo(
                name=lv.name,
                path=str(lv.path.relative_to(study.root)),
                cells=cell_count(lv.path),
                two_d_patches=two_d,
                first_layer_height=lv.first_layer_height,
            )
        )
        faces.append({name: n for name, (_, n) in patches.items() if n is not None})
    cells = [info.cells for info in infos]
    if any(a <= b for a, b in zip(cells, cells[1:], strict=False)):
        listing = ", ".join(f"{i.name}: {i.cells}" for i in infos)
        raise StudyError(f"levels must be listed finest first with falling cell counts ({listing})")
    warnings, study_notes = _dimension_checks(study, infos, faces)

    options = gci_options(study)
    names = [lv.name for lv in study.levels]
    results: list[QoIResult] = []
    for qoi in study.qois:
        values: list[float] = []
        samples: list[int] = []
        notes: list[str] = []
        histories: list[IterativeResult] = []
        for lv in study.levels:
            value, used, level_notes, history = _qoi_value(lv.path, qoi)
            values.append(value)
            samples.append(used)
            notes.extend(f"level {lv.name}: {note}" for note in level_notes)
            histories.append(_iterative(history, qoi, lv.name))
        if study.scope is Scope.BOUNDARY_LAYER:
            heights = [lv.first_layer_height for lv in study.levels]
            gci = grid_convergence(
                values,
                h=[h for h in heights if h is not None],
                scope=study.scope,
                grid_sequence=study.grid_sequence,
                options=options,
            )
        else:
            gci = grid_convergence(
                values,
                cells=cells,
                dim=study.dim,
                scope=study.scope,
                grid_sequence=study.grid_sequence,
                layer_cells=study.layer_cells,
                options=options,
            )
        # The headline result comes from the finest triplet, or both grids of a two-grid study.
        contamination = check_contamination(
            histories, gci.uncertainty, names=names, used=min(3, len(names))
        )
        results.append(
            QoIResult(
                qoi.name,
                tuple(values),
                tuple(samples),
                tuple(notes),
                gci,
                tuple(histories),
                contamination,
            )
        )

    consistency = settings_consistency(
        [lv.path for lv in study.levels], names=names, scope=study.scope, root=study.root
    )
    return StudyResult(
        name=study.name,
        root=str(study.root),
        dim=study.dim,
        scope=study.scope,
        grid_sequence=study.grid_sequence,
        levels=tuple(infos),
        qois=tuple(results),
        warnings=tuple(warnings),
        consistency=consistency,
        notes=tuple(study_notes),
    )


def compare_references(study: Study, result: StudyResult) -> tuple[QoIComparison, ...]:
    """Each reference in study.toml against its QoI's finest-grid value and U.

    result must be assess_study(study). A comparison is no part of the verification verdict: it
    says how far the value is from the reference, not whether the value is converged.
    """
    by_name = {q.name: q for q in result.qois}
    return tuple(
        QoIComparison(
            ref.qoi,
            compare_result(
                by_name[ref.qoi].gci,
                ref.reference,
                input_uncertainty=ref.input_uncertainty,
                c=ref.c,
            ),
        )
        for ref in study.references
    )
