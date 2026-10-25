#!/bin/bash
# Mesh and solve every level in build/, in parallel, serial solver per level.
# Run inside the pinned container from the repository root (see studies/README.md):
#   bash studies/duct/run.sh
source /usr/lib/openfoam/openfoam2512/etc/bashrc
set -euo pipefail
cd "$(dirname "$0")/build"
for case in n*/; do
    (
        cd "$case"
        blockMesh > log.blockMesh 2>&1
        checkMesh > log.checkMesh 2>&1
        simpleFoam > log.simpleFoam 2>&1
        echo "${case%/}: $(grep -c '^Time =' log.simpleFoam) iterations"
    ) &
done
wait
