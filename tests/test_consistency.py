"""Settings consistency across the levels of a grid study."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from foam_verify.consistency import ConsistencyResult, settings_consistency
from foam_verify.gci import Scope


def header(cls: str, obj: str) -> str:
    return f"FoamFile {{ version 2.0; format ascii; class {cls}; object {obj}; }}\n"


FILES = {
    "system/fvSchemes": header("dictionary", "fvSchemes")
    + """
ddtSchemes      { default Euler; }
gradSchemes     { default Gauss linear; }
divSchemes      { default none; div(phi,U) Gauss linear; }
laplacianSchemes { default Gauss linear corrected; }
""",
    "system/fvSolution": header("dictionary", "fvSolution")
    + """
solvers
{
    p       { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0.05; }
    pFinal  { $p; relTol 0; }
    U       { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-05; relTol 0; }
}
PISO            { nCorrectors 2; nNonOrthogonalCorrectors 0; momentumPredictor yes; }
""",
    "system/controlDict": header("dictionary", "controlDict")
    + "application icoFoam;\nendTime 10;\ndeltaT 0.005;\nwriteControl runTime;\n",
    "system/blockMeshDict": header("dictionary", "blockMeshDict") + "cells (20 20 1);\n",
    "constant/transportProperties": header("dictionary", "transportProperties") + "nu 0.001;\n",
    "0/U": header("volVectorField", "U")
    + """
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    lid             { type fixedValue; value uniform (1 0 0); }
    walls           { type noSlip; }
    frontAndBack    { type empty; }
}
""",
    "0/p": header("volScalarField", "p")
    + """
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{
    lid             { type zeroGradient; }
    walls           { type zeroGradient; }
    frontAndBack    { type empty; }
}
""",
}
NAMES = ("fine", "medium", "coarse")


def make_cases(
    root: Path, edits: Mapping[str, Mapping[str, str | None]] | None = None
) -> list[Path]:
    """Three cases with FILES; edits[level][file] replaces a file's text, or removes it."""
    cases: list[Path] = []
    for name in NAMES:
        files: dict[str, str | None] = dict(FILES)
        files.update((edits or {}).get(name, {}))
        case = root / name
        for rel, text in files.items():
            if text is not None:
                path = case / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        cases.append(case)
    return cases


def check(
    root: Path,
    edits: Mapping[str, Mapping[str, str | None]] | None = None,
    scope: Scope = Scope.MESH,
) -> ConsistencyResult:
    return settings_consistency(make_cases(root, edits), names=NAMES, scope=scope, root=root)


def edit(rel: str, old: str, new: str) -> str:
    text = FILES[rel]
    assert old in text
    return text.replace(old, new)


# --- the settings files ----------------------------------------------------------------------


def test_identical_levels_pass_and_list_what_was_compared(tmp_path: Path) -> None:
    res = check(tmp_path)
    assert res.clean_pass, res.warnings
    assert res.levels == NAMES
    assert res.files == (
        "system/fvSchemes",
        "system/fvSolution",
        "constant/transportProperties",
        "0/U",
        "0/p",
        "system/controlDict",
    )
    assert res.differences == () and res.warnings == () and res.notes == ()
    assert res.to_dict()["clean_pass"] is True


def test_a_different_scheme_is_named_by_key_and_level(tmp_path: Path) -> None:
    scheme = edit("system/fvSchemes", "div(phi,U) Gauss linear", "div(phi,U) Gauss upwind")
    res = check(tmp_path, {"coarse": {"system/fvSchemes": scheme}})
    assert not res.clean_pass
    (diff,) = res.differences
    assert (diff.file, diff.key, diff.blocking) == (
        "system/fvSchemes",
        "divSchemes/div(phi,U)",
        True,
    )
    assert diff.values == ("Gauss linear", "Gauss linear", "Gauss upwind")
    assert res.warnings == (
        "system/fvSchemes: divSchemes/div(phi,U): 'Gauss linear' on fine, medium; "
        "'Gauss upwind' on coarse",
    )


@pytest.mark.parametrize(
    ("rel", "old", "new"),
    [
        ("constant/transportProperties", "nu 0.001;", "nu 1e-3;"),
        (
            "system/fvSolution",
            "pFinal  { $p; relTol 0; }",
            "pFinal { relTol 0; solver PCG; preconditioner DIC; tolerance 1e-6; }",
        ),
        ("system/fvSolution", "momentumPredictor yes;", "momentumPredictor true;"),
        ("0/U", "walls           { type noSlip; }", "walls { type   noSlip ; }"),
    ],
)
def test_the_same_setting_spelled_differently_passes(
    tmp_path: Path, rel: str, old: str, new: str
) -> None:
    assert check(tmp_path, {"medium": {rel: edit(rel, old, new)}}).clean_pass


def test_physics_and_boundary_conditions_are_compared(tmp_path: Path) -> None:
    res = check(
        tmp_path,
        {
            "fine": {
                "constant/transportProperties": edit(
                    "constant/transportProperties", "0.001", "0.01"
                )
            },
            "coarse": {"0/U": edit("0/U", "uniform (1 0 0)", "uniform (1.01 0 0)")},
        },
    )
    assert [(d.file, d.key) for d in res.differences] == [
        ("constant/transportProperties", "nu"),
        ("0/U", "boundaryField/lid/value"),
    ]
    assert all(d.blocking for d in res.differences) and not res.clean_pass


def test_a_file_on_some_levels_only_blocks(tmp_path: Path) -> None:
    nut = (
        header("volScalarField", "nut") + "dimensions [0 2 -1 0 0 0 0];\ninternalField uniform 0;\n"
    )
    res = check(tmp_path, {"fine": {"0/nut": nut}, "coarse": {"system/fvSolution": None}})
    assert not res.clean_pass
    assert "system/fvSolution: present on fine, medium; absent on coarse" in res.warnings
    assert "0/nut: present on fine; absent on medium, coarse" in res.warnings
    assert {(d.file, d.values) for d in res.differences} == {
        ("system/fvSolution", ("present", "present", None)),
        ("0/nut", ("present", None, None)),
    }


def test_controldict_blocks_only_on_the_application(tmp_path: Path) -> None:
    rel = "system/controlDict"
    res = check(
        tmp_path,
        {
            "medium": {rel: edit(rel, "deltaT 0.005", "deltaT 0.01")},
            "coarse": {rel: edit(rel, "deltaT 0.005", "deltaT 0.02")},
        },
    )
    assert res.clean_pass
    assert res.notes == (
        "system/controlDict: deltaT: '0.005' on fine; '0.01' on medium; '0.02' on coarse",
    )
    res = check(tmp_path / "app", {"coarse": {rel: edit(rel, "icoFoam", "pisoFoam")}})
    assert not res.clean_pass
    assert res.warnings == (
        "system/controlDict: application: 'icoFoam' on fine, medium; 'pisoFoam' on coarse",
    )


def test_nonuniform_fields_compare_by_kind(tmp_path: Path) -> None:
    def field(n: int) -> str:
        values = " ".join(str(0.1 * i) for i in range(n))
        return edit(
            "0/p",
            "internalField   uniform 0;",
            f"internalField nonuniform List<scalar> {n}({values});",
        )

    res = check(
        tmp_path,
        {"fine": {"0/p": field(16)}, "medium": {"0/p": field(8)}, "coarse": {"0/p": field(4)}},
    )
    assert res.clean_pass, res.warnings
    assert any("0/p: internalField: nonuniform on every level" in n for n in res.notes)
    res = check(tmp_path / "mixed", {"fine": {"0/p": field(16)}})
    assert not res.clean_pass
    (diff,) = res.differences
    assert diff.values == ("nonuniform List<scalar> 16(...)", "uniform 0", "uniform 0")


def test_includes_inside_the_study_are_compared_through(tmp_path: Path) -> None:
    including = edit(
        "0/U",
        "internalField   uniform (0 0 0);",
        '#include "../../common/initial"\ninternalField uniform $U0;',
    )
    common = tmp_path / "common" / "initial"
    common.parent.mkdir()
    common.write_text("U0 (0 0 0);\n")
    res = check(tmp_path, {name: {"0/U": including} for name in NAMES})
    assert res.clean_pass, res.warnings
    assert res.notes == ()
    # Each case read on its own cannot see the shared file: the directive is compared instead.
    alone = settings_consistency(make_cases(tmp_path, {name: {"0/U": including} for name in NAMES}))
    assert alone.clean_pass
    assert any('#include "../../common/initial"' in n and "not followed" in n for n in alone.notes)


def test_unreadable_and_foreign_files(tmp_path: Path) -> None:
    res = check(
        tmp_path,
        {
            "medium": {"system/fvSolution": "solvers { p { solver PCG; }\n"},
            "fine": {"constant/README": "notes about the case"},
            "coarse": {"constant/README": "notes about the case"},
        },
    )
    assert not res.clean_pass
    (warning,) = res.warnings
    assert warning.startswith("system/fvSolution on medium: cannot be read:")
    assert "fvSolution:2: end of file inside a dictionary" in warning
    assert (
        "constant/README: not an OpenFOAM dictionary (no FoamFile header); not compared"
        in res.notes
    )


def test_backups_and_mesh_generation_files_are_not_compared(tmp_path: Path) -> None:
    res = check(
        tmp_path,
        {
            "fine": {
                "system/blockMeshDict": edit("system/blockMeshDict", "20 20", "80 80"),
                "0/U.orig": "anything",
                "constant/transportProperties~": "anything",
            },
        },
    )
    assert res.clean_pass, res.warnings
    assert "system/blockMeshDict" not in res.files and "0/U.orig" not in res.files


def test_no_solver_settings_cannot_pass(tmp_path: Path) -> None:
    gone: dict[str, str | None] = {"system/fvSchemes": None, "system/fvSolution": None}
    res = check(tmp_path, {name: gone for name in NAMES})
    assert not res.clean_pass
    assert res.warnings[0].startswith("no system/fvSchemes or system/fvSolution on any level")


def test_a_file_linking_outside_the_root_is_not_read(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text(FILES["constant/transportProperties"])
    cases = make_cases(tmp_path / "study")
    for case in cases:
        target = case / "constant" / "transportProperties"
        target.unlink()
        target.symlink_to(secret)
    res = settings_consistency(cases, names=NAMES, root=tmp_path / "study")
    assert not res.clean_pass
    assert any("links outside" in w for w in res.warnings)


@pytest.mark.parametrize(
    ("cases", "names", "message"),
    [(["a"], None, "at least two"), (["a", "b"], ["x"], "one entry per case")],
)
def test_arguments_are_checked(cases: list[str], names: list[str] | None, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        settings_consistency(cases, names=names)


# --- near-wall layers against the refinement scope ----------------------------------------------


def snappy(level: int = 2, layers: int = 3, relative: str = "false", add: str = "true") -> str:
    return (
        header("dictionary", "snappyHexMeshDict")
        + f"""
castellatedMesh true;
snap            true;
addLayers       {add};
castellatedMeshControls
{{
    maxGlobalCells  2000000;
    refinementSurfaces {{ wall {{ level ({level} {level}); }} }}
}}
snapControls    {{ nSmoothPatch 3; tolerance 2.0; }}
addLayersControls
{{
    relativeSizes       {relative};
    layers              {{ wall {{ nSurfaceLayers {layers}; }} }}
    expansionRatio      1.2;
    firstLayerThickness 1e-4;
    minThickness        1e-5;
}}
"""
    )


def levels(**per_level: str) -> dict[str, dict[str, str | None]]:
    return {name: {"system/snappyHexMeshDict": text} for name, text in per_level.items()}


def test_core_scope_needs_the_same_absolute_layers(tmp_path: Path) -> None:
    # The core is refined (the surface level changes); the layers are fixed in metres.
    same = levels(fine=snappy(level=4), medium=snappy(level=3), coarse=snappy(level=2))
    res = check(tmp_path / "same", same, Scope.CORE)
    assert res.clean_pass, res.warnings
    assert "system/snappyHexMeshDict" in res.files

    fewer = levels(fine=snappy(level=4), medium=snappy(level=3), coarse=snappy(level=2, layers=2))
    res = check(tmp_path / "fewer", fewer, Scope.CORE)
    assert not res.clean_pass
    (diff,) = res.differences
    assert diff.key == "addLayersControls/layers/wall/nSurfaceLayers" and diff.blocking

    relative = levels(**{name: snappy(relative="true") for name in NAMES})
    res = check(tmp_path / "relative", relative, Scope.CORE)
    assert not res.clean_pass
    assert "relativeSizes is not false on every level" in res.warnings[0]


def test_mesh_scope_expects_the_layers_to_be_refined(tmp_path: Path) -> None:
    refined = levels(fine=snappy(layers=6), medium=snappy(layers=4), coarse=snappy(layers=3))
    res = check(tmp_path / "refined", refined, Scope.MESH)
    assert res.clean_pass, res.warnings
    assert all(not d.blocking for d in res.differences) and len(res.notes) == 1

    fixed = levels(**{name: snappy() for name in NAMES})
    res = check(tmp_path / "fixed", fixed, Scope.MESH)
    assert not res.clean_pass
    assert "the near-wall layers were not refined" in res.warnings[0]

    scaled = levels(**{name: snappy(relative="true") for name in NAMES})
    assert check(tmp_path / "scaled", scaled, Scope.MESH).clean_pass


def test_boundary_layer_scope_keeps_the_core_and_refines_the_layers(tmp_path: Path) -> None:
    good = levels(fine=snappy(layers=12), medium=snappy(layers=6), coarse=snappy(layers=3))
    assert check(tmp_path / "good", good, Scope.BOUNDARY_LAYER).clean_pass

    same = levels(**{name: snappy() for name in NAMES})
    res = check(tmp_path / "same", same, Scope.BOUNDARY_LAYER)
    assert "the layer settings are the same on every level" in res.warnings[0]

    core = levels(fine=snappy(level=3, layers=12), medium=snappy(layers=6), coarse=snappy(layers=3))
    res = check(tmp_path / "core", core, Scope.BOUNDARY_LAYER)
    assert not res.clean_pass
    assert [d.key for d in res.differences if d.blocking] == [
        "castellatedMeshControls/refinementSurfaces/wall/level"
    ]

    off = levels(**{name: snappy(add="false") for name in NAMES})
    assert "no level adds layers" in check(tmp_path / "off", off, Scope.BOUNDARY_LAYER).warnings[0]


def test_snappy_on_some_levels_only_and_none_at_all(tmp_path: Path) -> None:
    res = check(tmp_path / "some", levels(fine=snappy(), medium=snappy()), Scope.MESH)
    assert not res.clean_pass
    assert res.warnings[0].endswith("the levels were meshed differently")

    res = check(tmp_path / "none", None, Scope.CORE)
    assert res.clean_pass
    assert res.notes[-1].startswith("no system/snappyHexMeshDict on any level")
