# Studies

Generator scripts and committed outputs for the verification studies. Scripts here are run by
hand inside the pinned container; foam-verify itself never runs a solver. Each study folder also
holds foam-verify's report on it, `report.md` and `report.json`; `make reports` regenerates them.

- [`duct/`](duct/README.md): fully developed laminar flow in a square duct, where f Re is known
  exactly. The honesty test: the fine-grid GCI band contains the exact value.
- [`cavity/`](cavity/README.md): the lid-driven cavity at Re = 100, the recognised benchmark.
  Every QoI converges monotonically and passes cleanly.
- [`pitzDaily/`](pitzDaily/README.md): the backward-facing step with k-epsilon and wall
  functions. Refining the mesh moves the walls through the wall-function switch, and no QoI
  converges with the mesh.

## Container

Every study uses one OpenFOAM build, pinned by digest:

```text
image:   docker.io/opencfd/openfoam-default:2512
digest:  sha256:33fb575aa9980d2bc42fd58c75ae698c489293ba30c991380fe3f899c622f319
build:   _87ed40d2-20251219 OPENFOAM=2512 version=2512
arch:    "LSB;label=32;scalar=64"
```

Run a shell with the current directory mounted (`:z` relabels the mount for SELinux hosts and is
harmless elsewhere):

```console
$ IMG=docker.io/opencfd/openfoam-default@sha256:33fb575aa9980d2bc42fd58c75ae698c489293ba30c991380fe3f899c622f319
$ podman run --rm -it -v "$PWD":/work:z -w /work --entrypoint /bin/bash $IMG
# source /usr/lib/openfoam/openfoam2512/etc/bashrc
```

`docker run` takes the same arguments.

## Reference values

- Square duct, fully developed laminar flow: Darcy f Re = 56.9083 (Fanning 14.22708), computed
  from the series solution in `foam_verify.exact` (Shah and London 1978).
