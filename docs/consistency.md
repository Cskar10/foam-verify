# Settings consistency: what is compared and why

`foam_verify.consistency` checks that the levels of a grid study differ only in the mesh. A grid
study attributes the change in a QoI between levels to the mesh. If a scheme, a solver setting, a
property or a boundary condition also changes, the GCI measures both and reports the sum as
discretisation error. ITTC 7.5-03-01-01 puts it as systematic refinement of one input parameter
"while holding all other parameters constant" (Revision 02, 2008, section 4.1; Revision 05, 2024,
section 3.3; the copies are listed in [iterative.md](iterative.md)).

`settings_consistency()` reads the same files on every level and compares them entry by entry, so
each difference names the file and the key:

```text
system/fvSchemes: divSchemes/div(phi,U): 'Gauss linear' on 160x160, 80x80, 40x40; 'Gauss upwind' on 20x20
```

`assess_study()` runs it on every study, with the study folder as the only folder it may read. A
difference that blocks makes `consistency.clean_pass` false. A study is clean only when the
consistency check and every QoI's GCI and contamination check pass.

## What is compared

| File | Rule |
|---|---|
| `system/fvSchemes`, `fvSolution`, `fvOptions`, `fvModels`, `fvConstraints` | every entry must match |
| every dictionary directly in `constant/` (transport and thermophysical properties, the turbulence model, `g`, `fvOptions`, ...) | every entry must match |
| every field directly in `0/` | every entry must match; mesh-dependent values by kind only (below) |
| `system/controlDict` | `application` must match; any other difference is a note |
| `system/snappyHexMeshDict` | the near-wall layer settings, against the refinement scope (below) |
| any of these on some levels only | blocks |

Not compared:

- mesh generation: `blockMeshDict`, `extrudeMeshDict`, `refineMeshDict`, `topoSetDict`,
  `surfaceFeatureExtractDict`, `surfaceFeaturesDict`, `createPatchDict`, `mirrorMeshDict`,
  `meshQualityDict`, `decomposeParDict`, and `snappyHexMeshDict` apart from its layer settings.
  These differ between levels by design;
- other `system/` files, such as function-object files and `setFieldsDict`;
- subfolders of `constant/` and `0/` (`polyMesh/`, `triSurface/`, `boundaryData/`, ...), except
  as files that a compared dictionary includes;
- backups: names starting with `.` or ending in `~`, `.orig`, `.bak`, `.backup`, `.old` or `.swp`;
- files in `constant/` or `0/` without a `FoamFile` header, which are noted as not compared.

`controlDict` differences other than the application are notes because a transient study
legitimately refines the time step with the mesh: at a fixed Courant number `deltaT` halves with
the cell size, as in the cavity study. For a time-dependent QoI that makes the study a combined
refinement of space and time, and the note shows it. Run length and write settings do not change
a converged result, and the iterative check judges whether each level converged.

Without `system/fvSchemes` or `system/fvSolution` on any level, nothing that matters can be
compared, and the check is not a clean pass.

## Compared by meaning, not by text

Each file is parsed (see [The parser](#the-parser)) and the entries are compared by value:

- numbers by value: `1e-3`, `0.001` and `0.0010` are equal;
- switches: `on`, `yes` and `true` are equal, and so are `off`, `no` and `false`;
- the order of entries does not matter, and an entry given twice takes its last value, as in
  OpenFOAM;
- `$macros` are expanded, so `pFinal { $p; relTol 0; }` equals the same entries written out;
- `#include`, `#includeIfPresent` and `#sinclude` are followed inside the study folder, so a
  difference in a shared include file shows up under the including file. An include that cannot
  be followed (missing, or outside the folder) is compared as written, with a note;
- every other directive (`#includeEtc`, `#includeFunc`, `#calc`, `#eval`, `#codeStream`) and
  verbatim `#{ ... #}` code are compared as written.

A nonuniform list (`nonuniform List<vector> 6400(...)`) has one value per cell or face, so its
length and values change with the mesh. A field mapped onto each level cannot be compared value by
value. Two nonuniform values of the same element type count as the same, with a note; a uniform
value on one level against a nonuniform value on another is a difference.

## Near-wall layers

`snappyHexMeshDict` is mesh generation, but its layer settings carry the claim the study makes with
`refined` ([gci.md](gci.md), Refinement scope). snappyHexMesh documents `relativeSizes` in its own
dictionaries: the thicknesses are "relative to the undistorted size of the refined cell outside
layer (true) or absolute sizes (false)". The rules compare `addLayers` and every entry of
`addLayersControls` across levels:

| `refined` | Layer settings that differ | Layer settings that are the same |
|---|---|---|
| `mesh` | notes: the layers are refined with the mesh | blocks if every level has absolute sizes (`relativeSizes false`): the layers were not refined |
| `core` | block: the layers must be the same on every level | blocks unless every level gives absolute sizes (`relativeSizes false`): relative thicknesses follow the surface cells, which the core refinement changes |
| `boundary-layer` | notes: the refined layers | blocks: nothing was refined |

With `refined = boundary-layer` the core mesh must stay fixed, so differences in
`castellatedMeshControls` or `snapControls` block, and a study that adds no layers blocks. A
`snappyHexMeshDict` present on some levels only blocks, since the levels were meshed differently.
With none on any level, a `core` or `boundary-layer` study gets a note that its layers could not be
checked.

These rules are foam-verify's own, derived from what each scope claims. They read the settings
only; whether snappyHexMesh added the layers it was asked for is in `log.snappyHexMesh`, which is
not read.

## The parser

`foam_verify.foamdict` reads OpenFOAM dictionaries without evaluating them: comments, quoted
strings, regex keys such as `"(U|k).*"`, words with brackets such as `div(phi,U)`, sub-dictionaries,
lists and counted lists, dimension sets, uniform lists `N{value}`, files that hold a list rather
than a dictionary, `$macros` with OpenFOAM's scoping (`$name`, `$:name`, `$..name`, `$a/b`,
`$a.b`), the includes above, and gzip. Typed lists (`List<scalar>` and the like) are skipped,
not read: in ASCII files to the matching bracket, in binary files by their length in bytes from
the `arch` entry of the header. Text is decoded as Latin-1, one character per byte, so binary data
cannot break the decoding. Files above 64 MiB are refused.

It was run once on every dictionary in the OpenFOAM v2512 tutorials (`system/`, `constant/`, `0/`
and `0.orig/`; 9,277 files, the `blockMeshDict.m4` templates excluded), and every file parsed.
Spot checks of the result included `pitzDaily`'s schemes and solution settings, a `$p` merge in
`TJunction`, and `motorBike`'s layer settings and its included initial conditions. The tutorial
files are not part of this repository; `tests/test_foamdict.py` covers each feature on small
examples, and reads binary and compressed fields that v2512 wrote for the 20 x 20 cavity
(`tests/data/fields_v2512`).

## Not covered

- Multi-region cases: `system/<region>/`, `constant/<region>/` and `0/<region>/`.
- Values that only a directive produces (`#includeEtc`, `#includeFunc`, `#calc`, `#eval`,
  `#codeStream`): the directive is compared as written, not its result.
- Binary lists of element types other than scalars, vectors, tensors and labels.
- Whether the layers were added: snappyHexMesh's own log, not the settings.
