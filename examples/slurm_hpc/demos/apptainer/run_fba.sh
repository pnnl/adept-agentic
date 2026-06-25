#!/bin/bash
#SBATCH --job-name=adept-cobrapy-fba
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1

# ADEPT COBRApy/Gurobi FBA Execution Job
# Runs an arbitrary Python script inside the pre-built Apptainer SIF.
#
# The script can be:
#   - A hardcoded demo (cobrapy_fba_job.py)
#   - Agent-generated code (produced by Sandbox MCP, submitted here)
#   - Any COBRApy/Gurobi optimization script
#
# Prerequisites:
#   - SIF exists at /scratch/<user>/containers/adept-cobrapy.sif (built by build_sif.sh)
#   - Target script uploaded to /scratch/<user>/adept_jobs/ or /people/<user>/adept-workspace/inputs/
#   - Gurobi license accessible at /opt/gurobi/gurobi.lic (or via token server)
#
# Usage:
#   sbatch --dependency=afterok:<build_jobid> run_fba.sh                    # default script
#   sbatch run_fba.sh /people/$USER/adept-workspace/inputs/my_analysis.py   # custom script
#   sbatch run_fba.sh /scratch/$USER/adept_jobs/agent_generated.py          # agent-generated
#
# Environment variables:
#   ADEPT_JOB_SCRIPT  — path to Python script (overrides positional arg)
#   ADEPT_MODEL_PATH  — path to SBML .xml model file (passed as $1 to script)

set -euo pipefail
USERNAME=$(whoami)
JOBS_DIR="/scratch/${USERNAME}/adept_jobs"
SIF_PATH="/scratch/${USERNAME}/containers/adept-cobrapy.sif"
WORKSPACE="/people/${USERNAME}/adept-workspace"

# Resolve script path: env var > positional arg > default
JOB_SCRIPT="${ADEPT_JOB_SCRIPT:-${1:-${JOBS_DIR}/cobrapy_fba_job.py}}"
MODEL_PATH="${ADEPT_MODEL_PATH:-${2:-}}"

echo "=== ADEPT COBRApy/Gurobi FBA Execution ==="
echo "User: ${USERNAME}"
echo "Host: $(hostname)"
echo "Date: $(date -Iseconds)"
echo "SIF:  ${SIF_PATH}"
echo "Script: ${JOB_SCRIPT}"
echo "Model:  ${MODEL_PATH:-'(none — script uses built-in model)'}"
echo ""

# Validate SIF exists
if [ ! -f "${SIF_PATH}" ]; then
    echo "ERROR: SIF not found at ${SIF_PATH}"
    echo "Run build_sif.sh first (or use --dependency=afterok:<build_jobid>)"
    echo "RESULT:fba=FAIL"
    echo "RESULT:reason=sif_missing"
    exit 1
fi

# Validate job script exists
if [ ! -f "${JOB_SCRIPT}" ]; then
    echo "ERROR: Job script not found: ${JOB_SCRIPT}"
    echo "RESULT:fba=FAIL"
    echo "RESULT:reason=script_missing"
    exit 1
fi

# Validate model file if specified
if [ -n "${MODEL_PATH}" ] && [ ! -f "${MODEL_PATH}" ]; then
    echo "ERROR: Model file not found: ${MODEL_PATH}"
    echo "RESULT:fba=FAIL"
    echo "RESULT:reason=model_missing"
    exit 1
fi

# Determine Gurobi license bind path
GUROBI_BIND=""
if [ -d "/opt/gurobi" ]; then
    GUROBI_BIND="--bind /opt/gurobi:/opt/gurobi:ro"
    echo "Gurobi license: /opt/gurobi (bind-mounted)"
elif [ -n "${GRB_LICENSE_FILE:-}" ] && [ -f "${GRB_LICENSE_FILE}" ]; then
    GUROBI_BIND="--bind $(dirname ${GRB_LICENSE_FILE}):/opt/gurobi:ro"
    echo "Gurobi license: ${GRB_LICENSE_FILE} (bind-mounted)"
else
    echo "WARNING: No Gurobi license directory found — solver may use token server"
fi

echo ""
echo "--- Executing FBA inside SIF ---"
echo ""

# Build script arguments (pass model path if provided)
SCRIPT_ARGS=""
if [ -n "${MODEL_PATH}" ]; then
    SCRIPT_ARGS="${MODEL_PATH}"
fi

apptainer exec \
    ${GUROBI_BIND} \
    --bind "${JOBS_DIR}:${JOBS_DIR}:ro" \
    --bind "${WORKSPACE}:${WORKSPACE}:rw" \
    "${SIF_PATH}" \
    python3 "${JOB_SCRIPT}" ${SCRIPT_ARGS}

EXIT_CODE=$?

echo ""
echo "--- Execution complete (exit code: ${EXIT_CODE}) ---"

# Copy results to persistent workspace
if [ ${EXIT_CODE} -eq 0 ]; then
    RESULT_FILE="${WORKSPACE}/outputs/fba_result_${SLURM_JOB_ID:-local}.json"
    cat > "${RESULT_FILE}" << RESULT_EOF
{
  "timestamp": "$(date -Iseconds)",
  "hostname": "$(hostname)",
  "slurm_job_id": "${SLURM_JOB_ID:-unknown}",
  "sif_path": "${SIF_PATH}",
  "job_script": "${JOB_SCRIPT}",
  "exit_code": ${EXIT_CODE},
  "status": "success"
}
RESULT_EOF
    echo "Result metadata: ${RESULT_FILE}"
fi

exit ${EXIT_CODE}
