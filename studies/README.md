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

Each study's `study.toml` lists its reference values under `[[reference]]`, and its report
compares them with the finest-grid values, apart from the verdict.

- Square duct, fully developed laminar flow: Darcy f Re = 56.9083 (Fanning 14.22708), computed
  from the series solution in `foam_verify.exact` (Shah and London 1978). Kind `exact`.
- Lid-driven cavity, Re = 100: u on the vertical centreline at y = 0.5000, 0.4531 and 0.8516 of
  L is -0.20581, -0.21090 and 0.23151 (Ghia, Ghia and Shin 1982, J. Comput. Phys. 48, 387-411,
  Table I, p. 398, the Re = 100 column, their 129 x 129 grid points 65, 59 and 110). Copied from
  the paper and checked against the printed page. Kind `code`: a numerical solution with no
  stated uncertainty.
- Lid-driven cavity, Re = 100: u at the centre -0.2091491418, u_min -0.2140417, v_max
  0.179572814 and v_min -0.253804, with estimated errors 8.6e-9, 1.6e-6, 2.7e-8 and 1.1e-5
  (Marchi, Suero and Araki 2009, J. Braz. Soc. Mech. Sci. & Eng. 31(3), 186-198, Tables 6 and 7,
  pp. 194-195, the Re = 100 column; open access). Copied from the paper and checked against the
  printed pages. Kind `code`, with each estimated error taken as the 95% uncertainty U_D, an
  assumption that `study.toml` explains.
