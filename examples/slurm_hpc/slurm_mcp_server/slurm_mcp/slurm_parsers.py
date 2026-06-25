"""Shared Slurm CLI output parsers.

Used by FabricSSHTransport for both Deception and Tahoma clusters.
Parses output from sbatch, squeue, sinfo, sacct, and scancel commands.
"""

import json
import re
from typing import Any, Dict, List, Optional


def parse_sbatch_output(stdout: str) -> str:
    """Extract job ID from sbatch output.

    Expected format: "Submitted batch job 12345"
    """
    match = re.search(r"Submitted batch job (\d+)", stdout)
    if match:
        return match.group(1)
    raise ValueError(f"Could not parse sbatch output: {stdout.strip()}")


def parse_squeue_json(stdout: str) -> List[Dict[str, Any]]:
    """Parse squeue --json output into job list."""
    data = json.loads(stdout)
    return data.get("jobs", [])


def parse_sinfo_json(stdout: str) -> Dict[str, Any]:
    """Parse sinfo --json output into cluster info."""
    return json.loads(stdout)


def parse_sacct_json(stdout: str) -> List[Dict[str, Any]]:
    """Parse sacct --json output into job history."""
    data = json.loads(stdout)
    return data.get("jobs", [])


def parse_scancel_output(stdout: str, stderr: str) -> bool:
    """Determine if scancel succeeded (empty output = success)."""
    return not stderr.strip()


def build_sbatch_options(
    job_name: str,
    partition: Optional[str] = None,
    account: Optional[str] = None,
    nodes: int = 1,
    ntasks: int = 1,
    cpus_per_task: int = 1,
    memory: Optional[str] = None,
    time_limit: str = "01:00:00",
    working_directory: Optional[str] = None,
    array: Optional[str] = None,
    output_path: Optional[str] = None,
    error_path: Optional[str] = None,
) -> str:
    """Build sbatch command-line options string.

    CLI --output/--error override any #SBATCH directives in the script.
    """
    opts = [f"--job-name={job_name}"]
    if partition:
        opts.append(f"--partition={partition}")
    if account:
        opts.append(f"--account={account}")
    opts.append(f"--nodes={nodes}")
    opts.append(f"--ntasks={ntasks}")
    opts.append(f"--cpus-per-task={cpus_per_task}")
    if memory:
        opts.append(f"--mem={memory}")
    opts.append(f"--time={time_limit}")
    if working_directory:
        opts.append(f"--chdir={working_directory}")
    if array:
        opts.append(f"--array={array}")
    if output_path:
        opts.append(f"--output={output_path}")
    if error_path:
        opts.append(f"--error={error_path}")
    return " ".join(opts)
