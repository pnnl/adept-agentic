"""E2E: Cross-backend compute lifecycle parity test.

Validates that ADEPT's two execution backends (Sandbox MCP local Docker,
Slurm MCP remote Deception HPC) produce identical results from the same
COBRApy/Gurobi optimization code.

This proves runtime parity: what runs in local sandbox produces the same
scientific result on HPC, guaranteeing reproducibility across environments.

Compute lifecycle stages tested:
    Stage 0: Pre-flight workspace provisioning (Slurm job)
    Stage 1: Local validation via sandbox (Docker container)
    Stage 3: SIF build on Deception (Slurm job)
    Stage 4: FBA execution inside SIF (Slurm job with dependency chain)

Guards:
    COBRAPY_DECEPTION_E2E_ENABLED=true  (opt-in, consumes HPC allocation)
    SANDBOX_MCP_RUNNING=true            (opt-in, requires sandbox container)
    DECEPTION_USERNAME=<user>           (rigo160, dowd665, or geor228)
    Network reachability to deception.pnl.gov:22

Run with:
    COBRAPY_DECEPTION_E2E_ENABLED=true SANDBOX_MCP_RUNNING=true \
      DECEPTION_USERNAME=rigo160 \
      pytest tests/e2e/test_compute_lifecycle_parity.py -v
"""

import json
import logging
import os
import socket
import time
from pathlib import Path

import pytest

logger = logging.getLogger("adept.test.compute_lifecycle")

# --- Guards ---

DECEPTION_E2E = os.getenv("COBRAPY_DECEPTION_E2E_ENABLED", "false").lower() == "true"
SANDBOX_RUNNING = os.getenv("SANDBOX_MCP_RUNNING", "false").lower() == "true"
DECEPTION_USERNAME = os.getenv("DECEPTION_USERNAME", "rigo160")


def _can_reach_deception() -> bool:
    try:
        sock = socket.create_connection(("deception.pnl.gov", 22), timeout=3.0)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


skip_deception = pytest.mark.skipif(
    not DECEPTION_E2E,
    reason="COBRAPY_DECEPTION_E2E_ENABLED not set to 'true'",
)

skip_sandbox = pytest.mark.skipif(
    not SANDBOX_RUNNING,
    reason="SANDBOX_MCP_RUNNING not set to 'true'",
)

skip_network = pytest.mark.skipif(
    not _can_reach_deception() if DECEPTION_E2E else True,
    reason="Cannot reach deception.pnl.gov:22",
)


# --- Paths ---

DEMOS_DIR = Path(__file__).resolve().parent.parent.parent / "demos"
JOB_SCRIPT = DEMOS_DIR / "cobrapy_fba_job.py"
PREFLIGHT_SCRIPT = DEMOS_DIR / "preflight" / "preflight_workspace.sh"
BUILD_SIF_SCRIPT = DEMOS_DIR / "apptainer" / "build_sif.sh"
RUN_FBA_SCRIPT = DEMOS_DIR / "apptainer" / "run_fba.sh"
COBRAPY_DEF = DEMOS_DIR / "apptainer" / "cobrapy.def"
REQUIREMENTS_TXT = DEMOS_DIR / "apptainer" / "requirements.txt"
MODEL_FILE = DEMOS_DIR / "models" / "simple_pathway.xml"


# --- Fixtures ---

@pytest.fixture
def deception_transport():
    """Create SSH transport for the configured Deception user."""
    from slurm_mcp.deception.config import DeceptionConfig
    from slurm_mcp.fabric_transport import FabricSSHTransport

    os.environ["DECEPTION_USERNAME"] = DECEPTION_USERNAME
    config = DeceptionConfig()
    config.username = DECEPTION_USERNAME
    config.working_directory = f"/scratch/{DECEPTION_USERNAME}"

    t = FabricSSHTransport(config)
    t.connect()
    yield t
    t.close()


def _wait_for_job(transport, job_id: str, timeout: int = 600, interval: int = 10) -> str:
    """Poll until terminal state or timeout."""
    terminal = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY"}
    deadline = time.time() + timeout

    while time.time() < deadline:
        result = transport.run_command(
            f"sacct -j {job_id} --format=JobID,State,ExitCode --noheader --parsable2"
        )
        lines = [l for l in result.stdout.strip().splitlines()
                 if ".batch" not in l and ".extern" not in l]
        if lines:
            parts = lines[0].split("|")
            state = parts[1].strip() if len(parts) > 1 else "UNKNOWN"
            if state in terminal:
                return state
        time.sleep(interval)

    pytest.fail(f"Job {job_id} did not reach terminal state within {timeout}s")


# --- Stage 0: Pre-flight ---

@skip_deception
@skip_network
class TestPreflightWorkspace:
    """Stage 0: Validate workspace provisioning via Slurm job."""

    def test_preflight_provisions_workspace(self, deception_transport):
        """Submit preflight job, verify directories and report created."""
        username = DECEPTION_USERNAME
        remote_dir = f"/scratch/{username}/adept_jobs"

        deception_transport.run_command(f"mkdir -p {remote_dir}")
        deception_transport.put_file(str(PREFLIGHT_SCRIPT), f"{remote_dir}/preflight_workspace.sh")

        result = deception_transport.run_command(f"sbatch {remote_dir}/preflight_workspace.sh")
        job_id = result.stdout.strip().split()[-1]
        assert job_id.isdigit(), f"Expected numeric job ID, got: {result.stdout}"

        state = _wait_for_job(deception_transport, job_id, timeout=120)
        assert state == "COMPLETED", f"Pre-flight job {job_id} ended with: {state}"

        # Verify directories exist
        dirs_to_check = [
            f"/scratch/{username}/containers",
            f"/scratch/{username}/adept_jobs",
            f"/scratch/{username}/tmp",
            f"/people/{username}/adept-workspace/inputs",
            f"/people/{username}/adept-workspace/outputs",
            f"/people/{username}/adept-workspace/logs",
        ]
        for d in dirs_to_check:
            check = deception_transport.run_command(f"test -d {d} && echo EXISTS || echo MISSING")
            assert "EXISTS" in check.stdout, f"Directory not created: {d}"

        # Verify report written
        report_path = f"/people/{username}/adept-workspace/.adept-preflight.json"
        report_result = deception_transport.run_command(f"cat {report_path}")
        report = json.loads(report_result.stdout)
        assert report["username"] == username
        assert report["checks_passed"] == report["checks_total"]

    def test_preflight_is_idempotent(self, deception_transport):
        """Running preflight twice produces no errors."""
        username = DECEPTION_USERNAME
        remote_dir = f"/scratch/{username}/adept_jobs"

        result = deception_transport.run_command(f"sbatch {remote_dir}/preflight_workspace.sh")
        job_id = result.stdout.strip().split()[-1]

        state = _wait_for_job(deception_transport, job_id, timeout=120)
        assert state == "COMPLETED", f"Second preflight run failed: {state}"


# --- Stage 1: Sandbox Local Execution ---

@skip_sandbox
class TestSandboxLocalExecution:
    """Stage 1: Validate COBRApy FBA runs correctly in local sandbox."""

    def test_sandbox_cobrapy_fba(self):
        """Execute FBA job script in local Python (simulates sandbox container)."""
        import subprocess

        result = subprocess.run(
            ["python3", str(JOB_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"Script failed:\n{result.stderr}"
        assert "RESULT:optimal_value=" in result.stdout

        value_str = result.stdout.split("RESULT:optimal_value=")[1].split()[0]
        optimal_value = float(value_str)
        assert optimal_value == pytest.approx(10.0, abs=0.01), (
            f"Expected ~10.0, got {optimal_value}"
        )

    def test_sandbox_cobrapy_with_sbml_model(self):
        """Execute FBA with SBML XML model file (same as HPC will use)."""
        import subprocess

        if not MODEL_FILE.exists():
            pytest.skip("Model file not found")

        result = subprocess.run(
            ["python3", str(JOB_SCRIPT), str(MODEL_FILE)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"Script failed:\n{result.stderr}"
        assert "RESULT:optimal_value=" in result.stdout


# --- Stage 3+4: SIF Build + FBA on Deception ---

@skip_deception
@skip_network
class TestDeceptionSIFLifecycle:
    """Stages 3-4: Build SIF on Deception, then run FBA inside it."""

    def test_build_sif_on_deception(self, deception_transport):
        """Submit Apptainer build job, verify SIF produced."""
        username = DECEPTION_USERNAME
        remote_dir = f"/scratch/{username}/adept_jobs"

        # Upload build artifacts
        deception_transport.put_file(str(BUILD_SIF_SCRIPT), f"{remote_dir}/build_sif.sh")
        deception_transport.put_file(str(COBRAPY_DEF), f"{remote_dir}/cobrapy.def")
        deception_transport.put_file(str(REQUIREMENTS_TXT), f"{remote_dir}/requirements.txt")

        # Force rebuild for test isolation
        result = deception_transport.run_command(
            f"export FORCE_REBUILD=true && sbatch {remote_dir}/build_sif.sh"
        )
        job_id = result.stdout.strip().split()[-1]
        assert job_id.isdigit(), f"Expected numeric job ID, got: {result.stdout}"
        logger.info("SIF build job submitted: %s", job_id)

        state = _wait_for_job(deception_transport, job_id, timeout=600)
        assert state == "COMPLETED", f"Build job {job_id} ended with: {state}"

        # Verify SIF exists
        sif_path = f"/scratch/{username}/containers/adept-cobrapy.sif"
        check = deception_transport.run_command(f"test -f {sif_path} && echo EXISTS || echo MISSING")
        assert "EXISTS" in check.stdout, f"SIF not found at {sif_path}"

    def test_run_fba_against_sif(self, deception_transport):
        """Execute FBA inside pre-built SIF, verify optimal_value matches sandbox."""
        username = DECEPTION_USERNAME
        remote_dir = f"/scratch/{username}/adept_jobs"

        # Upload execution artifacts
        deception_transport.put_file(str(RUN_FBA_SCRIPT), f"{remote_dir}/run_fba.sh")
        deception_transport.put_file(str(JOB_SCRIPT), f"{remote_dir}/cobrapy_fba_job.py")

        result = deception_transport.run_command(f"sbatch {remote_dir}/run_fba.sh")
        job_id = result.stdout.strip().split()[-1]
        assert job_id.isdigit(), f"Expected numeric job ID, got: {result.stdout}"
        logger.info("FBA job submitted: %s", job_id)

        state = _wait_for_job(deception_transport, job_id, timeout=300)
        assert state == "COMPLETED", f"FBA job {job_id} ended with: {state}"

        # Retrieve and validate output
        output = deception_transport.run_command(f"cat {remote_dir}/fba-{job_id}.out")
        stdout = output.stdout

        assert "RESULT:optimal_value=" in stdout, (
            f"Job output missing RESULT line:\n{stdout}"
        )
        value_str = stdout.split("RESULT:optimal_value=")[1].split()[0]
        deception_value = float(value_str)

        # Cross-backend parity assertion
        assert deception_value == pytest.approx(10.0, abs=0.01), (
            f"Deception FBA result ({deception_value}) != expected (10.0)"
        )

    def test_dependency_chain_preflight_build_run(self, deception_transport):
        """Full dependency chain: preflight -> build -> run via Slurm afterok."""
        username = DECEPTION_USERNAME
        remote_dir = f"/scratch/{username}/adept_jobs"

        # Upload all artifacts
        deception_transport.put_file(str(PREFLIGHT_SCRIPT), f"{remote_dir}/preflight_workspace.sh")
        deception_transport.put_file(str(BUILD_SIF_SCRIPT), f"{remote_dir}/build_sif.sh")
        deception_transport.put_file(str(RUN_FBA_SCRIPT), f"{remote_dir}/run_fba.sh")
        deception_transport.put_file(str(COBRAPY_DEF), f"{remote_dir}/cobrapy.def")
        deception_transport.put_file(str(REQUIREMENTS_TXT), f"{remote_dir}/requirements.txt")
        deception_transport.put_file(str(JOB_SCRIPT), f"{remote_dir}/cobrapy_fba_job.py")

        # Stage 0: Pre-flight
        r0 = deception_transport.run_command(f"sbatch {remote_dir}/preflight_workspace.sh")
        preflight_id = r0.stdout.strip().split()[-1]
        logger.info("Chain: preflight=%s", preflight_id)

        # Stage 3: Build (depends on preflight)
        r3 = deception_transport.run_command(
            f"sbatch --dependency=afterok:{preflight_id} {remote_dir}/build_sif.sh"
        )
        build_id = r3.stdout.strip().split()[-1]
        logger.info("Chain: build=%s (depends on %s)", build_id, preflight_id)

        # Stage 4: Run (depends on build)
        r4 = deception_transport.run_command(
            f"sbatch --dependency=afterok:{build_id} {remote_dir}/run_fba.sh"
        )
        run_id = r4.stdout.strip().split()[-1]
        logger.info("Chain: run=%s (depends on %s)", run_id, build_id)

        # Wait for final job in chain
        state = _wait_for_job(deception_transport, run_id, timeout=900)
        assert state == "COMPLETED", (
            f"Dependency chain failed at run job {run_id}: {state}"
        )

        # Verify result
        output = deception_transport.run_command(f"cat {remote_dir}/fba-{run_id}.out")
        assert "RESULT:optimal_value=" in output.stdout
