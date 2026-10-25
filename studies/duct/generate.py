"""Square duct, fully developed laminar flow: case generator and output collector.

    python3 generate.py setup     # writes build/n20 ... build/n160
    bash run.sh                   # inside the pinned container (see ../README.md)
    python3 generate.py collect   # copies the committed subset into n20/ ... n160/

The cross-section is the unit square in y-z; the flow is along x through one cyclic cell, driven
by a meanVelocityForce source that holds the bulk velocity at Ubar = 1. With D_h = 1 and
nu = 0.01, Re = 100 and the Darcy friction factor times Re is

    f Re = 2 D_h^2 G / (nu Ubar) = 200 G = 8 tau_w D_h / (nu Ubar) = 800 tau_w

where G is the kinematic pressure-gradient source and tau_w the mean kinematic wall shear stress
(force balance: G * area = tau_w * perimeter). The exact value is foam_verify.exact.
Standard library only, so it runs on any host Python 3.11+.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
LEVELS = (160, 80, 40, 20)  # cells per side, finest first
LENGTH = 0.05  # duct length along x: one cyclic cell, the same on every level
NU = 0.01

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


def block_mesh(n: int) -> str:
    return foam(
        "dictionary",
        "blockMeshDict",
        f"""
scale 1;

vertices
(
    (0 0 0) ({LENGTH} 0 0) ({LENGTH} 1 0) (0 1 0)
    (0 0 1) ({LENGTH} 0 1) ({LENGTH} 1 1) (0 1 1)
);

blocks
(
    hex (0 1 2 3 4 5 6 7) (1 {n} {n}) simpleGrading (1 1 1)
);

boundary
(
    inlet
    {{
        type            cyclic;
        neighbourPatch  outlet;
        faces           ((0 4 7 3));
    }}
    outlet
    {{
        type            cyclic;
        neighbourPatch  inlet;
        faces           ((1 2 6 5));
    }}
    walls
    {{
        type            wall;
        faces           ((0 1 5 4) (3 7 6 2) (0 3 2 1) (4 5 6 7));
    }}
);
""",
    )


CONTROL = foam(
    "dictionary",
    "controlDict",
    """
application     simpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         8000;
deltaT          1;
writeControl    timeStep;
writeInterval   8000;
purgeWrite      0;
writeFormat     ascii;
writePrecision  12;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable false;

functions
{
    wallShearStress
    {
        type            wallShearStress;
        libs            (fieldFunctionObjects);
        patches         (walls);
        executeControl  timeStep;
        writeControl    writeTime;
        log             false;
    }

    wallStress
    {
        type            surfaceFieldValue;
        libs            (fieldFunctionObjects);
        regionType      patch;
        name            walls;
        operation       areaAverage;
        fields          (wallShearStress);
        writeFields     false;
        writeControl    timeStep;
        writeInterval   10;
        writePrecision  12;
        log             false;
    }

    residuals
    {
        type            solverInfo;
        libs            (utilityFunctionObjects);
        fields          (U p);
        executeControl  timeStep;
        executeInterval 10;  // solverInfo writes whenever it executes
        writeControl    timeStep;
        writeInterval   10;
    }
}
""",
)

SCHEMES = foam(
    "dictionary",
    "fvSchemes",
    """
ddtSchemes      { default steadyState; }
gradSchemes     { default Gauss linear; }
divSchemes
{
    default         none;
    div(phi,U)      Gauss linear;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes     { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes        { default corrected; }
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
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-12;
        relTol          0.01;
    }
    U
    {
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-13;
        relTol          0.01;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 0;
    consistent      yes;
    pRefCell        0;
    pRefValue       0;
    residualControl
    {
        p               1e-10;
        U               1e-10;
    }
}

relaxationFactors
{
    equations { U 0.9; }
}
""",
)

FV_OPTIONS = foam(
    "dictionary",
    "fvOptions",
    """
momentumSource
{
    type            meanVelocityForce;
    selectionMode   all;
    fields          (U);
    Ubar            (1 0 0);
}
""",
)

TRANSPORT = foam(
    "dictionary", "transportProperties", f"transportModel  Newtonian;\nnu              {NU};"
)
TURBULENCE = foam("dictionary", "turbulenceProperties", "simulationType  laminar;")

U0 = foam(
    "volVectorField",
    "U",
    """
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    inlet  { type cyclic; }
    outlet { type cyclic; }
    walls  { type noSlip; }
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
    inlet  { type cyclic; }
    outlet { type cyclic; }
    walls  { type zeroGradient; }
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
            "system/controlDict": CONTROL,
            "system/fvSchemes": SCHEMES,
            "system/fvSolution": SOLUTION,
            "system/fvOptions": FV_OPTIONS,
            "constant/transportProperties": TRANSPORT,
            "constant/turbulenceProperties": TURBULENCE,
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
        for log in ("log.blockMesh", "log.checkMesh", "log.simpleFoam"):
            text = (src / log).read_text().splitlines(keepends=True)
            if len(text) > 400:  # keep the header and the end of long solver logs
                text = text[:60] + ["...\n"] + text[-200:]
            (dst / log).write_text("".join(text))
        times = sorted(
            (p for p in src.iterdir() if p.is_dir() and p.name.replace(".", "").isdigit()),
            key=lambda p: float(p.name),
        )
        last = times[-1]
        gradient = last / "uniform" / "momentumSourceProperties"
        if gradient.is_file():
            (dst / "final").mkdir()
            shutil.copy2(gradient, dst / "final" / "momentumSourceProperties")
            (dst / "final" / "TIME").write_text(last.name + "\n")
    print(f"collected {len(LEVELS)} levels into {HERE}")


if __name__ == "__main__":
    commands = {"setup": setup, "collect": collect}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: python3 {Path(__file__).name} setup|collect")
    commands[sys.argv[1]]()
