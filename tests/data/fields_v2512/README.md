Real OpenFOAM v2512 field files (image digest in studies/README.md): the 20 x 20 cavity of
studies/cavity, run with icoFoam to t = 0.01 s (four steps), written at that time.

- binary/U, binary/p: `writeFormat binary`. The cell values are raw doubles
  (`arch "LSB;label=32;scalar=64"`); the parser must skip them by length.
- compressed/U.gz: `writeFormat ascii`, `writeCompression on`.

The internal fields are nonuniform (400 cells); the boundary conditions are those of
studies/cavity/n20/0.
