"""pitzDaily (simpleFoam, k-epsilon, wall functions): case generator and output collector.

    python3 generate.py setup     # writes build/n12k ... build/n139k
    bash run.sh                   # inside the pinned container (see ../README.md)
    python3 generate.py collect   # copies the committed subset into n12k/ ... n139k/

The OpenFOAM v2512 pitzDaily tutorial: the backward-facing step of Pitz and Daily (1983), step
height H = 25.4 mm, inlet velocity 10 m/s, nu = 1e-5 (Re_H = 25,400), standard k-epsilon with
wall functions. Its geometry, gradings, schemes, solver settings and boundary conditions are kept;
two things change:

- four meshes: every block's cell count is the tutorial's times 1.5^k, k = 0 ... 3, rounded to
  the nearest integer (half up). Level k = 0 is the tutorial mesh, 12,225 cells. The gradings
  (end-to-start cell size ratios) are kept, so each level is the tutorial mesh refined by about
  1.5 per direction everywhere, near-wall cells included;
- the tutorial's residualControl stops its run after about 285 iterations, when the residuals
  fall below 1e-2 to 1e-3. It is removed, so that every level runs the same number of iterations
  and each QoI is judged by its own history.

Quantities of interest:
- the pressure drop: inlet minus outlet area-averaged kinematic pressure (m^2/s^2), through
  multiFieldValue as in v2512's pressureDifferencePatch template, every 10 iterations;
- the lower-wall shear stress, sampled on the lowerWall patch (raw face values) every 100
  iterations over the last 2000. Its last change of sign along x is the reattachment point.
Also written: y+ on the walls at the end (yPlus), and the residuals every 10 iterations.
Standard library only, so it runs on any host Python 3.11+.
"""

from __future__ import annotations

import math
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
RATIO = 1.5  # refinement per direction between levels
LEVELS = (3, 2, 1, 0)  # k: every block's cell count times RATIO**k, finest first
ITERATIONS = 8000
SAMPLE_EVERY = 10  # pressure drop and residuals
SHEAR_EVERY = 200  # lower-wall shear stress, over the last SHEAR_SPAN iterations
SHEAR_SPAN = 2000

# The tutorial's cell counts: before the step, along the channel, in the outlet contraction;
# below the step line (y < 0) and above it.
NX_INLET, NX_CHANNEL, NX_OUTLET = 18, 180, 25
NY_LOWER, NY_UPPER = 27, 30

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


def cells(n: int, k: int) -> int:
    """A tutorial cell count refined k times, rounded half up."""
    return math.floor(n * RATIO**k + 0.5)


def total_cells(k: int) -> int:
    inlet, channel, outlet = (cells(n, k) for n in (NX_INLET, NX_CHANNEL, NX_OUTLET))
    lower, upper = cells(NY_LOWER, k), cells(NY_UPPER, k)
    return inlet * upper + channel * (lower + upper) + outlet * (lower + upper)


def name(k: int) -> str:
    return f"n{round(total_cells(k) / 1000)}k"


def block_mesh(k: int) -> str:
    inlet, channel, outlet = (cells(n, k) for n in (NX_INLET, NX_CHANNEL, NX_OUTLET))
    lower, upper = cells(NY_LOWER, k), cells(NY_UPPER, k)
    return foam(
        "dictionary",
        "blockMeshDict",
        f"""
scale   0.001;

vertices
(
    (-20.6 0 -0.5) (-20.6 25.4 -0.5) (0 -25.4 -0.5) (0 0 -0.5) (0 25.4 -0.5)
    (206 -25.4 -0.5) (206 0 -0.5) (206 25.4 -0.5) (290 -16.6 -0.5) (290 0 -0.5) (290 16.6 -0.5)
    (-20.6 0 0.5) (-20.6 25.4 0.5) (0 -25.4 0.5) (0 0 0.5) (0 25.4 0.5)
    (206 -25.4 0.5) (206 0 0.5) (206 25.4 0.5) (290 -16.6 0.5) (290 0 0.5) (290 16.6 0.5)
);

// Multi-grading across the channel, as in the tutorial: (length fraction, cell fraction,
// expansion ratio) for each section.
negY    ((2 4 1) (1 3 0.3));
posY    ((1 4 2) (2 3 4) (2 4 0.25));
posYR   ((2 1 1) (1 1 0.25));

blocks
(
    hex (0 3 4 1 11 14 15 12) ({inlet} {upper} 1) simpleGrading (0.5 $posY 1)
    hex (2 5 6 3 13 16 17 14) ({channel} {lower} 1)
        edgeGrading (4 4 4 4 $negY 1 1 $negY 1 1 1 1)
    hex (3 6 7 4 14 17 18 15) ({channel} {upper} 1)
        edgeGrading (4 4 4 4 $posY $posYR $posYR $posY 1 1 1 1)
    hex (5 8 9 6 16 19 20 17) ({outlet} {lower} 1) simpleGrading (2.5 1 1)
    hex (6 9 10 7 17 20 21 18) ({outlet} {upper} 1) simpleGrading (2.5 $posYR 1)
);

edges   ();

boundary
(
    inlet        {{ type patch; faces ((0 1 12 11)); }}
    outlet       {{ type patch; faces ((8 9 20 19) (9 10 21 20)); }}
    upperWall    {{ type wall;  faces ((1 4 15 12) (4 7 18 15) (7 10 21 18)); }}
    lowerWall    {{ type wall;  faces ((0 3 14 11) (3 2 13 14) (2 5 16 13) (5 8 19 16)); }}
    frontAndBack
    {{
        type empty;
        faces
        (
            (0 3 4 1) (2 5 6 3) (3 6 7 4) (5 8 9 6) (6 9 10 7)
            (11 14 15 12) (13 16 17 14) (14 17 18 15) (16 19 20 17) (17 20 21 18)
        );
    }}
);
""",
    )


CONTROL = foam(
    "dictionary",
    "controlDict",
    f"""
application     simpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {ITERATIONS};
deltaT          1;
writeControl    timeStep;
writeInterval   {ITERATIONS};
purgeWrite      0;
writeFormat     ascii;
writePrecision  12;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable false;

functions
{{
    // Total pressure p + |U|^2/2, kinematic like p (rhoInf 1), for the pressure loss.
    totalPressure
    {{
        type            pressure;
        libs            (fieldFunctionObjects);
        mode            total;
        rho             rhoInf;
        rhoInf          1;
        executeControl  timeStep;
        executeInterval 1;
        writeControl    writeTime;
        log             false;
    }}

    // Inlet minus outlet area averages of p and of the total pressure, as in v2512's
    // pressureDifferencePatch template.
    pressureDrop
    {{
        type            multiFieldValue;
        libs            (fieldFunctionObjects);
        operation       subtract;
        writeControl    timeStep;
        writeInterval   {SAMPLE_EVERY};
        writePrecision  12;
        log             false;
        functions
        {{
            inlet
            {{
                type            surfaceFieldValue;
                libs            (fieldFunctionObjects);
                regionType      patch;
                name            inlet;
                operation       areaAverage;
                fields          (p total(p));
                writeFields     false;
                writeControl    timeStep;
                writeInterval   {SAMPLE_EVERY};
                log             false;
            }}
            outlet
            {{
                type            surfaceFieldValue;
                libs            (fieldFunctionObjects);
                regionType      patch;
                name            outlet;
                operation       areaAverage;
                fields          (p total(p));
                writeFields     false;
                writeControl    timeStep;
                writeInterval   {SAMPLE_EVERY};
                log             false;
            }}
        }}
    }}

    wallShearStress
    {{
        type            wallShearStress;
        libs            (fieldFunctionObjects);
        patches         (lowerWall);
        executeControl  timeStep;
        executeInterval 1;
        writeControl    writeTime;
        log             false;
    }}

    lowerWallShear
    {{
        type            surfaces;
        libs            (sampling);
        surfaceFormat   raw;
        formatOptions   {{ raw {{ precision 12; }} }}
        fields          (wallShearStress);
        interpolate     false;
        timeStart       {ITERATIONS - SHEAR_SPAN};
        writeControl    timeStep;
        writeInterval   {SHEAR_EVERY};
        surfaces
        {{
            lowerWall
            {{
                type            patch;
                patches         (lowerWall);
            }}
        }}
    }}

    yPlus
    {{
        type            yPlus;
        libs            (fieldFunctionObjects);
        writeControl    writeTime;
        log             false;
    }}

    residuals
    {{
        type            solverInfo;
        libs            (utilityFunctionObjects);
        fields          (U p k epsilon);
        executeControl  timeStep;
        executeInterval {SAMPLE_EVERY};  // solverInfo writes whenever it executes
        writeControl    timeStep;
        writeInterval   {SAMPLE_EVERY};
    }}
}}
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
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    turbulence      bounded Gauss limitedLinear 1;
    div(phi,k)      $turbulence;
    div(phi,epsilon) $turbulence;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes     { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes        { default corrected; }
wallDist             { method meshWave; }
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
        tolerance       1e-06;
        relTol          0.1;
        smoother        GaussSeidel;
    }
    "(U|k|epsilon)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-05;
        relTol          0.1;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 0;
    consistent      yes;
}

relaxationFactors
{
    equations
    {
        U               0.9;
        ".*"            0.9;
    }
}
""",
)

TRANSPORT = foam(
    "dictionary", "transportProperties", "transportModel  Newtonian;\nnu              1e-05;"
)
TURBULENCE = foam(
    "dictionary",
    "turbulenceProperties",
    """
simulationType  RAS;
RAS
{
    RASModel        kEpsilon;
    turbulence      on;
    printCoeffs     on;
}
""",
)


def field(cls: str, obj: str, dims: str, value: str, inlet: str, wall: str, outlet: str) -> str:
    return foam(
        cls,
        obj,
        f"""
dimensions      {dims};
internalField   uniform {value};
boundaryField
{{
    inlet           {{ {inlet} }}
    outlet          {{ {outlet} }}
    upperWall       {{ {wall} }}
    lowerWall       {{ {wall} }}
    frontAndBack    {{ type empty; }}
}}
""",
    )


FIELDS = {
    "0/U": field(
        "volVectorField",
        "U",
        "[0 1 -1 0 0 0 0]",
        "(0 0 0)",
        "type fixedValue; value uniform (10 0 0);",
        "type noSlip;",
        "type zeroGradient;",
    ),
    "0/p": field(
        "volScalarField",
        "p",
        "[0 2 -2 0 0 0 0]",
        "0",
        "type zeroGradient;",
        "type zeroGradient;",
        "type fixedValue; value uniform 0;",
    ),
    "0/k": field(
        "volScalarField",
        "k",
        "[0 2 -2 0 0 0 0]",
        "0.375",
        "type fixedValue; value uniform 0.375;",
        "type kqRWallFunction; value uniform 0.375;",
        "type zeroGradient;",
    ),
    "0/epsilon": field(
        "volScalarField",
        "epsilon",
        "[0 2 -3 0 0 0 0]",
        "14.855",
        "type fixedValue; value uniform 14.855;",
        "type epsilonWallFunction; value uniform 14.855;",
        "type zeroGradient;",
    ),
    "0/nut": field(
        "volScalarField",
        "nut",
        "[0 2 -1 0 0 0 0]",
        "0",
        "type calculated; value uniform 0;",
        "type nutkWallFunction; value uniform 0;",
        "type calculated; value uniform 0;",
    ),
}


def setup() -> None:
    for k in LEVELS:
        case = BUILD / name(k)
        if case.exists():
            shutil.rmtree(case)
        files = {
            "system/blockMeshDict": block_mesh(k),
            "system/controlDict": CONTROL,
            "system/fvSchemes": SCHEMES,
            "system/fvSolution": SOLUTION,
            "constant/transportProperties": TRANSPORT,
            "constant/turbulenceProperties": TURBULENCE,
            **FIELDS,
        }
        for rel, text in files.items():
            path = case / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        print(f"{name(k)}: {total_cells(k)} cells")
    print(f"wrote {len(LEVELS)} cases under {BUILD}")


def _owner_header(src: Path, dst: Path) -> None:
    lines = src.read_text().splitlines(keepends=True)
    end = next(i for i, line in enumerate(lines) if line.startswith("// * *"))
    dst.write_text("".join(lines[: end + 1]) + "// (cut after the header: only nCells is read)\n")


def collect() -> None:
    for k in LEVELS:
        src = BUILD / name(k)
        dst = HERE / name(k)
        if dst.exists():
            shutil.rmtree(dst)
        # multiFieldValue also writes its two inputs under pressureDrop:inlet and
        # pressureDrop:outlet; a ':' in a path cannot be checked out on Windows, and
        # pressureDrop/0/multiFieldValue.dat holds the differences that are used.
        ignore = shutil.ignore_patterns("polyMesh", "*:*")
        for sub in ("system", "constant", "0", "postProcessing"):
            shutil.copytree(src / sub, dst / sub, ignore=ignore)
        mesh = dst / "constant" / "polyMesh"
        mesh.mkdir()
        shutil.copy2(src / "constant/polyMesh/boundary", mesh / "boundary")
        _owner_header(src / "constant/polyMesh/owner", mesh / "owner")
        for log in ("log.blockMesh", "log.checkMesh", "log.simpleFoam"):
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
