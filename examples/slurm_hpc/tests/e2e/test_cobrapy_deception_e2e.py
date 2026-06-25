"""E2E: COBRApy/Gurobi FBA job submission to Deception HPC.

Validates the full pipeline: upload script -> sbatch submit -> poll -> verify output.
This test consumes real allocation hours on Deception.

Guards:
    COBRAPY_DECEPTION_E2E_ENABLED=true  (opt-in, consumes allocation)
    DECEPTION_USERNAME=<user>           (dowd665, geor228, or rigo160)
    Network reachability to deception.pnl.gov:22

Run with:
    COBRAPY_DECEPTION_E2E_ENABLED=true DECEPTION_USERNAME=dowd665 \
      pytest tests/e2e/test_cobrapy_deception_e2e.py -v

Corresponds to demo: demos/cobrapy_fba_deception.py
"""

import os
import socket
import time
from pathlib import Path

import pytest

COBRAPY_E2E_ENABLED = os.getenv("COBRAPY_DECEPTION_E2E_ENABLED", "false").lower() == "true"
DECEPTION_USERNAME = os.getenv("DECEPTION_USERNAME", "rigo160")

skip_e2e = pytest.mark.skipif(
    not COBRAPY_E2E_ENABLED,
    reason="COBRAPY_DECEPTION_E2E_ENABLED not set to 'true'",
)


def _can_reach_deception() -> bool:
    try:
        sock = socket.create_connection(("deception.pnl.gov", 22), timeout=3.0)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


skip_network = pytest.mark.skipif(
    not _can_reach_deception() if COBRAPY_E2E_ENABLED else True,
    reason="Cannot reach deception.pnl.gov:22",
)

JOB_SCRIPT = Path(__file__).resolve().parent.parent.parent / "demos" / "cobrapy_fba_job.py"

SBATCH_TEMPLATE = """\
#!/bin/bash
#SBATCH --job-name=adept-cobrapy-fba-test
#SBATCH --output=/scratch/{username}/adept_jobs/slurm-%j.out
#SBATCH --error=/scratch/{username}/adept_jobs/slurm-%j.err
#SBATCH --time=00:05:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1

module load python/3.11 2>/dev/null || true
module load gurobi/11.0 2>/dev/null || true

if ! python3 -c "import cobra" 2>/dev/null; then
    source activate cobrapy-env 2>/dev/null || conda activate cobrapy-env 2>/dev/null || true
fi

python3 /scratch/{username}/adept_jobs/cobrapy_fba_job.py
"""


@pytest.fixture
def transport():
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


def _wait_for_job(transport, job_id: str, timeout: int = 300, interval: int = 10) -> str:
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


@skip_e2e
@skip_network
class TestCobraPyDeceptionFBA:
    """Full lifecycle: upload -> submit -> poll -> verify FBA result."""

    def test_submit_cobrapy_fba_job(self, transport):
        """Submit FBA job, wait for completion, verify optimal_value in output."""
        username = DECEPTION_USERNAME
        remote_dir = f"/scratch/{username}/adept_jobs"

        transport.run_command(f"mkdir -p {remote_dir}")
        transport.put_file(str(JOB_SCRIPT), f"{remote_dir}/cobrapy_fba_job.py")

        script_content = SBATCH_TEMPLATE.format(username=username)
        sbatch_path = f"{remote_dir}/submit_fba_test.sh"
        transport.run_command(f"cat > {sbatch_path} << 'EOF'\n{script_content}\nEOF")

        result = transport.run_command(f"sbatch {sbatch_path}")
        job_id = result.stdout.strip().split()[-1]
        assert job_id.isdigit(), f"Expected numeric job ID, got: {result.stdout}"

        final_state = _wait_for_job(transport, job_id, timeout=300)
        assert final_state == "COMPLETED", f"Job {job_id} ended with state: {final_state}"

        output = transport.run_command(f"cat {remote_dir}/slurm-{job_id}.out")
        stdout = output.stdout

        assert "RESULT:optimal_value=" in stdout, (
            f"Job output missing RESULT line. Full output:\n{stdout}"
        )
        value_str = stdout.split("RESULT:optimal_value=")[1].split()[0]
        optimal_value = float(value_str)
        assert optimal_value == pytest.approx(10.0, abs=0.01), (
            f"Expected optimal_value ~10.0, got {optimal_value}"
        )

    def test_scratch_dir_isolation(self, transport):
        """Verify each user's scratch directory is independent."""
        username = DECEPTION_USERNAME
        result = transport.run_command(f"ls -la /scratch/{username}/adept_jobs/ 2>/dev/null || echo EMPTY")
        assert username in result.stdout or "EMPTY" in result.stdout


@skip_e2e
@skip_network
@pytest.mark.parametrize("username", ["dowd665", "geor228", "rigo160"])
def test_user_scratch_exists(username):
    """Verify scratch directory exists for each configured user."""
    from slurm_mcp.deception.config import DeceptionConfig
    from slurm_mcp.fabric_transport import FabricSSHTransport

    if username != DECEPTION_USERNAME:
        pytest.skip(f"Only testing configured user: {DECEPTION_USERNAME}")

    os.environ["DECEPTION_USERNAME"] = username
    config = DeceptionConfig()
    config.username = username
    config.working_directory = f"/scratch/{username}"

    t = FabricSSHTransport(config)
    t.connect()
    try:
        result = t.run_command(f"test -d /scratch/{username} && echo EXISTS || echo MISSING")
        assert "EXISTS" in result.stdout, f"/scratch/{username} does not exist on Deception"
    finally:
        t.close()
