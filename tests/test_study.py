"""study.toml reader, mesh headers and function-object tables."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from foam_verify.gci import Scope, Verdict
from foam_verify.study import (
    QoI,
    StudyError,
    assess_study,
    cell_count,
    load_study,
    patch_types,
    read_series,
    reduce_series,
)

REAL = Path(__file__).parent / "data" / "cavity_v2512"

OWNER = """FoamFile
{{
    version     2.0;
    format      binary;
    note        "nPoints:1  nCells:{cells}  nFaces:1  nInternalFaces:1";
    class       labelList;
    object      owner;
}}
"""

BOUNDARY = """FoamFile
{{
    version 2.0; format ascii; class polyBoundaryMesh; object boundary;
}}
// a comment with a brace {{
2
(
    walls
    {{
        type            wall;
        inGroups        1(wall);
        nFaces          4;
        startFace       0;
    }}
    sides
    {{
        type            {side};
        nFaces          4;
        startFace       4;
    }}
)
"""

TABLE = "# Time        \tareaAverage(p)\n" + "".join(
    f"{i}\t{value}\n" for i, value in enumerate([3.0, 2.0, 1.5, 1.25], start=1)
)


def make_case(root: Path, name: str, cells: int, value: float, side: str = "empty") -> Path:
    case = root / name
    mesh = case / "constant" / "polyMesh"
    mesh.mkdir(parents=True)
    (mesh / "owner").write_text(OWNER.format(cells=cells))
    (mesh / "boundary").write_text(BOUNDARY.format(side=side))
    out = case / "postProcessing" / "avg" / "0"
    out.mkdir(parents=True)
    (out / "surfaceFieldValue.dat").write_text(
        f"# Time\tareaAverage(p)\n1\t{value * 2}\n2\t{value}\n"
    )
    return case


def manifest(levels: list[tuple[str, str]], extra: str = "", qoi: str = "") -> str:
    text = 'name = "demo"\ndim = 2\nrefined = "mesh"\n' + extra
    for name, path in levels:
        text += f'\n[[levels]]\nname = "{name}"\npath = "{path}"\n'
    text += qoi or (
        '\n[[qoi]]\nname = "pavg"\nfile = "postProcessing/avg/*/surfaceFieldValue.dat"\n'
        'column = "areaAverage(p)"\n'
    )
    return text


def phi(h: float) -> float:
    return 1.0 + 0.5 * h**2


@pytest.fixture
def study_dir(tmp_path: Path) -> Path:
    # 2-D levels 80^2, 40^2, 20^2: r = 2, and phi = 1 + 0.5 h^2 recovers p = 2.
    for name, n, h in (("fine", 6400, 0.1), ("medium", 1600, 0.2), ("coarse", 400, 0.4)):
        make_case(tmp_path, name, n, phi(h))
    levels = [("fine", "fine"), ("medium", "medium"), ("coarse", "coarse")]
    (tmp_path / "study.toml").write_text(manifest(levels))
    return tmp_path


# --- real v2512 output ------------------------------------------------------------------


def test_real_owner_header() -> None:
    assert cell_count(REAL) == 400


def test_real_boundary_patch_types() -> None:
    assert patch_types(REAL) == {
        "movingWall": "wall",
        "fixedWalls": "wall",
        "frontAndBack": "empty",
    }


def test_real_surface_field_value_table() -> None:
    qoi = QoI("p", "postProcessing/lidAvg/*/surfaceFieldValue.dat", "areaAverage(p)")
    series = read_series(REAL, qoi)
    assert len(series.y) == 100
    assert series.x[0] == 0.005 and series.x[-1] == 0.5
    assert series.y[-1] == pytest.approx(5.972628e-02)
    assert series.files == ("postProcessing/lidAvg/0/surfaceFieldValue.dat",)


def test_real_probe_vector_component() -> None:
    qoi = QoI("ux", "postProcessing/probes/0/U", "0", component=0)
    assert read_series(REAL, qoi).y[-1] == pytest.approx(-0.196068)
    qoi = QoI("uy1", "postProcessing/probes/0/U", "1", component=1)
    assert read_series(REAL, qoi).y[-1] == pytest.approx(0.312475)


def test_vector_column_needs_a_component() -> None:
    with pytest.raises(StudyError, match="set component"):
        read_series(REAL, QoI("u", "postProcessing/probes/0/U", "0"))


def test_unknown_column_lists_the_header() -> None:
    qoi = QoI("p", "postProcessing/lidAvg/0/surfaceFieldValue.dat", "sum(p)")
    with pytest.raises(StudyError, match=r"areaAverage\(p\)"):
        read_series(REAL, qoi)


# --- the study end to end ---------------------------------------------------------------


def test_assess_recovers_order_and_limit(study_dir: Path) -> None:
    study = load_study(study_dir)
    assert study.scope is Scope.MESH and study.dim == 2 and len(study.levels) == 3
    res = assess_study(study)
    assert [lv.cells for lv in res.levels] == [6400, 1600, 400]
    assert res.levels[0].two_d_patches == ("sides",)
    assert res.warnings == ()
    (qoi,) = res.qois
    assert qoi.values == pytest.approx([phi(0.1), phi(0.2), phi(0.4)])
    assert qoi.gci.verdict is Verdict.MONOTONIC
    assert qoi.gci.richardson is not None
    assert qoi.gci.richardson.p == pytest.approx(2.0, abs=1e-9)
    assert qoi.gci.richardson.phi_ext == pytest.approx(1.0, abs=1e-9)
    assert res.to_dict()["qois"][0]["gci"]["verdict"] == "monotonic_convergence"


def test_manifest_file_path_works_too(study_dir: Path) -> None:
    assert load_study(study_dir / "study.toml").name == "demo"


def test_levels_must_be_finest_first(study_dir: Path) -> None:
    levels = [("coarse", "coarse"), ("medium", "medium"), ("fine", "fine")]
    (study_dir / "study.toml").write_text(manifest(levels))
    with pytest.raises(StudyError, match="finest first"):
        assess_study(load_study(study_dir))


def test_dim_cross_checks(tmp_path: Path) -> None:
    for name, n in (("a", 6400), ("b", 1600)):
        make_case(tmp_path, name, n, 1.0, side="cyclic")
    (tmp_path / "study.toml").write_text(manifest([("a", "a"), ("b", "b")]))
    res = assess_study(load_study(tmp_path))
    assert any("no empty or wedge patches" in w for w in res.warnings)

    (tmp_path / "study.toml").write_text(
        manifest([("a", "a"), ("b", "b")]).replace("dim = 2", "dim = 3")
    )
    shutil.rmtree(tmp_path / "a")
    make_case(tmp_path, "a", 6400, 1.0, side="empty")
    res = assess_study(load_study(tmp_path))
    assert any("dim = 3 but" in w for w in res.warnings)
    assert any("different empty or wedge" in w for w in res.warnings)


def test_window_mean_and_scale(tmp_path: Path) -> None:
    case = tmp_path / "c"
    (case / "pp" / "0").mkdir(parents=True)
    (case / "pp" / "0" / "t.dat").write_text(TABLE)
    qoi = QoI("q", "pp/*/t.dat", 1, reduction="window_mean", window=0.5, min_samples=1, scale=2.0)
    value, used, note = reduce_series(read_series(case, qoi), qoi)
    assert (value, used, note) == (pytest.approx(2 * 1.375), 2, None)
    qoi = QoI("q", "pp/*/t.dat", 1, reduction="window_mean", min_samples=50)
    value, used, note = reduce_series(read_series(case, qoi), qoi)
    assert used == 4 and note is not None and "all were used" in note


def test_restart_files_join_in_start_time_order(tmp_path: Path) -> None:
    case = tmp_path / "c"
    for start, rows in (("0", "1\t10\n2\t20\n3\t30\n"), ("2.5", "3\t31\n4\t41\n")):
        (case / "pp" / start).mkdir(parents=True)
        (case / "pp" / start / "t.dat").write_text("# Time v\n" + rows)
    series = read_series(case, QoI("q", "pp/*/t.dat", "v"))
    assert series.x == (1, 2, 3, 4)
    assert series.y == (10, 20, 31, 41)


# --- manifest validation ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda t: t.replace('refined = "mesh"\n', ""), "refined is required"),
        (lambda t: t.replace('refined = "mesh"', 'refined = "all"'), "refined must be"),
        (lambda t: t.replace("dim = 2", "dim = 4"), "dim"),
        (lambda t: t + "\ncolour = 1\n", "unknown key"),
        (lambda t: t.replace('path = "fine"', 'path = "../elsewhere"'), "outside"),
        (lambda t: t.replace('path = "fine"', 'path = "missing"'), "does not exist"),
        (lambda t: t.replace("dim = 2", "dim = 2\nlayer_cells = 10"), "only to refined = core"),
        (
            lambda t: t.replace('refined = "mesh"', 'refined = "boundary-layer"'),
            "first_layer_height",
        ),
        (
            lambda t: t.replace('column = "areaAverage(p)"', 'column = "x"\nreduction = "max"'),
            "reduction",
        ),
    ],
)
def test_manifest_errors(study_dir: Path, edit, message: str) -> None:  # type: ignore[no-untyped-def]
    path = study_dir / "study.toml"
    path.write_text(edit(path.read_text()))
    with pytest.raises(StudyError, match=message):
        load_study(study_dir)


def test_qoi_glob_cannot_escape_the_case(study_dir: Path) -> None:
    secret = study_dir / "secret.dat"
    secret.write_text("# Time v\n1 2\n")
    qoi = QoI("q", "../secret.dat", "v")
    with pytest.raises(StudyError, match="outside"):
        read_series(study_dir / "fine", qoi)


def test_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(StudyError, match="no study.toml"):
        load_study(tmp_path)


def test_boundary_layer_study_uses_first_layer_heights(tmp_path: Path) -> None:
    for name, n, h in (("fine", 6400, 0.1), ("medium", 1600, 0.2), ("coarse", 400, 0.4)):
        make_case(tmp_path, name, n, phi(h))
    text = manifest([("fine", "fine"), ("medium", "medium"), ("coarse", "coarse")])
    text = text.replace('refined = "mesh"', 'refined = "boundary-layer"')
    for name, h in (("fine", 0.1), ("medium", 0.2), ("coarse", 0.4)):
        text = text.replace(f'path = "{name}"\n', f'path = "{name}"\nfirst_layer_height = {h}\n')
    (tmp_path / "study.toml").write_text(text)
    (qoi,) = assess_study(load_study(tmp_path)).qois
    assert qoi.gci.scope is Scope.BOUNDARY_LAYER
    assert qoi.gci.richardson is not None
    assert qoi.gci.richardson.p == pytest.approx(2.0, abs=1e-9)
