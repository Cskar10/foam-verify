# foam-verify

Read-only verification of OpenFOAM results. It answers "can I trust this number?": grid
convergence index (GCI), iterative convergence of the quantities you report, settings consistency
across grid levels, and comparison with reference data, with the uncertainty stated.

**Status: early development.** The GCI engine, the `study.toml` reader, the iterative
convergence check and the settings consistency check exist, and three studies are committed under
[`studies/`](studies/README.md): a square duct with an exact answer, the lid-driven cavity, and
`pitzDaily`, where refining the mesh moves the walls through the wall-function switch. The
`report` command comes next; this README will lead with its results once they are committed.

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

## Iterative convergence

Residuals are not the quantity you report. For a study, foam-verify also reads the history of
each QoI on every level and asks whether the value itself has stopped moving: `converged`,
`oscillating` or `drifting`, with the iterative uncertainty u_it, half the range over the last
window of samples. On the levels behind the headline result, u_it must be at most a tenth of the
GCI uncertainty, or iterative error contaminates the grid study. The method, its sources and this
tool's own conventions are in [docs/iterative.md](docs/iterative.md).

## Settings consistency

The levels of a grid study should differ only in the mesh. foam-verify compares their schemes,
solver settings, physical properties, boundary conditions and near-wall layer settings entry by
entry, and names any difference by file and key:

```text
system/fvSchemes: divSchemes/div(phi,U): 'Gauss linear' on 160x160, 80x80, 40x40; 'Gauss upwind' on 20x20
```

Any difference blocks a clean verdict, except run controls in `controlDict` such as a time step
that shrinks with the mesh, which are listed as notes. What is compared, and why, is in
[docs/consistency.md](docs/consistency.md).

## Development

```console
$ make setup   # uv sync
$ make ci      # ruff + pytest
```

## Author

[Chris Skarakis](https://www.linkedin.com/in/chris-skarakis-511276217/)

Built with AI assistance; the tests and the published reference values carry the claims.
