"""Lid-driven cavity at Re = 100 (icoFoam): case generator and output collector.

    python3 generate.py setup     # writes build/n20 ... build/n160
    bash run.sh                   # inside the pinned container (see ../README.md)
    python3 generate.py collect   # copies the committed subset into n20/ ... n160/

The square cavity of side L = 0.1 m, lid speed U = 1 m/s, as in the icoFoam cavity tutorial,
but with nu = 0.001 so that Re = U L / nu = 100 (the tutorial's nu = 0.01 gives Re = 10).
Schemes are the tutorial's. The time step keeps the Courant number at 0.5 on every level, and
each run goes to t = 10 s (100 L/U), well past steady state.

Quantities of interest, all in units of U and L, sampled with cellPoint interpolation so that
every level is read at the same physical points:
- u on the vertical centreline at three of Ghia et al.'s (1982) points, y = 64/128, 58/128
  and 109/128 of L, written every 0.05 s;
- the profiles u(y) on the vertical centreline and v(x) on the horizontal one, 255 points each
  (spacing L/256), written at the end only; foam-verify takes their extrema.
Standard library only, so it runs on any host Python 3.11+.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
LEVELS = (160, 80, 40, 20)  # cells per side, finest first
L = 0.1
NU = 0.001
COURANT = 0.5
END_TIME = 10
SAMPLE_INTERVAL = 0.05
GHIA_Y = (64, 58, 109)  # Ghia et al. (1982) grid indices, y = k/128 of L
PROFILE_POINTS = 255  # k/256 of L, k = 1 ... 255
Z = 0.005  # mid-plane of the one-cell-thick mesh

HEADER = """FoamFile
{{
    version     2.0;
    format      ascii;
    class       {cls};
    object      {obj};
}}
"""


def foam(cls: str, obj: str, body: str) -> str:
    return HEADER.format(cls=cls, obj=obj) + "\n" + body.strip() + "\n"


def point(x: float, y: float) -> str:
    return f"({x:.10g} {y:.10g} {Z})"


def block_mesh(n: int) -> str:
    return foam(
        "dictionary",
        "blockMeshDict",
        f"""
scale {L};

vertices
(
    (0 0 0) (1 0 0) (1 1 0) (0 1 0)
    (0 0 0.1) (1 0 0.1) (1 1 0.1) (0 1 0.1)
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({n} {n} 1) simpleGrading (1 1 1)
);

boundary
(
    movingWall
    {{
        type            wall;
        faces           ((3 7 6 2));
    }}
    fixedWalls
    {{
        type            wall;
        faces           ((0 4 7 3) (2 6 5 1) (1 5 4 0));
    }}
    frontAndBack
    {{
        type            empty;
        faces           ((0 3 2 1) (4 5 6 7));
    }}
);
""",
    )


def probes(name: str, points: list[str], write: str) -> str:
    listing = "\n".join(f"            {p}" for p in points)
    return f"""
    {name}
    {{
        type            probes;
        libs            (sampling);
        interpolationScheme cellPoint;
        fields          (U);
        {write}
        writePrecision  12;
        log             false;
        probeLocations
        (
{listing}
        );
    }}
"""


def control(n: int) -> str:
    dt = COURANT * (L / n)  # lid speed 1
    ghia = [point(0.5 * L, k / 128 * L) for k in GHIA_Y]
    vertical = [point(0.5 * L, k / 256 * L) for k in range(1, PROFILE_POINTS + 1)]
    horizontal = [point(k / 256 * L, 0.5 * L) for k in range(1, PROFILE_POINTS + 1)]
    every = f"writeControl    runTime;\n        writeInterval   {SAMPLE_INTERVAL};"
    final = "writeControl    writeTime;"
    return foam(
        "dictionary",
        "controlDict",
        f"""
application     icoFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {END_TIME};
deltaT          {dt:.10g};
writeControl    runTime;
writeInterval   {END_TIME};
purgeWrite      0;
writeFormat     ascii;
writePrecision  12;
writeCompression off;
timeFormat      general;
timePrecision   8;
runTimeModifiable false;

functions
{{
{probes("ghiaPoints", ghia, every)}
{probes("verticalCentreline", vertical, final)}
{probes("horizontalCentreline", horizontal, final)}
    residuals
    {{
        type            solverInfo;
        libs            (utilityFunctionObjects);
        fields          (U p);
        executeControl  runTime;
        executeInterval {SAMPLE_INTERVAL};
        writeControl    runTime;
        writeInterval   {SAMPLE_INTERVAL};
    }}
}}
""",
    )


SCHEMES = foam(
    "dictionary",
    "fvSchemes",
    """
ddtSchemes      { default Euler; }
gradSchemes     { default Gauss linear; }
divSchemes
{
    default         none;
    div(phi,U)      Gauss linear;
}
laplacianSchemes     { default Gauss linear orthogonal; }
interpolationSchemes { default linear; }
snGradSchemes        { default orthogonal; }
""",
)

SOLUTION = foam(
    "dictionary",
    "fvSolution",
    """
solvers
{
    p
    {
        solver          PCG;
        preconditioner  DIC;
        tolerance       1e-10;
        relTol          0.05;
    }
    pFinal
    {
        $p;
        relTol          0;
    }
    U
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-12;
        relTol          0;
    }
}

PISO
{
    nCorrectors     2;
    nNonOrthogonalCorrectors 0;
    pRefCell        0;
    pRefValue       0;
}
""",
)

TRANSPORT = foam("dictionary", "transportProperties", f"nu              {NU};")

U0 = foam(
    "volVectorField",
    "U",
    """
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    movingWall   { type fixedValue; value uniform (1 0 0); }
    fixedWalls   { type noSlip; }
    frontAndBack { type empty; }
}
""",
)

P0 = foam(
    "volScalarField",
    "p",
    """
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{
    movingWall   { type zeroGradient; }
    fixedWalls   { type zeroGradient; }
    frontAndBack { type empty; }
}
""",
)


def setup() -> None:
    for n in LEVELS:
        case = BUILD / f"n{n}"
        if case.exists():
            shutil.rmtree(case)
        files = {
            "system/blockMeshDict": block_mesh(n),
            "system/controlDict": control(n),
            "system/fvSchemes": SCHEMES,
            "system/fvSolution": SOLUTION,
            "constant/transportProperties": TRANSPORT,
            "0/U": U0,
            "0/p": P0,
        }
        for rel, text in files.items():
            path = case / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    print(f"wrote {len(LEVELS)} cases under {BUILD}")


def _owner_header(src: Path, dst: Path) -> None:
    lines = src.read_text().splitlines(keepends=True)
    end = next(i for i, line in enumerate(lines) if line.startswith("// * *"))
    dst.write_text("".join(lines[: end + 1]) + "// (cut after the header: only nCells is read)\n")


def collect() -> None:
    for n in LEVELS:
        src = BUILD / f"n{n}"
        dst = HERE / f"n{n}"
        if dst.exists():
            shutil.rmtree(dst)
        for sub in ("system", "constant", "0", "postProcessing"):
            shutil.copytree(src / sub, dst / sub, ignore=shutil.ignore_patterns("polyMesh"))
        mesh = dst / "constant" / "polyMesh"
        mesh.mkdir()
        shutil.copy2(src / "constant/polyMesh/boundary", mesh / "boundary")
        _owner_header(src / "constant/polyMesh/owner", mesh / "owner")
        for log in ("log.blockMesh", "log.checkMesh", "log.icoFoam"):
            text = (src / log).read_text().splitlines(keepends=True)
            if len(text) > 400:  # keep the header and the end of long solver logs
                text = text[:60] + ["...\n"] + text[-200:]
            (dst / log).write_text("".join(text))
    print(f"collected {len(LEVELS)} levels into {HERE}")


if __name__ == "__main__":
    commands = {"setup": setup, "collect": collect}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: python3 {Path(__file__).name} setup|collect")
    commands[sys.argv[1]]()
