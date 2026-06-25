#!/usr/bin/env python3
"""Demo: Full compute lifecycle on Deception HPC via ADEPT MCP tools.

Demonstrates the complete ADEPT compute lifecycle:
  Stage 0: Pre-flight — provision workspace directories, validate environment
  Stage 3: Build SIF — build Apptainer container on Deception (if needed)
  Stage 4: Run FBA — execute COBRApy/Gurobi optimization inside the SIF

Stages are chained via Slurm --dependency=afterok for automatic sequencing.

Usage:
    # Full lifecycle (pre-flight + build + run) as Paul:
    python demos/cobrapy_fba_deception.py --user rigo160 --build-sif

    # Pre-flight only (validate workspace/environment):
    python demos/cobrapy_fba_deception.py --user rigo160 --preflight

    # Skip pre-flight (workspace already provisioned):
    python demos/cobrapy_fba_deception.py --user dowd665 --skip-preflight

    # Force rebuild SIF (even if cached):
    python demos/cobrapy_fba_deception.py --user geor228 --build-sif --force-rebuild

    # Run only (SIF already built):
    python demos/cobrapy_fba_deception.py --user rigo160

    # Dry-run (print sbatch scripts without submitting):
    python demos/cobrapy_fba_deception.py --user rigo160 --build-sif --dry-run

    # Via environment variable:
    DECEPTION_USERNAME=geor228 python demos/cobrapy_fba_deception.py --build-sif

Prerequisites:
    1. Generate SSH keypair (one-time per user):
         ssh-keygen -t ed25519 -f ssh_keys/<user>/slurm.id_ed25519.deception.pnl.gov \
           -N "" -C "adept-mcp@deception"
    2. Copy public key to Deception:
         ssh-copy-id -i ssh_keys/<user>/slurm.id_ed25519.deception.pnl.gov.pub \
           <user>@deception.pnl.gov
       Or manually append to ~/.ssh/authorized_keys on Deception.
    3. Network access to deception.pnl.gov:22 from this host
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("adept.deception_demo")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "slurm_mcp_server"))

from slurm_mcp.deception.config import DeceptionConfig
from slurm_mcp.fabric_transport import FabricSSHTransport


DEMOS_DIR = Path(__file__).resolve().parent
PREFLIGHT_SCRIPT = DEMOS_DIR / "preflight" / "preflight_workspace.sh"
BUILD_SIF_SCRIPT = DEMOS_DIR / "apptainer" / "build_sif.sh"
RUN_FBA_SCRIPT = DEMOS_DIR / "apptainer" / "run_fba.sh"
COBRAPY_DEF = DEMOS_DIR / "apptainer" / "cobrapy.def"
REQUIREMENTS_TXT = DEMOS_DIR / "apptainer" / "requirements.txt"
JOB_SCRIPT = DEMOS_DIR / "cobrapy_fba_job.py"


def parse_args():
    parser = argparse.ArgumentParser(
        description="ADEPT Compute Lifecycle Demo: COBRApy/Gurobi FBA on Deception HPC"
    )
    parser.add_argument(
        "--user",
        default=os.getenv("DECEPTION_USERNAME", "rigo160"),
        help="Deception username (default: $DECEPTION_USERNAME or rigo160)",
    )
    parser.add_argument(
        "--partition",
        default="",
        help="Slurm partition (default: cluster default)",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Run pre-flight only (provision workspace, validate environment)",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip pre-flight check (assume workspace already provisioned)",
    )
    parser.add_argument(
        "--build-sif",
        action="store_true",
        help="Include SIF build stage (required on first run)",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Force SIF rebuild even if cached",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Path to SBML XML model file (uploaded to workspace/inputs/, passed to job script)",
    )
    parser.add_argument(
        "--script",
        default="",
        help="Path to custom Python job script (replaces default cobrapy_fba_job.py)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=10,
        help="Seconds between job status polls (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print job scripts without submitting",
    )
    return parser.parse_args()


def create_transport(username: str) -> FabricSSHTransport:
    """Create SSH transport for the given Deception user."""
    os.environ["DECEPTION_USERNAME"] = username
    config = DeceptionConfig()
    config.username = username
    config.working_directory = f"/scratch/{username}"
    return FabricSSHTransport(config)


def upload_file(transport: FabricSSHTransport, local_path: Path, remote_path: str):
    """Upload a local file to Deception."""
    transport.put_file(str(local_path), remote_path)
    logger.debug("Uploaded %s -> %s", local_path.name, remote_path)


def submit_job(transport: FabricSSHTransport, sbatch_cmd: str) -> str:
    """Submit a Slurm job and return the job ID."""
    result = transport.run_command(sbatch_cmd)
    job_id = result.stdout.strip().split()[-1]
    return job_id


def poll_job(transport: FabricSSHTransport, job_id: str, label: str, interval: int) -> str:
    """Poll job status until terminal state. Returns final state."""
    terminal_states = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY"}
    logger.info("Polling %s (job %s) every %ds...", label, job_id, interval)

    while True:
        result = transport.run_command(
            f"sacct -j {job_id} --format=JobID,State,ExitCode --noheader --parsable2"
        )
        lines = [l for l in result.stdout.strip().splitlines()
                 if ".batch" not in l and ".extern" not in l]
        if lines:
            parts = lines[0].split("|")
            state = parts[1].strip() if len(parts) > 1 else "UNKNOWN"
            if state in terminal_states:
                logger.info("Job %s final state: %s", job_id, state)
                return state
            logger.debug("Job %s state: %s", job_id, state)

        time.sleep(interval)


def needs_preflight(transport: FabricSSHTransport, username: str) -> bool:
    """Check if workspace pre-flight has already run successfully."""
    report_path = f"/people/{username}/adept-workspace/.adept-preflight.json"
    result = transport.run_command(f"cat {report_path} 2>/dev/null || echo MISSING")
    return "MISSING" in result.stdout


def sif_exists(transport: FabricSSHTransport, username: str) -> bool:
    """Check if the Apptainer SIF is already built."""
    sif_path = f"/scratch/{username}/containers/adept-cobrapy.sif"
    result = transport.run_command(f"test -f {sif_path} && echo EXISTS || echo MISSING")
    return "EXISTS" in result.stdout


def run_preflight(transport: FabricSSHTransport, username: str, args) -> str:
    """Stage 0: Submit pre-flight workspace provisioning job."""
    logger.info("[Stage 0] Pre-flight: Provisioning workspace...")
    remote_dir = f"/scratch/{username}/adept_jobs"

    transport.run_command(f"mkdir -p {remote_dir}")

    logger.info("Uploading preflight script...")
    upload_file(transport, PREFLIGHT_SCRIPT, f"{remote_dir}/preflight_workspace.sh")

    if args.dry_run:
        logger.info("[DRY RUN] Would submit: sbatch preflight_workspace.sh")
        return "DRY_RUN"

    partition_flag = f"--partition={args.partition}" if args.partition else ""
    job_id = submit_job(transport, f"sbatch {partition_flag} {remote_dir}/preflight_workspace.sh")
    logger.info("Submitted pre-flight job: %s", job_id)

    state = poll_job(transport, job_id, "pre-flight", args.poll_interval)
    if state != "COMPLETED":
        logger.error("Pre-flight failed with state: %s", state)
        sys.exit(1)

    report_path = f"/people/{username}/adept-workspace/.adept-preflight.json"
    result = transport.run_command(f"cat {report_path} 2>/dev/null || echo 'Report not found'")
    logger.info("Pre-flight report:\n%s", result.stdout)

    return job_id


def run_build_sif(transport: FabricSSHTransport, username: str, args, depends_on: str = None) -> str:
    """Stage 3: Submit Apptainer SIF build job."""
    logger.info("[Stage 3] Build: Compiling Apptainer SIF on Deception...")
    remote_dir = f"/scratch/{username}/adept_jobs"

    logger.info("Uploading build artifacts...")
    upload_file(transport, BUILD_SIF_SCRIPT, f"{remote_dir}/build_sif.sh")
    upload_file(transport, COBRAPY_DEF, f"{remote_dir}/cobrapy.def")
    upload_file(transport, REQUIREMENTS_TXT, f"{remote_dir}/requirements.txt")

    if args.dry_run:
        dep_flag = f" --dependency=afterok:{depends_on}" if depends_on else ""
        logger.info("[DRY RUN] Would submit: sbatch%s build_sif.sh", dep_flag)
        return "DRY_RUN"

    dep_flag = f"--dependency=afterok:{depends_on}" if depends_on and depends_on != "DRY_RUN" else ""
    partition_flag = f"--partition={args.partition}" if args.partition else ""

    if args.force_rebuild:
        sbatch_cmd = f"export FORCE_REBUILD=true && sbatch {dep_flag} {partition_flag} {remote_dir}/build_sif.sh"
    else:
        sbatch_cmd = f"sbatch {dep_flag} {partition_flag} {remote_dir}/build_sif.sh".strip()

    job_id = submit_job(transport, sbatch_cmd)
    logger.info("Submitted build job: %s", job_id)

    state = poll_job(transport, job_id, "SIF build", args.poll_interval)
    if state != "COMPLETED":
        logger.error("SIF build failed with state: %s", state)
        result = transport.run_command(f"cat /scratch/{username}/adept_jobs/build-sif-{job_id}.out 2>/dev/null | tail -20")
        logger.error("Last 20 lines of build log:\n%s", result.stdout)
        sys.exit(1)

    logger.info("SIF build completed successfully")
    return job_id


def run_fba(transport: FabricSSHTransport, username: str, args, depends_on: str = None) -> int:
    """Stage 4: Submit FBA execution job inside the SIF."""
    logger.info("[Stage 4] Execute: Running COBRApy/Gurobi FBA...")
    remote_dir = f"/scratch/{username}/adept_jobs"

    logger.info("Uploading execution artifacts...")
    upload_file(transport, RUN_FBA_SCRIPT, f"{remote_dir}/run_fba.sh")

    # Upload job script (custom or default)
    if args.script:
        custom_script = Path(args.script)
        if not custom_script.exists():
            logger.error("Custom script not found: %s", args.script)
            sys.exit(1)
        upload_file(transport, custom_script, f"{remote_dir}/cobrapy_fba_job.py")
    else:
        upload_file(transport, JOB_SCRIPT, f"{remote_dir}/cobrapy_fba_job.py")

    # Upload model file (explicit --model, or bundled example)
    model_remote_path = ""
    if args.model:
        model_file = Path(args.model)
        if not model_file.exists():
            logger.error("Model file not found: %s", args.model)
            sys.exit(1)
        workspace_inputs = f"/people/{username}/adept-workspace/inputs"
        transport.run_command(f"mkdir -p {workspace_inputs}")
        model_remote_path = f"{workspace_inputs}/{model_file.name}"
        upload_file(transport, model_file, model_remote_path)
    else:
        # Upload bundled example model for use with default script
        model_file = DEMOS_DIR / "models" / "simple_pathway.xml"
        if model_file.exists():
            workspace_inputs = f"/people/{username}/adept-workspace/inputs"
            transport.run_command(f"mkdir -p {workspace_inputs}")
            upload_file(transport, model_file, f"{workspace_inputs}/simple_pathway.xml")

    if args.dry_run:
        dep_flag = f" --dependency=afterok:{depends_on}" if depends_on else ""
        logger.info("[DRY RUN] Would submit: sbatch%s run_fba.sh", dep_flag)
        return 0

    dep_flag = f"--dependency=afterok:{depends_on}" if depends_on and depends_on != "DRY_RUN" else ""
    partition_flag = f"--partition={args.partition}" if args.partition else ""

    # Pass model path as env var if specified
    env_prefix = ""
    if model_remote_path:
        env_prefix = f"export ADEPT_MODEL_PATH={model_remote_path} && "

    job_id = submit_job(transport, f"{env_prefix}sbatch {dep_flag} {partition_flag} {remote_dir}/run_fba.sh")
    logger.info("Submitted FBA job: %s", job_id)

    state = poll_job(transport, job_id, "FBA execution", args.poll_interval)

    output_path = f"/scratch/{username}/adept_jobs/fba-{job_id}.out"
    result = transport.run_command(f"cat {output_path}")
    stdout = result.stdout

    logger.info("=== Job Output ===\n%s", stdout)

    if state == "COMPLETED" and "RESULT:optimal_value=" in stdout:
        value = stdout.split("RESULT:optimal_value=")[1].split()[0]
        logger.info("Optimal biomass flux: %s — SUCCESS", value)
        return 0
    elif state == "COMPLETED":
        logger.warning("Job completed but no RESULT line found in output")
        return 1
    else:
        logger.error("Job ended with state: %s", state)
        err_path = f"/scratch/{username}/adept_jobs/fba-{job_id}.err"
        err_result = transport.run_command(f"cat {err_path} 2>/dev/null || echo '(no stderr)'")
        if err_result.stdout.strip() and err_result.stdout.strip() != "(no stderr)":
            logger.error("Stderr:\n%s", err_result.stdout)
        return 1


def main():
    args = parse_args()
    username = args.user

    logger.info("ADEPT Compute Lifecycle Demo")
    logger.info("  Cluster:       deception.pnl.gov")
    logger.info("  User:          %s", username)
    logger.info("  Partition:     %s", args.partition or "(default)")
    logger.info("  Build SIF:     %s", args.build_sif)
    logger.info("  Force rebuild: %s", args.force_rebuild)

    if args.dry_run:
        logger.info("*** DRY RUN MODE — no jobs will be submitted ***")

    logger.info("Connecting to Deception...")
    transport = create_transport(username)
    transport.connect()

    last_job_id = None

    # Stage 0: Pre-flight
    if args.preflight or (not args.skip_preflight and needs_preflight(transport, username)):
        last_job_id = run_preflight(transport, username, args)
        if args.preflight:
            logger.info("Pre-flight complete. Use --skip-preflight on subsequent runs.")
            return 0
    elif args.skip_preflight:
        logger.info("[Stage 0] Pre-flight: SKIPPED (--skip-preflight)")
    else:
        logger.info("[Stage 0] Pre-flight: SKIPPED (workspace already provisioned)")

    # Stage 3: Build SIF (if requested or needed)
    if args.build_sif or args.force_rebuild:
        last_job_id = run_build_sif(transport, username, args, depends_on=last_job_id)
    elif not sif_exists(transport, username):
        logger.info("[Stage 3] Build: SIF not found — running build automatically...")
        last_job_id = run_build_sif(transport, username, args, depends_on=last_job_id)
    else:
        logger.info("[Stage 3] Build: SKIPPED (SIF already cached)")

    # Stage 4: Run FBA
    exit_code = run_fba(transport, username, args, depends_on=last_job_id)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
