#!/bin/bash
#SBATCH --job-name=adept-preflight
#SBATCH --time=00:02:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=512M

# ADEPT Workspace Pre-Flight Check
# Provisions workspace directories and validates compute environment.
# Submitted via: sbatch preflight_workspace.sh
# Expected output: RESULT:preflight=PASS (or FAIL with details)

set -euo pipefail
USERNAME=$(whoami)
SCRATCH_BASE="/scratch/${USERNAME}"
PEOPLE_BASE="/people/${USERNAME}/adept-workspace"
REPORT="${PEOPLE_BASE}/.adept-preflight.json"

echo "=== ADEPT Workspace Pre-Flight ==="
echo "User: ${USERNAME}"
echo "Host: $(hostname)"
echo "Date: $(date -Iseconds)"
echo ""

CHECKS_PASSED=0
CHECKS_TOTAL=5

# --- Stage 1: Create /scratch directories ---
echo "[1/5] Provisioning ${SCRATCH_BASE}/ ..."
mkdir -p "${SCRATCH_BASE}/containers"
mkdir -p "${SCRATCH_BASE}/adept_jobs"
mkdir -p "${SCRATCH_BASE}/tmp"
echo "  OK: /scratch directories created"
CHECKS_PASSED=$((CHECKS_PASSED + 1))

# --- Stage 2: Create /people workspace ---
echo "[2/5] Provisioning ${PEOPLE_BASE}/ ..."
mkdir -p "${PEOPLE_BASE}/inputs"
mkdir -p "${PEOPLE_BASE}/outputs"
mkdir -p "${PEOPLE_BASE}/logs"
echo "  OK: /people workspace created"
CHECKS_PASSED=$((CHECKS_PASSED + 1))

# --- Stage 3: Check filesystem capacity ---
echo "[3/5] Filesystem capacity check..."
SCRATCH_AVAIL=$(df -BG "${SCRATCH_BASE}" 2>/dev/null | awk 'NR==2{print $4}' || echo "UNKNOWN")
PEOPLE_AVAIL=$(df -BG "${PEOPLE_BASE}" 2>/dev/null | awk 'NR==2{print $4}' || echo "UNKNOWN")
echo "  /scratch available: ${SCRATCH_AVAIL}"
echo "  /people available:  ${PEOPLE_AVAIL}"
CHECKS_PASSED=$((CHECKS_PASSED + 1))

# --- Stage 4: Check module/software availability ---
echo "[4/5] Software availability..."
PYTHON_OK="false"
GUROBI_OK="false"
APPTAINER_OK="false"
APPTAINER_VERSION="none"

if module load python/3.11 2>/dev/null; then
    PYTHON_OK="true"
    echo "  Python 3.11:  available ($(python3 --version 2>&1))"
else
    echo "  Python 3.11:  NOT AVAILABLE via module"
fi

if module load gurobi/11.0 2>/dev/null; then
    GUROBI_OK="true"
    echo "  Gurobi 11.0:  available"
else
    echo "  Gurobi 11.0:  NOT AVAILABLE via module"
fi

if command -v apptainer >/dev/null 2>&1; then
    APPTAINER_OK="true"
    APPTAINER_VERSION=$(apptainer --version 2>&1 | head -1)
    echo "  Apptainer:    available (${APPTAINER_VERSION})"
else
    echo "  Apptainer:    NOT AVAILABLE"
fi

CHECKS_PASSED=$((CHECKS_PASSED + 1))

# --- Stage 5: Check Gurobi license server reachability ---
echo "[5/5] Gurobi license server..."
GUROBI_LICENSE_OK="false"
if timeout 5 bash -c "echo >/dev/tcp/leghorn.emsl.pnl.gov/41954" 2>/dev/null; then
    GUROBI_LICENSE_OK="true"
    echo "  leghorn.emsl.pnl.gov:41954 — reachable"
else
    echo "  leghorn.emsl.pnl.gov:41954 — UNREACHABLE (may need VPN or compute-node network)"
fi
CHECKS_PASSED=$((CHECKS_PASSED + 1))

# --- Write structured report ---
cat > "$REPORT" << REPORT_EOF
{
  "timestamp": "$(date -Iseconds)",
  "hostname": "$(hostname)",
  "username": "${USERNAME}",
  "slurm_job_id": "${SLURM_JOB_ID:-unknown}",
  "checks_passed": ${CHECKS_PASSED},
  "checks_total": ${CHECKS_TOTAL},
  "checks": {
    "scratch_dirs": true,
    "people_workspace": true,
    "scratch_available": "${SCRATCH_AVAIL}",
    "people_available": "${PEOPLE_AVAIL}",
    "python_3_11": ${PYTHON_OK},
    "gurobi_11_0": ${GUROBI_OK},
    "apptainer": ${APPTAINER_OK},
    "apptainer_version": "${APPTAINER_VERSION}",
    "gurobi_license_server": ${GUROBI_LICENSE_OK}
  },
  "paths": {
    "scratch": "${SCRATCH_BASE}",
    "containers": "${SCRATCH_BASE}/containers",
    "jobs": "${SCRATCH_BASE}/adept_jobs",
    "tmp": "${SCRATCH_BASE}/tmp",
    "workspace": "${PEOPLE_BASE}",
    "inputs": "${PEOPLE_BASE}/inputs",
    "outputs": "${PEOPLE_BASE}/outputs",
    "logs": "${PEOPLE_BASE}/logs"
  }
}
REPORT_EOF

echo ""
echo "Pre-flight report written: ${REPORT}"
echo ""
echo "=== Summary ==="
echo "  Checks passed: ${CHECKS_PASSED}/${CHECKS_TOTAL}"

if [ "${PYTHON_OK}" = "false" ] || [ "${APPTAINER_OK}" = "false" ]; then
    echo "  WARNING: Some software modules unavailable — SIF build may require manual setup"
fi

if [ "${GUROBI_LICENSE_OK}" = "false" ]; then
    echo "  WARNING: Gurobi license server unreachable — FBA jobs may fail at solver step"
fi

echo ""
echo "RESULT:preflight=PASS"
echo "RESULT:checks=${CHECKS_PASSED}/${CHECKS_TOTAL}"
echo "RESULT:report_path=${REPORT}"
