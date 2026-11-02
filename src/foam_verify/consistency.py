"""Settings consistency: do the levels of a grid study differ only in the mesh?

A grid study attributes the change in a QoI to the mesh. If the levels also differ in a
scheme, a solver setting, a physical property or a boundary condition, part of that change
comes from the setting, and the GCI measures both. settings_consistency() reads the same
files on every level and compares them entry by entry, so a difference names the file and
the key:

- system/fvSchemes and system/fvSolution, and fvOptions, fvModels and fvConstraints;
- every dictionary directly under constant/ (transport and thermophysical properties, the
  turbulence model, g, ...), except mesh-generation dictionaries;
- every field file directly under 0/ (the initial and boundary conditions);
- system/controlDict: a different application blocks; any other difference (a time step
  that shrinks with the mesh, say) is reported as a note;
- the near-wall layer settings in system/snappyHexMeshDict, checked against the refinement
  scope the study claims (see docs/consistency.md).

Values are compared by meaning, not text: 1e-3 equals 0.001, on equals true, the order of
entries does not matter, and $macros and #include files are expanded. Field values that
depend on the mesh (nonuniform lists) are compared by kind only. Any other difference
blocks the clean pass. docs/consistency.md records each rule and its reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import access
from .foamdict import (
    DEFAULT_MAX_BYTES,
    Entry,
    FoamDict,
    FoamDictError,
    canonical,
    display,
    flatten,
    read_dict,
    skipped,
    switch,
)
from .gci import Scope

SOLVER_FILES = (
    "system/fvSchemes",
    "system/fvSolution",
    "system/fvOptions",
    "system/fvModels",
    "system/fvConstraints",
)
CONTROL = "system/controlDict"
SNAPPY = "system/snappyHexMeshDict"
# controlDict entries that must match; the others are reported as notes.
CONTROL_KEYS = frozenset({"application"})
# Mesh generation, not solver settings: never compared as such.
MESH_DICTS = frozenset(
    {
        "blockMeshDict",
        "snappyHexMeshDict",
        "extrudeMeshDict",
        "refineMeshDict",
        "topoSetDict",
        "surfaceFeatureExtractDict",
        "surfaceFeaturesDict",
        "createPatchDict",
        "mirrorMeshDict",
        "meshQualityDict",
        "decomposeParDict",
    }
)
_BACKUPS = ("~", ".orig", ".bak", ".backup", ".old", ".swp")
_UNFOLLOWED = ("#include ", "#includeIfPresent ", "#sinclude ")
_LAYERS = ("addLayers", "addLayersControls")
_CORE_MESH = ("castellatedMeshControls", "snapControls")


@dataclass(frozen=True)
class Difference:
    """One entry that is not the same on every level.

    key is the entry's path of keywords joined with '/', or "" when the file itself is
    missing on some levels. values are as written on each level, finest first; None where
    the entry or file is absent.
    """

    file: str
    key: str
    values: tuple[str | None, ...]
    blocking: bool


@dataclass(frozen=True)
class ConsistencyResult:
    clean_pass: bool
    levels: tuple[str, ...]
    files: tuple[str, ...]
    differences: tuple[Difference, ...]
    warnings: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _settings_files(case: Path) -> dict[str, Path]:
    """The files compared in one case, by their path relative to it (without .gz)."""
    found: dict[str, Path] = {}
    for rel in (*SOLVER_FILES, CONTROL, SNAPPY):
        for path in (case / rel, case / f"{rel}.gz"):
            if path.is_file():
                found[rel] = path
                break
    for sub in ("constant", "0"):
        folder = case / sub
        if not folder.is_dir():
            continue
        access.checked(folder)  # inside a sandbox, a folder listed must lie under its roots
        for path in sorted(folder.iterdir()):
            name = path.name.removesuffix(".gz")
            if (
                path.is_file()
                and not name.startswith(".")
                and not name.endswith(_BACKUPS)
                and name not in MESH_DICTS
            ):
                found.setdefault(f"{sub}/{name}", path)
    return found


def _file_order(found: Sequence[dict[str, Path]]) -> list[str]:
    names = {rel for f in found for rel in f}
    fixed = [rel for rel in SOLVER_FILES if rel in names]
    physics = sorted(rel for rel in names if rel.startswith("constant/"))
    fields = sorted(rel for rel in names if rel.startswith("0/"))
    return fixed + physics + fields + [rel for rel in (CONTROL, SNAPPY) if rel in names]


def _levels(labels: Sequence[str], mask: Sequence[bool]) -> str:
    return ", ".join(label for label, keep in zip(labels, mask, strict=True) if keep)


def _presence(rel: str, labels: Sequence[str], present: Sequence[bool]) -> str:
    absent = [not p for p in present]
    return f"{rel}: present on {_levels(labels, present)}; absent on {_levels(labels, absent)}"


def _missing(rel: str, present: Sequence[bool]) -> Difference:
    """A file that exists on some levels only."""
    return Difference(rel, "", tuple("present" if p else None for p in present), True)


def _compare(
    rel: str, docs: Sequence[FoamDict], labels: Sequence[str]
) -> list[tuple[str, tuple[str | None, ...], str]]:
    """(key, values as written, description) for each entry that differs between levels."""
    flats = [flatten(d) for d in docs]
    keys = list(dict.fromkeys(k for f in flats for k in f))
    out: list[tuple[str, tuple[str | None, ...], str]] = []
    for key in keys:
        canon = [canonical(f[key]) if key in f else None for f in flats]
        if len(set(canon)) == 1:
            continue
        shown = tuple(display(f[key]) if key in f else None for f in flats)
        groups: dict[str | None, list[str]] = {}
        first: dict[str | None, str | None] = {}
        for c, s, label in zip(canon, shown, labels, strict=True):
            groups.setdefault(c, []).append(label)
            first.setdefault(c, s)
        parts = "; ".join(
            f"{'(absent)' if first[c] is None else repr(first[c])} on {', '.join(levels)}"
            for c, levels in groups.items()
        )
        out.append((key, shown, f"{rel}: {key}: {parts}"))
    return out


def _subset(d: FoamDict, keys: Sequence[str]) -> FoamDict:
    return FoamDict({k: d[k] for k in keys if k in d})


def _get(d: FoamDict, *path: str) -> Entry | None:
    entry: Entry | None = d
    for key in path:
        if not isinstance(entry, FoamDict):
            return None
        entry = entry.get(key)
    return entry


def _layer_check(
    labels: Sequence[str], docs: Sequence[FoamDict | None], scope: Scope
) -> tuple[list[Difference], list[str], list[str]]:
    """The near-wall layer settings in snappyHexMeshDict against the refinement scope."""
    diffs: list[Difference] = []
    warnings: list[str] = []
    notes: list[str] = []
    present = [d is not None for d in docs]
    if not any(present):
        if scope is not Scope.MESH:
            notes.append(
                f"no {SNAPPY} on any level: the near-wall layer settings behind refined = "
                f"{scope.value.replace('_', '-')} cannot be checked"
            )
        return diffs, warnings, notes
    if not all(present):
        diffs.append(_missing(SNAPPY, present))
        warnings.append(_presence(SNAPPY, labels, present) + ": the levels were meshed differently")
        return diffs, warnings, notes
    full = [d for d in docs if d is not None]
    found = _compare(SNAPPY, [_subset(d, _LAYERS) for d in full], labels)
    adds = [switch(d.get("addLayers")) for d in full]
    relative = [switch(_get(d, "addLayersControls", "relativeSizes")) for d in full]
    layered = all(a is True for a in adds)
    if scope is Scope.CORE:
        for key, shown, text in found:
            diffs.append(Difference(SNAPPY, key, shown, True))
            warnings.append(f"{text} (refined = core needs the same near-wall layers throughout)")
        if not found and layered and any(r is not False for r in relative):
            warnings.append(
                f"{SNAPPY}: relativeSizes is not false on every level, so the layer thicknesses "
                "scale with the local cell size, and refining the core changes the near-wall "
                "layers unless the surface cells are the same on every level: give absolute "
                "sizes (relativeSizes false) or check the layers"
            )
        elif not any(a is True for a in adds):
            notes.append(f"{SNAPPY}: no level adds near-wall layers")
    elif scope is Scope.MESH:
        for key, shown, text in found:
            diffs.append(Difference(SNAPPY, key, shown, False))
            notes.append(f"{text} (the layers are refined with the mesh)")
        if not found and layered and all(r is False for r in relative):
            warnings.append(
                f"{SNAPPY}: refined = mesh, but every level has the same absolute layer sizes, so "
                "the near-wall layers were not refined: refine them too, or use refined = core "
                "with layer_cells"
            )
    else:
        for key, shown, text in found:
            diffs.append(Difference(SNAPPY, key, shown, False))
            notes.append(f"{text} (the refined layers)")
        if not any(a is True for a in adds):
            warnings.append(f"{SNAPPY}: refined = boundary-layer, but no level adds layers")
        elif not found:
            warnings.append(
                f"{SNAPPY}: refined = boundary-layer, but the layer settings are the same on "
                "every level"
            )
        for key, shown, text in _compare(SNAPPY, [_subset(d, _CORE_MESH) for d in full], labels):
            diffs.append(Difference(SNAPPY, key, shown, True))
            warnings.append(f"{text} (refined = boundary-layer keeps the core mesh the same)")
    return diffs, warnings, notes


def settings_consistency(
    cases: Sequence[str | Path],
    *,
    names: Sequence[str] | None = None,
    scope: Scope = Scope.MESH,
    root: str | Path | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> ConsistencyResult:
    """Compare the settings of the cases of a grid study, finest first.

    names label the levels in messages. scope is what the study says was refined; it decides
    which layer-setting differences are expected. #include is followed, and files are read,
    only inside root: by default each case's own folder.
    """
    paths = [Path(c) for c in cases]
    if len(paths) < 2:
        raise ValueError("a grid study has at least two levels")
    labels = list(names) if names is not None else [str(i + 1) for i in range(len(paths))]
    if len(labels) != len(paths):
        raise ValueError("names must have one entry per case")
    scope = Scope(scope)
    roots = [Path(root).resolve() if root is not None else p.resolve() for p in paths]
    found = [_settings_files(p) for p in paths]

    files: list[str] = []
    diffs: list[Difference] = []
    warnings: list[str] = []
    notes: list[str] = []
    snappy: list[FoamDict | None] = [None] * len(paths)
    for rel in _file_order(found):
        present = [rel in f for f in found]
        docs: list[FoamDict | None] = []
        for label, case, base, f in zip(labels, paths, roots, found, strict=True):
            path = f.get(rel)
            if path is None:
                docs.append(None)
            elif not path.resolve().is_relative_to(base):
                warnings.append(f"{rel} on {label}: links outside {base}; not read")
                docs.append(None)
            else:
                try:
                    docs.append(read_dict(path, case=case, root=base, max_bytes=max_bytes))
                except (FoamDictError, OSError) as exc:
                    warnings.append(f"{rel} on {label}: cannot be read: {exc}")
                    docs.append(None)
        read = [d for d in docs if d is not None]
        if len(read) < sum(present):
            continue  # a warning names the file that could not be read
        if rel.startswith(("constant/", "0/")) and any("FoamFile" not in d for d in read):
            notes.append(f"{rel}: not an OpenFOAM dictionary (no FoamFile header); not compared")
            continue
        for d in read:
            d.pop("FoamFile", None)
        if rel == SNAPPY:
            snappy = docs
            continue
        files.append(rel)
        if not all(present):
            diffs.append(_missing(rel, present))
            warnings.append(_presence(rel, labels, present))
            continue
        for key, shown, text in _compare(rel, read, labels):
            blocking = rel != CONTROL or key.split("/")[0] in CONTROL_KEYS
            diffs.append(Difference(rel, key, shown, blocking))
            (warnings if blocking else notes).append(text)
        flats = [flatten(d) for d in read]
        nonuniform: list[str] = []
        for key in dict.fromkeys(k for f in flats for k in f):
            if all(key in f and skipped(f[key]) for f in flats):
                nonuniform.append(key)
            if any(part.startswith(_UNFOLLOWED) for part in key.split("/")):
                notes.append(
                    f"{rel}: {key}: not followed (the file is missing or outside the folder "
                    "foam-verify may read), so only the directive is compared"
                )
        if nonuniform:
            notes.append(
                f"{rel}: {', '.join(nonuniform)}: nonuniform on every level; the values depend "
                "on the mesh and are compared by kind only"
            )

    if not any(rel in f for f in found for rel in SOLVER_FILES[:2]):
        warnings.append(
            "no system/fvSchemes or system/fvSolution on any level: the discretisation and "
            "solver settings cannot be compared"
        )
    if not any(rel.startswith("0/") for f in found for rel in f):
        notes.append(
            "no 0/ fields on any level: the initial and boundary conditions are not compared"
        )
    layer_diffs, layer_warnings, layer_notes = _layer_check(labels, snappy, scope)
    if any(d is not None for d in snappy):
        files.append(SNAPPY)
    return ConsistencyResult(
        clean_pass=not warnings and not layer_warnings,
        levels=tuple(labels),
        files=tuple(files),
        differences=tuple(diffs + layer_diffs),
        warnings=tuple(warnings + layer_warnings),
        notes=tuple(notes + layer_notes),
    )
