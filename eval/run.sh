#!/bin/bash
# Mesh and solve every case under eval/build/<run>/, in parallel, with the solver each case's
# controlDict names. Run inside the pinned container from the repository root (see
# studies/README.md):
#   bash eval/run.sh
source /usr/lib/openfoam/openfoam2512/etc/bashrc
set -euo pipefail
cd "$(dirname "$0")/build"
for case in */n*/; do
    (
        cd "$case"
        app=$(foamDictionary -entry application -value system/controlDict)
        blockMesh > log.blockMesh 2>&1
        checkMesh > log.checkMesh 2>&1
        "$app" > "log.$app" 2>&1
        echo "${case%/}: $app, $(grep -c '^Time =' "log.$app") steps"
    ) &
done
wait
