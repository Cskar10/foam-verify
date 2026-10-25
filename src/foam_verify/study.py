"""Grid studies on disk: the study.toml manifest, mesh headers and function-object output.

A study is a folder holding study.toml and one OpenFOAM case per grid level. Everything here
reads; nothing writes, runs a solver or leaves the study folder. Cell counts come from the
note in the header of constant/polyMesh/owner, and quantities of interest from the tables
that function objects write under postProcessing/.

study.toml, levels finest first:

    name = "square-duct"
    dim = 2                    # refined directions
    formal_order = 2           # optional, default 2
    refined = "mesh"           # mesh | core | boundary-layer
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
    window = 0.1               # window_mean: last fraction of samples...
    min_samples = 50           # ...but at least this many
    scale = 1.0                # multiplies the reduced value (unit or non-dimensional factor)
"""

from __future__ import annotations

import gzip
import math
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from .gci import GCIResult, Options, Scope, grid_convergence

MANIFEST = "study.toml"
REDUCTIONS = ("last", "window_mean")
_COMPONENTS = {"x": 0, "y": 1, "z": 2, "0": 0, "1": 1, "2": 2}
_TWO_D_PATCHES = ("empty", "wedge")
_TOKEN = re.compile(r"\([^()]*\)|\S+")


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
    column: str | int
    component: int | None = None
    reduction: str = "last"
    window: float = 0.1
    min_samples: int = 50
    scale: float = 1.0


@dataclass(frozen=True)
class Study:
    root: Path
    name: str
    dim: int
    formal_order: float
    scope: Scope
    layer_cells: float | None
    levels: tuple[Level, ...]
    qois: tuple[QoI, ...]


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


@dataclass(frozen=True)
class StudyResult:
    name: str
    root: str
    dim: int
    scope: Scope
    levels: tuple[LevelInfo, ...]
    qois: tuple[QoIResult, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    allowed = {"name", "file", "column", "component", "reduction", "window", "min_samples", "scale"}
    _check_keys(raw, allowed, where)
    for key in ("name", "file", "column"):
        if key not in raw:
            raise StudyError(f"{where}: {key} is required")
    column = raw["column"]
    if isinstance(column, bool) or not isinstance(column, str | int):
        raise StudyError(f"{where}: column must be a header name or a 0-based index")
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
    )


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
    allowed = {"name", "dim", "formal_order", "refined", "layer_cells", "levels", "qoi"}
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

    return Study(
        root=root.resolve(),
        name=str(raw.get("name", root.resolve().name)),
        dim=dim,
        formal_order=formal_order,
        scope=scope,
        layer_cells=None if layer_cells is None else float(layer_cells),
        levels=levels,
        qois=qois,
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


def patch_types(case: Path) -> dict[str, str]:
    """Patch name to type, from constant/polyMesh/boundary."""
    boundary = case / "constant" / "polyMesh" / "boundary"
    text = _strip_comments(_read_head(boundary, 1 << 20))
    types: dict[str, str] = {}
    for name, body in re.findall(r"([^\s{};()]+)\s*\{([^{}]*)\}", text):
        match = re.search(r"\btype\s+([^\s;]+)\s*;", body)
        if match and name != "FoamFile":
            types[name] = match.group(1)
    return types


# --- function-object tables -------------------------------------------------------------


def _start_time(path: Path) -> float:
    try:
        return float(path.parent.name)
    except ValueError:
        return math.inf


def _column_index(header: list[str], column: str | int, path: Path) -> int:
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


# --- the study --------------------------------------------------------------------------


def assess_study(study: Study) -> StudyResult:
    """Cell counts, QoI values and the grid convergence assessment of each QoI."""
    warnings: list[str] = []
    infos: list[LevelInfo] = []
    for lv in study.levels:
        types = patch_types(lv.path)
        two_d = tuple(sorted(name for name, t in types.items() if t in _TWO_D_PATCHES))
        infos.append(
            LevelInfo(
                name=lv.name,
                path=str(lv.path.relative_to(study.root)),
                cells=cell_count(lv.path),
                two_d_patches=two_d,
                first_layer_height=lv.first_layer_height,
            )
        )
    cells = [info.cells for info in infos]
    if any(a <= b for a, b in zip(cells, cells[1:], strict=False)):
        listing = ", ".join(f"{i.name}: {i.cells}" for i in infos)
        raise StudyError(f"levels must be listed finest first with falling cell counts ({listing})")

    if any(info.two_d_patches for info in infos) and study.dim == 3:
        warnings.append(
            "dim = 3 but the mesh has empty or wedge patches, which make a case 2-D; check dim"
        )
    if study.dim == 2 and not any(info.two_d_patches for info in infos):
        warnings.append(
            "dim = 2 with no empty or wedge patches: assumed one cell across a cyclic or "
            "symmetric direction that was not refined; check that this holds on every level"
        )
    if len({info.two_d_patches for info in infos}) > 1:
        warnings.append("the levels have different empty or wedge patches")

    options = Options(formal_order=study.formal_order)
    results: list[QoIResult] = []
    for qoi in study.qois:
        values: list[float] = []
        samples: list[int] = []
        notes: list[str] = []
        for lv in study.levels:
            value, used, note = reduce_series(read_series(lv.path, qoi), qoi)
            values.append(value)
            samples.append(used)
            if note:
                notes.append(f"level {lv.name}: {note}")
        if study.scope is Scope.BOUNDARY_LAYER:
            heights = [lv.first_layer_height for lv in study.levels]
            gci = grid_convergence(
                values, h=[h for h in heights if h is not None], scope=study.scope, options=options
            )
        else:
            gci = grid_convergence(
                values,
                cells=cells,
                dim=study.dim,
                scope=study.scope,
                layer_cells=study.layer_cells,
                options=options,
            )
        results.append(QoIResult(qoi.name, tuple(values), tuple(samples), tuple(notes), gci))

    return StudyResult(
        name=study.name,
        root=str(study.root),
        dim=study.dim,
        scope=study.scope,
        levels=tuple(infos),
        qois=tuple(results),
        warnings=tuple(warnings),
    )
