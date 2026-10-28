"""Refinement scope: whole mesh, core volume only, or near-wall layers only."""

from __future__ import annotations

from typing import Any

import pytest

from foam_verify.gci import Scope, Verdict, grid_convergence

H = (1.0, 2.0, 4.0)
CONVERGED = [1.0 + 0.01 * x**2 for x in H]


def test_default_scope_is_whole_mesh_and_says_so() -> None:
    res = grid_convergence(CONVERGED, h=H)
    assert res.scope is Scope.MESH
    assert res.clean_pass
    assert res.notes[0].startswith("scope mesh")


def test_core_scope_states_what_the_uncertainty_omits() -> None:
    res = grid_convergence(CONVERGED, h=H, scope=Scope.CORE)
    assert res.scope is Scope.CORE
    assert res.clean_pass
    assert "near-wall" in res.notes[0] and "not included" in res.notes[0]


def test_core_scope_with_total_counts_needs_layer_cells() -> None:
    # 100 fixed layer cells; the core goes 8000 -> 1000 -> 125 cells, r = 2 in 3-D.
    totals = (8100, 1100, 225)
    values = [1.0 + 0.01 * x**2 for x in H]
    blind = grid_convergence(values, cells=totals, dim=3, scope=Scope.CORE)
    assert not blind.clean_pass
    assert any("understates the core refinement" in w for w in blind.warnings)
    assert blind.r21 < 2.0

    told = grid_convergence(values, cells=totals, dim=3, scope=Scope.CORE, layer_cells=100)
    assert told.r21 == pytest.approx(2.0)
    assert told.r32 == pytest.approx(2.0)
    assert told.richardson is not None
    assert told.richardson.p == pytest.approx(2.0)
    assert told.clean_pass


def test_explicit_zero_layer_cells_is_accepted() -> None:
    res = grid_convergence(CONVERGED, cells=(64, 8, 1), dim=3, scope=Scope.CORE, layer_cells=0)
    assert res.clean_pass


def test_boundary_layer_scope_needs_first_layer_heights() -> None:
    with pytest.raises(ValueError, match="first-layer heights"):
        grid_convergence(CONVERGED, cells=(64, 8, 1), dim=3, scope=Scope.BOUNDARY_LAYER)
    res = grid_convergence(CONVERGED, h=(1e-6, 2e-6, 4e-6), scope=Scope.BOUNDARY_LAYER)
    assert res.scope is Scope.BOUNDARY_LAYER
    assert res.verdict is Verdict.MONOTONIC
    assert "wall-normal" in res.notes[0]


def test_scope_is_carried_into_every_triplet() -> None:
    h = (1.0, 2.0, 4.0, 8.0)
    res = grid_convergence([1.0 + 0.01 * x**2 for x in h], h=h, scope=Scope.CORE)
    assert [t.scope for t in res.triplets] == [Scope.CORE, Scope.CORE]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"h": H, "layer_cells": 10}, "only to scope core"),
        ({"h": H, "scope": Scope.CORE, "layer_cells": 10}, "needs cells"),
        ({"cells": (64, 8, 1), "dim": 3, "scope": Scope.CORE, "layer_cells": 5}, "below every"),
    ],
)
def test_layer_cells_misuse(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        grid_convergence(CONVERGED, **kwargs)


def test_missing_layer_cells_warning_only_with_an_uncertainty() -> None:
    # Divergent data: the layer count cannot change the outcome.
    res = grid_convergence([1.0, 1.5, 1.7], cells=(8000, 1000, 125), dim=3, scope=Scope.CORE)
    assert res.verdict is Verdict.DIVERGENT
    assert res.uncertainty is None
    assert not any("layer" in w for w in res.warnings)


def test_missing_layer_cells_warning_follows_each_triplet() -> None:
    # Grids 1-3 converge (warned); grids 2-4 diverge (no layer warning).
    cells = (8000, 1000, 125, 64)
    res = grid_convergence([1.0, 1.04, 1.2, 1.25], cells=cells, dim=3, scope=Scope.CORE)
    first, second = res.triplets
    assert any("understates" in w for w in first.warnings)
    assert second.uncertainty is None
    assert not any("understates" in w for w in second.warnings)
