# foam-verify

Read-only verification of OpenFOAM results. It answers "can I trust this number?": grid
convergence index (GCI), iterative convergence of the quantities you report, settings consistency
across grid levels, and comparison with reference data, with the uncertainty stated.

**Status: early development.** Only the GCI engine exists so far. There are no published results
yet; this README will lead with them once they are committed.

## GCI from numbers

The grid study is given finest grid first, as values with cell counts and the number of refined
directions, or with representative cell sizes:

```console
$ uv run foam-verify gci --values 6.063 5.972 5.863 --cells 18000 8000 4500 --dim 2 --refined mesh
$ uv run foam-verify gci --values 6.063 5.972 5.863 --cells 18000 8000 4500 --dim 2 --refined mesh --json
```

`--refined` (`mesh`, `core` or `boundary-layer`) is required: it states which part of the mesh was
refined, and so what the uncertainty covers.

The verdict is one of `monotonic_convergence`, `oscillatory_convergence`, `divergence`,
`degenerate`, `two_grid` or `order_unresolved`. Only a monotonic triplet with no warnings is a
clean pass, and the exit code is 0 only then. The maths, its sources and the conventions that are
this tool's own are in [docs/gci.md](docs/gci.md).

## Development

```console
$ make setup   # uv sync
$ make ci      # ruff + pytest
```

Built with AI assistance; the tests and the published reference values carry the claims.
