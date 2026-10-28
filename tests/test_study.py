"""study.toml reader, mesh headers and function-object tables."""

from __future__ import annotations

import math
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from foam_verify.gci import Scope, Verdict
from foam_verify.iterative import Verdict as IterativeVerdict
from foam_verify.study import (
    Profile,
    QoI,
    StudyError,
    assess_study,
    cell_count,
    load_study,
    patch_faces,
    patch_types,
    profile_crossing,
    profile_extremum,
    read_profile,
    read_profiles,
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
    assert patch_faces(REAL) == {"movingWall": 20, "fixedWalls": 60, "frontAndBack": 800}


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


def test_a_study_without_settings_files_is_not_shown_consistent(study_dir: Path) -> None:
    # The fixture keeps only mesh headers and function-object output.
    res = assess_study(load_study(study_dir))
    check = res.consistency
    assert check is not None and not check.clean_pass
    assert check.levels == ("fine", "medium", "coarse")
    assert check.warnings[0].startswith("no system/fvSchemes or system/fvSolution")
    assert res.to_dict()["consistency"]["clean_pass"] is False


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


CYCLIC = """FoamFile {{ version 2.0; format ascii; class polyBoundaryMesh; object boundary; }}
3
(
    walls {{ type wall; nFaces 8; startFace 0; }}
    front {{ type cyclic; neighbourPatch back; nFaces {front}; startFace 8; }}
    back {{ type cyclic; neighbourPatch front; nFaces {back}; startFace 9; }}
)
"""


def cyclic_study(root: Path, dim: int, back: Sequence[int]) -> Path:
    """Two levels with a cyclic pair: front has one face per cell, back the counts given."""
    for (name, n), faces in zip((("a", 6400), ("b", 1600)), back, strict=True):
        case = make_case(root, name, n, 1.0, side="cyclic")
        (case / "constant" / "polyMesh" / "boundary").write_text(CYCLIC.format(front=n, back=faces))
    text = manifest([("a", "a"), ("b", "b")]).replace("dim = 2", f"dim = {dim}")
    (root / "study.toml").write_text(text)
    return root


def test_one_face_per_cell_on_a_cyclic_pair_confirms_dim_2(tmp_path: Path) -> None:
    # The square duct's case: one cell between the two halves of a cyclic, on every level.
    res = assess_study(load_study(cyclic_study(tmp_path, 2, back=(6400, 1600))))
    assert res.warnings == ()
    assert res.notes == (
        "dim = 2 with no empty or wedge patches: patches back and front have one face per cell "
        "on every level, so the mesh is one cell across them and that direction is not refined",
    )


def test_one_thin_patch_is_not_enough(tmp_path: Path) -> None:
    # On level b the back half has two faces per cell row: not one cell across.
    res = assess_study(load_study(cyclic_study(tmp_path, 2, back=(6400, 800))))
    assert res.notes == ()
    assert any("assumed one cell across" in w for w in res.warnings)


def test_dim_3_with_a_one_cell_direction_is_flagged(tmp_path: Path) -> None:
    res = assess_study(load_study(cyclic_study(tmp_path, 3, back=(6400, 1600))))
    assert res.notes == ()
    assert res.warnings == (
        "dim = 3 but patches back and front have one face per cell on every level, so the mesh "
        "is one cell across them and that direction is not refined; check dim",
    )


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


# --- iterative convergence in a study ---------------------------------------------------


def write_history(case: Path, values: list[float]) -> None:
    out = case / "postProcessing" / "avg" / "0" / "surfaceFieldValue.dat"
    rows = "".join(f"{i}\t{v!r}\n" for i, v in enumerate(values, start=1))
    out.write_text("# Time\tareaAverage(p)\n" + rows)


def test_two_samples_per_level_cannot_show_iterative_convergence(study_dir: Path) -> None:
    # The grid study passes on its own; the histories are too short to say the values settled.
    (qoi,) = assess_study(load_study(study_dir)).qois
    assert qoi.gci.clean_pass
    assert [r.verdict for r in qoi.iterative] == [IterativeVerdict.INSUFFICIENT_DATA] * 3
    assert qoi.contamination is not None and not qoi.contamination.clean_pass
    assert qoi.contamination.warnings[0].startswith("level fine: insufficient_data")


def test_settled_histories_pass_the_contamination_check(study_dir: Path) -> None:
    for name, h in (("fine", 0.1), ("medium", 0.2), ("coarse", 0.4)):
        write_history(study_dir / name, [phi(h) + 0.5 * math.exp(-i / 20) for i in range(500)])
    res = assess_study(load_study(study_dir))
    (qoi,) = res.qois
    assert qoi.values == pytest.approx([phi(0.1), phi(0.2), phi(0.4)], abs=1e-9)
    for it in qoi.iterative:
        assert it.verdict is IterativeVerdict.CONVERGED and it.clean_pass
        assert it.samples == 500 and it.window == 50 and it.window_x == (451, 500)
    check = qoi.contamination
    assert check is not None and check.clean_pass and check.warnings == ()
    assert check.u_num == qoi.gci.uncertainty
    assert check.worst_ratio is not None and check.worst_ratio < 1e-6
    assert res.to_dict()["qois"][0]["iterative"][0]["verdict"] == "converged"


def test_a_drifting_level_blocks_the_contamination_check(study_dir: Path) -> None:
    # The medium level still climbs 3e-5 per sample to the same last value: the GCI cannot
    # see it, the history can.
    for name, h in (("fine", 0.1), ("medium", 0.2), ("coarse", 0.4)):
        slope = 3e-5 if name == "medium" else 0.0
        write_history(study_dir / name, [phi(h) - slope * (499 - i) for i in range(500)])
    (qoi,) = assess_study(load_study(study_dir)).qois
    assert qoi.gci.clean_pass
    verdicts = [r.verdict for r in qoi.iterative]
    assert verdicts == [
        IterativeVerdict.CONVERGED,
        IterativeVerdict.DRIFTING,
        IterativeVerdict.CONVERGED,
    ]
    assert qoi.contamination is not None and not qoi.contamination.clean_pass
    assert any(w.startswith("level medium: drifting") for w in qoi.contamination.warnings)


def test_window_and_min_samples_set_the_iterative_window(study_dir: Path) -> None:
    for name, h in (("fine", 0.1), ("medium", 0.2), ("coarse", 0.4)):
        write_history(study_dir / name, [phi(h)] * 500)
    path = study_dir / "study.toml"
    path.write_text(path.read_text() + "window = 0.5\nmin_samples = 10\n")
    (qoi,) = assess_study(load_study(study_dir)).qois
    assert [r.window for r in qoi.iterative] == [250] * 3


# --- manifest validation ----------------------------------------------------------------


MANIFEST_EDITS: list[tuple[Callable[[str], str], str]] = [
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
]


@pytest.mark.parametrize(("edit", "message"), MANIFEST_EDITS)
def test_manifest_errors(study_dir: Path, edit: Callable[[str], str], message: str) -> None:
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


# --- profile extrema --------------------------------------------------------------------


def write_probes(path: Path, xs: list[float], values: list[float], order: list[int]) -> None:
    """A probes file with vector values (v, 0, 0), probes listed in the given order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Probe {i} ({xs[k]} 0.05 0.005)" for i, k in enumerate(order)]
    lines.append("# Time " + " ".join(str(i) for i in range(len(order))))
    lines.append("0.5 " + " ".join("(0 0 0)" for _ in order))
    lines.append("1 " + " ".join(f"({values[k]!r} 0 0)" for k in order))
    path.write_text("\n".join(lines) + "\n")


def write_probe_rows(
    path: Path, xs: Sequence[float], rows: Sequence[tuple[float, Sequence[float]]]
) -> None:
    """A probes file with vector values (v, 0, 0), one row per (time, values)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Probe {i} ({x} 0.05 0.005)" for i, x in enumerate(xs)]
    lines.append("# Time " + " ".join(str(i) for i in range(len(xs))))
    lines += [f"{t:g} " + " ".join(f"({v!r} 0 0)" for v in values) for t, values in rows]
    path.write_text("\n".join(lines) + "\n")


def test_parabola_minimum_is_recovered_exactly(tmp_path: Path) -> None:
    xs = [k / 10 for k in range(1, 10)]
    values = [2.0 + 3.0 * (x - 0.437) ** 2 for x in xs]
    write_probes(tmp_path / "pp/0/U", xs, values, order=[4, 0, 8, 2, 6, 1, 7, 3, 5])
    qoi = QoI("m", "pp/*/U", None, component=0, profile="min", axis=0)
    profile = read_profile(tmp_path, qoi)
    assert profile.coords == tuple(xs) and profile.time == 1.0
    value, where, note = profile_extremum(profile, "min")
    assert value == pytest.approx(2.0, abs=1e-12)
    assert where == pytest.approx(0.437, abs=1e-12)
    assert note is None
    value, where, note = profile_extremum(profile, "max")
    assert (value, where) == (values[-1], xs[-1]) and note is not None


def test_fitted_extremum_error_is_third_order_in_the_spacing() -> None:
    from foam_verify.study import Profile

    def f(x: float) -> float:  # minimum -0.25 at x = 0.5; cubic term shifts the fit
        return (x - 0.5) ** 2 - 0.25 + 0.4 * (x - 0.5) ** 3

    errors: list[float] = []
    for n in (32, 64):
        xs = tuple((k + 0.3) / n for k in range(n))
        prof = Profile(xs, tuple(f(x) for x in xs), 0.0, "f")
        errors.append(abs(profile_extremum(prof, "min")[0] + 0.25))
    assert errors[1] < errors[0] / 6


def test_real_probes_file_as_a_profile() -> None:
    # Two probes at y = 0.05 and 0.08: the minimum of u is the end probe, with a note.
    qoi = QoI("u", "postProcessing/probes/0/U", None, component=0, profile="min", axis=1)
    profile = read_profile(REAL, qoi)
    assert profile.coords == (0.05, 0.08)
    value, where, note = profile_extremum(profile, "min")
    assert value == pytest.approx(-0.196068) and where == 0.05
    assert note is not None and "end" in note


PEAK = (
    '\n[[qoi]]\nname = "peak"\nfile = "postProcessing/line/*/U"\nprofile = "max"\n'
    'axis = "x"\ncomponent = "x"\nscale = -1\n'
)


def test_profile_rows_join_across_restarts(tmp_path: Path) -> None:
    xs = [0.25, 0.5, 0.75]
    write_probe_rows(tmp_path / "pp/0/U", xs, [(t, [t, t, t]) for t in (1, 2, 3)])
    write_probe_rows(tmp_path / "pp/2.5/U", xs, [(t, [-t, -t, -t]) for t in (3, 4)])
    qoi = QoI("m", "pp/*/U", None, component=0, profile="min", axis=0)
    profiles = read_profiles(tmp_path, qoi)
    assert [p.time for p in profiles] == [1, 2, 3, 4]
    assert [p.values[0] for p in profiles] == [1, 2, -3, -4]  # the restart file covers t = 3
    assert [p.file for p in profiles] == ["pp/0/U", "pp/0/U", "pp/2.5/U", "pp/2.5/U"]
    assert read_profile(tmp_path, qoi) == profiles[-1]


def test_profile_qoi_history_is_the_extremum_of_every_row(study_dir: Path) -> None:
    xs = [k / 10 for k in range(1, 10)]
    for name, h in (("fine", 0.1), ("medium", 0.2), ("coarse", 0.4)):
        rows = [(t, [-phi(h) - (x - 0.42) ** 2 - math.exp(-t) for x in xs]) for t in range(1, 61)]
        write_probe_rows(study_dir / name / "postProcessing/line/0/U", xs, rows)
    path = study_dir / "study.toml"
    path.write_text(path.read_text() + PEAK)
    peak = assess_study(load_study(study_dir)).qois[1]
    assert peak.values == pytest.approx([phi(0.1), phi(0.2), phi(0.4)], abs=1e-12)
    for it, h in zip(peak.iterative, (0.1, 0.2, 0.4), strict=True):
        assert it.verdict is IterativeVerdict.CONVERGED and it.clean_pass
        assert it.samples == 60 and it.window == 50 and it.window_x == (11, 60)
        assert it.maximum == pytest.approx(phi(h) + math.exp(-11), abs=1e-12)
    assert peak.contamination is not None and peak.contamination.clean_pass


def test_study_with_a_profile_qoi(study_dir: Path) -> None:
    xs = [k / 10 for k in range(1, 10)]
    for name, h in (("fine", 0.1), ("medium", 0.2), ("coarse", 0.4)):
        values = [-phi(h) - (x - 0.42) ** 2 for x in xs]
        write_probes(study_dir / name / "postProcessing/line/0/U", xs, values, list(range(9)))
    path = study_dir / "study.toml"
    path.write_text(path.read_text() + PEAK)
    res = assess_study(load_study(study_dir))
    peak = res.qois[1]
    assert peak.values == pytest.approx([phi(0.1), phi(0.2), phi(0.4)])
    assert peak.samples == (9, 9, 9)
    assert any("max at x = 0.42" in note for note in peak.notes)
    assert peak.gci.richardson is not None
    assert peak.gci.richardson.p == pytest.approx(2.0, abs=1e-9)


# --- raw surface files and crossings ------------------------------------------------------


def write_raw(path: Path, points: Sequence[tuple[float, float]], vector: bool = True) -> None:
    """A raw surface file as surfaces writes it: x y z and the field, here (v, 0, 0) or v."""
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "x y z  tau_x tau_y tau_z" if vector else "x y z  p"
    rows = [f"{x!r} -0.0254 0 {v!r} 0 0" if vector else f"{x!r} -0.0254 0 {v!r}" for x, v in points]
    path.write_text(f"# tau  FACE_DATA {len(points)}\n# {head}\n" + "\n".join(rows) + "\n")


RAW = "postProcessing/shear/*/tau_lowerWall.raw"


def test_crossings_first_last_and_none() -> None:
    profile = Profile((0.0, 1.0, 2.0, 3.0, 4.0), (1.0, -1.0, -3.0, 1.0, 2.0), 0.0, "f")
    assert profile_crossing(profile, "first_crossing") == pytest.approx(0.5)
    assert profile_crossing(profile, "last_crossing") == pytest.approx(2.75)
    assert profile_crossing(Profile((0.0, 1.0), (1.0, 2.0), 0.0, "f"), "last_crossing") is None
    # A value of exactly zero is passed over: the change of sign is found between its neighbours.
    through_zero = Profile((0.0, 1.0, 2.0), (1.0, 0.0, -1.0), 0.0, "f")
    assert profile_crossing(through_zero, "first_crossing") == pytest.approx(1.0)
    with pytest.raises(ValueError, match="first_crossing or last_crossing"):
        profile_crossing(profile, "min")


def test_raw_surface_files_give_one_profile_per_time(tmp_path: Path) -> None:
    # The crossing moves from x = 0.30 towards 0.25 as the run settles; points written unsorted.
    xs = [0.4, 0.1, 0.0, 0.2, 0.3, 0.5]
    for time, xr in ((100, 0.30), (200, 0.26), (300, 0.25)):
        write_raw(
            tmp_path / f"postProcessing/shear/{time}/tau_lowerWall.raw", [(x, x - xr) for x in xs]
        )
    qoi = QoI("xr", RAW, None, component=0, profile="last_crossing", axis=0)
    profiles = read_profiles(tmp_path, qoi)
    assert [p.time for p in profiles] == [100, 200, 300]
    assert profiles[0].coords == (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
    assert profiles[-1].file == "postProcessing/shear/300/tau_lowerWall.raw"
    assert [profile_crossing(p, "last_crossing") for p in profiles] == pytest.approx(
        [0.30, 0.26, 0.25]
    )
    assert read_profile(tmp_path, qoi) == profiles[-1]


@pytest.mark.parametrize(
    ("component", "vector", "folder", "message"),
    [
        (None, True, "100", "set component"),
        (0, False, "100", "it is a scalar"),
        (3, True, "100", "out of range"),
        (0, True, "latest", "folder is its time"),
    ],
)
def test_raw_surface_file_errors(
    tmp_path: Path, component: int | None, vector: bool, folder: str, message: str
) -> None:
    write_raw(
        tmp_path / f"postProcessing/shear/{folder}/tau_lowerWall.raw",
        [(0.0, 1.0), (1.0, -1.0)],
        vector,
    )
    qoi = QoI("xr", RAW, None, component=component, profile="last_crossing", axis=0)
    with pytest.raises(StudyError, match=message):
        read_profiles(tmp_path, qoi)


def test_study_with_a_crossing_qoi(study_dir: Path) -> None:
    # The crossing settles to 0.3 + phi(h) on each level: p = 2 comes back, and the history of
    # the crossing over the sampled times feeds the iterative check.
    xs = [k / 20 for k in range(41)]
    for name, h in (("fine", 0.1), ("medium", 0.2), ("coarse", 0.4)):
        for time in range(100, 1200, 100):
            xr = 0.3 + phi(h) + 0.5 ** (time / 100)
            write_raw(
                study_dir / name / f"postProcessing/shear/{time}/tau_lowerWall.raw",
                [(x, x - xr) for x in xs],
            )
    path = study_dir / "study.toml"
    path.write_text(
        path.read_text()
        + f'\n[[qoi]]\nname = "xr"\nfile = "{RAW}"\nprofile = "last_crossing"\naxis = "x"\n'
        'component = "x"\nwindow = 1.0\nmin_samples = 11\n'
    )
    xr = assess_study(load_study(study_dir)).qois[1]
    assert xr.values == pytest.approx([0.3 + phi(h) + 0.5**11 for h in (0.1, 0.2, 0.4)])
    assert xr.samples == (41, 41, 41)
    assert any("last crossing at x = " in note for note in xr.notes)
    assert xr.gci.richardson is not None
    assert xr.gci.richardson.p == pytest.approx(2.0, abs=1e-9)
    assert [r.samples for r in xr.iterative] == [11, 11, 11]


def test_a_crossing_that_is_missing_is_an_error(study_dir: Path) -> None:
    for name in ("fine", "medium", "coarse"):
        write_raw(
            study_dir / name / "postProcessing/shear/100/tau_lowerWall.raw",
            [(0.0, 1.0), (1.0, 2.0)],
        )
    path = study_dir / "study.toml"
    path.write_text(
        path.read_text()
        + f'\n[[qoi]]\nname = "xr"\nfile = "{RAW}"\nprofile = "last_crossing"\naxis = "x"\n'
        'component = "x"\n'
    )
    with pytest.raises(StudyError, match="never change sign"):
        assess_study(load_study(study_dir))


def test_an_extremum_needs_distinct_coordinates(study_dir: Path) -> None:
    # A wall across the axis puts several faces at one coordinate: no parabola through them.
    for name in ("fine", "medium", "coarse"):
        write_raw(
            study_dir / name / "postProcessing/shear/100/tau_lowerWall.raw",
            [(0.0, 1.0), (0.0, 2.0), (1.0, 0.5), (2.0, 3.0)],
        )
    path = study_dir / "study.toml"
    path.write_text(
        path.read_text()
        + f'\n[[qoi]]\nname = "m"\nfile = "{RAW}"\nprofile = "min"\naxis = "x"\ncomponent = "x"\n'
    )
    with pytest.raises(StudyError, match="share a coordinate"):
        assess_study(load_study(study_dir))


@pytest.mark.parametrize(
    ("qoi", "message"),
    [
        ('profile = "min"\naxis = "y"\ncolumn = 1', "drop column"),
        ('profile = "min"', "axis must be"),
        ('profile = "mean"\naxis = "y"', "profile must be"),
        ('profile = "min"\naxis = "y"\nreduction = "window_mean"', "drop reduction"),
        ('column = 1\naxis = "y"', "axis applies only"),
        ("", "column is required"),
    ],
)
def test_profile_manifest_errors(study_dir: Path, qoi: str, message: str) -> None:
    path = study_dir / "study.toml"
    text = path.read_text().split("[[qoi]]")[0]
    path.write_text(text + f'[[qoi]]\nname = "q"\nfile = "x"\n{qoi}\n')
    with pytest.raises(StudyError, match=message):
        load_study(study_dir)
