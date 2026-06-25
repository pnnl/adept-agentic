#!/bin/bash
#SBATCH --job-name=adept-build-sif
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G

# ADEPT Apptainer SIF Build Job
# Builds the COBRApy/Gurobi container image on Deception compute nodes.
# Uses --fakeroot (no root/sudo required).
#
# Prerequisites:
#   - preflight_workspace.sh has run (creates /scratch/<user>/containers/)
#   - cobrapy.def and requirements.txt uploaded to /scratch/<user>/adept_jobs/
#
# Usage:
#   sbatch build_sif.sh
#   sbatch --dependency=afterok:<preflight_jobid> build_sif.sh

set -euo pipefail

# Load apptainer module (not in PATH by default on Deception)
module load apptainer 2>/dev/null || true

USERNAME=$(whoami)
JOBS_DIR="/scratch/${USERNAME}/adept_jobs"
SIF_DIR="/scratch/${USERNAME}/containers"
SIF_PATH="${SIF_DIR}/adept-cobrapy.sif"
DEF_PATH="${JOBS_DIR}/cobrapy.def"
REQ_PATH="${JOBS_DIR}/requirements.txt"

echo "=== ADEPT Apptainer SIF Build ==="
echo "User: ${USERNAME}"
echo "Host: $(hostname)"
echo "Date: $(date -Iseconds)"
echo "Definition: ${DEF_PATH}"
echo "Output SIF: ${SIF_PATH}"
echo ""

# Validate inputs exist
if [ ! -f "${DEF_PATH}" ]; then
    echo "ERROR: Definition file not found: ${DEF_PATH}"
    echo "RESULT:build=FAIL"
    exit 1
fi

if [ ! -f "${REQ_PATH}" ]; then
    echo "ERROR: Requirements file not found: ${REQ_PATH}"
    echo "RESULT:build=FAIL"
    exit 1
fi

# Ensure output directory exists
mkdir -p "${SIF_DIR}"

# Set temp directory for Apptainer build cache (avoid /tmp overflow on shared nodes)
export APPTAINER_TMPDIR="/scratch/${USERNAME}/tmp"
mkdir -p "${APPTAINER_TMPDIR}"

# Remove stale SIF if force-rebuild
if [ "${FORCE_REBUILD:-false}" = "true" ] && [ -f "${SIF_PATH}" ]; then
    echo "Force rebuild requested — removing existing SIF"
    rm -f "${SIF_PATH}"
fi

# Skip build if SIF already exists and not forcing
if [ -f "${SIF_PATH}" ] && [ "${FORCE_REBUILD:-false}" != "true" ]; then
    echo "SIF already exists at ${SIF_PATH} ($(stat -c%s "${SIF_PATH}") bytes)"
    echo "Use FORCE_REBUILD=true to rebuild"
    echo ""
    echo "RESULT:build=CACHED"
    echo "RESULT:sif_path=${SIF_PATH}"
    echo "RESULT:sif_size=$(stat -c%s "${SIF_PATH}")"
    exit 0
fi

echo "[1/3] Copying requirements.txt to build context..."
cp "${REQ_PATH}" "$(dirname "${DEF_PATH}")/requirements.txt"

echo "[2/3] Building SIF (this may take 5-15 minutes)..."
echo "  Command: apptainer build --fakeroot ${SIF_PATH} ${DEF_PATH}"
echo ""

apptainer build --fakeroot "${SIF_PATH}" "${DEF_PATH}"

echo ""
echo "[3/3] Verifying SIF..."
if [ -f "${SIF_PATH}" ]; then
    SIF_SIZE=$(stat -c%s "${SIF_PATH}")
    echo "  SIF built successfully: ${SIF_PATH} (${SIF_SIZE} bytes)"

    # Run container self-test
    echo "  Running import test inside SIF..."
    apptainer exec "${SIF_PATH}" python3 -c "import cobra; import gurobipy; print('Import test: PASS')"

    echo ""
    echo "RESULT:build=SUCCESS"
    echo "RESULT:sif_path=${SIF_PATH}"
    echo "RESULT:sif_size=${SIF_SIZE}"
else
    echo "  ERROR: SIF not found after build"
    echo "RESULT:build=FAIL"
    exit 1
fi
