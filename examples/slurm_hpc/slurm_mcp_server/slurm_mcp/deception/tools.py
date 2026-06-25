"""MCP tools for PNNL Deception HPC cluster.

Deception is a production Slurm HPC cluster at PNNL accessed via SSH
with key-based passwordless authentication. The SSH private key is
configured in clusters.yaml and used internally by Fabric — key material
is never exposed to the reasoning model.
"""

import functools
import logging
import time
from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from ..app import app
from ..transport import SlurmTransport
from .config import deception_config
from .models import DeceptionJobListFilters, DeceptionJobSubmissionRequest

logger = logging.getLogger(__name__)


def _log_tool_call(func):
    """Decorator that logs tool entry, exit, and elapsed time."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        tool_name = func.__name__
        logger.info("[TOOL] %s called | args=%s kwargs=%s", tool_name, args, kwargs)
        t0 = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.perf_counter() - t0
            status = result.get("status", "?") if isinstance(result, dict) else "?"
            logger.info(
                "[TOOL] %s completed | status=%s elapsed=%.3fs", tool_name, status, elapsed
            )
            logger.debug("[TOOL] %s result=%s", tool_name, result)
            return result
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.error(
                "[TOOL] %s failed | error=%s elapsed=%.3fs", tool_name, exc, elapsed
            )
            raise

    return wrapper

_transport: Optional[SlurmTransport] = None


async def _get_transport() -> SlurmTransport:
    """Get or create the Deception transport instance."""
    global _transport
    if _transport is None:
        if (
            deception_config.transport_mode == "rest"
            and deception_config.rest_api_url
        ):
            from .rest_client import DeceptionRESTTransport

            _transport = DeceptionRESTTransport(deception_config)
        elif deception_config.transport_mode == "auto":
            if deception_config.rest_api_url:
                try:
                    from .rest_client import DeceptionRESTTransport

                    t = DeceptionRESTTransport(deception_config)
                    if await t.ping():
                        _transport = t
                        logger.info("Deception: using REST transport")
                except Exception:
                    pass
            if _transport is None:
                from .ssh_client import FabricSSHTransport

                _transport = FabricSSHTransport(deception_config)
                logger.info("Deception: using SSH transport")
        else:
            from .ssh_client import FabricSSHTransport

            _transport = FabricSSHTransport(deception_config)
    return _transport


@app.tool
@_log_tool_call
async def deception_ping() -> Dict[str, Any]:
    """Test connectivity to PNNL's Deception HPC cluster via SSH.

    Verifies that:
    1. SSH key-based authentication succeeds to deception.pnl.gov
    2. The Slurm scheduler daemon (slurmctld) is responsive
    3. The configured user account can execute commands

    Call this before submitting jobs to confirm the cluster is reachable
    and your SSH key is properly provisioned.

    Returns:
        dict: Connection status with fields:
            - status (str): 'connected' if Slurm responds, 'unreachable' otherwise
            - cluster (str): Always 'deception'
            - host (str): Cluster hostname (deception.pnl.gov)
            - transport (str): Transport mode in use ('ssh')
            - username (str): Configured Slurm username

    Example:
        >>> deception_ping()
        {"status": "connected", "cluster": "deception", "host": "deception.pnl.gov",
         "transport": "ssh", "username": "rigo160"}
    """
    transport = await _get_transport()
    try:
        reachable = await transport.ping()
        return {
            "status": "connected" if reachable else "unreachable",
            "cluster": "deception",
            "host": deception_config.host,
            "transport": deception_config.transport_mode,
            "username": deception_config.username,
        }
    except Exception as e:
        return {"status": "error", "cluster": "deception", "message": str(e)}


@app.tool
@_log_tool_call
async def deception_submit_job(
    request: DeceptionJobSubmissionRequest,
    mcp_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit a batch job to PNNL's Deception HPC cluster via sbatch.

    Writes the script to the user's workspace on the cluster login node
    and runs sbatch. When session_id is provided, the script is persisted
    at ~/adept-workspace/{session_id}/{job_name}_{hash}.sh for provenance
    tracking. Without session_id, uses a temporary /tmp/ path (cleaned up
    after submission).

    Prerequisites:
        - SSH key must be provisioned (use hpc_generate_ssh_key + manual authorized_keys)
        - deception_ping() should return 'connected'

    Args:
        request: Job submission request containing:
            - job_spec.job_name (str): Job name for tracking in squeue/sacct
            - job_spec.partition (str, optional): Target partition (queue)
            - job_spec.account (str, optional): Allocation account for charging
            - job_spec.nodes (int): Number of compute nodes (default: 1)
            - job_spec.ntasks (int): Total tasks across all nodes (default: 1)
            - job_spec.cpus_per_task (int): CPU cores per task (default: 1)
            - job_spec.memory (str, optional): Memory per node (e.g., '16G', '4096M')
            - job_spec.time_limit (str): Wall time limit in HH:MM:SS (default: '01:00:00')
            - job_spec.working_directory (str, optional): Working dir on cluster
            - job_spec.array (str, optional): Array spec (e.g., '0-9', '1-100%10')
            - script (str): Bash script content to execute
            - session_id (str, optional): MCP session ID for workspace isolation

    Returns:
        dict: Submission result with fields:
            - status (str): 'submitted' on success, 'error' on failure
            - job_id (str): Assigned Slurm job ID (on success)
            - cluster (str): Always 'deception'
            - message (str): sbatch output or error details
            - workspace (str, optional): Remote path where script is persisted

    Example:
        >>> deception_submit_job(request=DeceptionJobSubmissionRequest(
        ...     job_spec=DeceptionJobSpec(
        ...         job_name="test_hello",
        ...         nodes=1, ntasks=1, time_limit="00:05:00"
        ...     ),
        ...     script="#!/bin/bash\\necho Hello from $(hostname)\\nsleep 5",
        ...     session_id="mcp_abc123"
        ... ))
        {"status": "submitted", "job_id": "1234567", "cluster": "deception",
         "message": "Submitted batch job 1234567",
         "workspace": "~/adept-workspace/mcp_abc123"}
    """
    transport = await _get_transport()
    spec = request.job_spec
    effective_session_id = request.session_id or mcp_session_id
    if effective_session_id and not request.session_id:
        logger.info(
            "session_id auto-injected from mcp_session_id=%s", effective_session_id
        )
    result = await transport.submit_job(
        script=request.script,
        job_name=spec.job_name,
        partition=spec.partition,
        account=spec.account,
        nodes=spec.nodes,
        ntasks=spec.ntasks,
        cpus_per_task=spec.cpus_per_task,
        memory=spec.memory,
        time_limit=spec.time_limit,
        working_directory=spec.working_directory,
        array=spec.array,
        session_id=effective_session_id,
        output_dir=request.output_dir,
        timeout_seconds=request.timeout_seconds,
    )
    if result.success:
        response = {
            "status": "submitted",
            "job_id": result.job_id,
            "cluster": "deception",
            "message": result.output.strip(),
        }
        if effective_session_id:
            response["workspace"] = f"$HOME/adept-workspace/{effective_session_id}"
            response["output_file"] = f"slurm-{result.job_id}.out"
            response["read_output_with"] = (
                f"workspace_read_file(filename='slurm-{result.job_id}.out', "
                f"session_id='{effective_session_id}', cluster='deception')"
            )
        if request.output_dir:
            response["output_dir"] = request.output_dir
        return response
    return {
        "status": "error",
        "cluster": "deception",
        "message": result.error or "Job submission failed",
        "details": result.output,
    }


@app.tool
@_log_tool_call
async def deception_get_job_details(
    job_id: Annotated[str, Field(
        description="Slurm job ID to query — numeric string from deception_submit_job output (e.g., '856118')"
    )]
) -> Dict[str, Any]:
    """Get status and details of a Slurm job on PNNL's Deception cluster via SSH.

    THIS is the correct tool for checking job status on Deception. It connects
    via SSH and runs squeue/sacct directly on the cluster login node. Do NOT use
    the generic 'get_job_details' tool for Deception — that tool calls slurmrestd
    (a REST API) which is not accessible from this server and returns HTTP 422.

    Query strategy (handles both active AND completed jobs):
      1. First tries squeue --json (for PENDING/RUNNING jobs still in the active queue)
      2. If squeue returns empty, falls back to sacct --json (for COMPLETED/FAILED/
         CANCELLED/TIMEOUT jobs in the accounting database)

    This two-phase approach ensures the tool works regardless of job state. Short-lived
    jobs (< 30 seconds) will have already left squeue by the time you query, but sacct
    retains their full history including exit codes and timing.

    Backend: SSH to deception.pnl.gov → squeue/sacct CLI commands
    Authentication: SSH key-based (provisioned via hpc_generate_ssh_key)

    Args:
        job_id: Numeric Slurm job ID returned by deception_submit_job (e.g., '856118').
            Must be a string of digits. Array job tasks use format '12345_0'.

    Returns:
        dict: Job details with fields:
            - status (str): 'found' if job exists in squeue or sacct, 'not_found' otherwise
            - job_id (str): The queried job ID (echoed back for reference)
            - cluster (str): Always 'deception'
            - job_data (dict): Raw Slurm JSON containing job_state, nodes, partition,
              account, submit_time, start_time, end_time, exit_code, time.elapsed,
              tres (resources), working_directory, etc. (present only when status='found')
            - message (str): Error details or reason for not_found (present only when
              status='not_found')

    Example:
        >>> deception_get_job_details(job_id="856118")
        {"status": "found", "job_id": "856118", "cluster": "deception",
         "job_data": {"job_id": 856118, "state": {"current": "COMPLETED"},
          "exit_code": {"return_code": 0}, "time": {"elapsed": 45}, ...}}
    """
    transport = await _get_transport()
    result = await transport.get_job_status(job_id)
    if result.success:
        return {
            "status": "found",
            "job_id": job_id,
            "cluster": "deception",
            "job_data": result.raw_data,
        }
    return {
        "status": "not_found",
        "job_id": job_id,
        "cluster": "deception",
        "message": result.error,
    }


@app.tool
@_log_tool_call
async def deception_cancel_job(
    job_id: Annotated[str, Field(description="Slurm job ID to cancel (numeric string, e.g., '1234567')")]
) -> Dict[str, Any]:
    """Cancel a running or pending job on PNNL's Deception cluster.

    Sends SIGTERM to the job via scancel. The job may take a few seconds
    to actually terminate. Array jobs can be cancelled by specifying either
    the parent job ID (cancels all tasks) or a specific task (e.g., '1234_5').

    Args:
        job_id: Numeric Slurm job ID or array task ID to cancel.

    Returns:
        dict: Cancellation result with fields:
            - status (str): 'cancelled' on success, 'error' on failure
            - job_id (str): Job ID that was cancelled
            - cluster (str): Always 'deception'
            - message (str): Error details (on failure)

    Example:
        >>> deception_cancel_job(job_id="1234567")
        {"status": "cancelled", "job_id": "1234567", "cluster": "deception"}
    """
    transport = await _get_transport()
    result = await transport.cancel_job(job_id)
    if result.success:
        return {
            "status": "cancelled",
            "job_id": job_id,
            "cluster": "deception",
        }
    return {
        "status": "error",
        "job_id": job_id,
        "cluster": "deception",
        "message": result.error,
    }


@app.tool
@_log_tool_call
async def deception_list_jobs(
    filters: Optional[DeceptionJobListFilters] = None,
) -> Dict[str, Any]:
    """List ACTIVE jobs in the scheduler queue on PNNL's Deception cluster via SSH.

    IMPORTANT: This tool only shows jobs currently in the active scheduler queue
    (PENDING, RUNNING, SUSPENDED). Jobs that have already COMPLETED, FAILED, or
    been CANCELLED are NOT visible here — they are removed from squeue within
    seconds of finishing. To check the status of a completed job, use
    deception_get_job_details instead (it queries sacct for historical records).

    Backend: SSH to deception.pnl.gov → squeue --json
    Authentication: SSH key-based

    Typical use case: Check if your recently-submitted job is still running or
    waiting in the queue. If this returns empty and you know a job was submitted,
    the job has already finished — use deception_get_job_details with the job ID.

    Args:
        filters: Optional filtering criteria:
            - user (str, optional): Show only jobs owned by this username
              (e.g., 'rigo160'). Without this, shows all visible jobs.
            - state (str, optional): Filter by active state: PENDING, RUNNING,
              SUSPENDED. Note: COMPLETED/FAILED/CANCELLED will never match
              because those jobs have already left the queue.

    Returns:
        dict: Job listing with fields:
            - status (str): Always 'success' (even if job_count is 0)
            - cluster (str): Always 'deception'
            - job_count (int): Number of jobs matching filters (0 if queue is empty
              or all matching jobs have already completed)
            - jobs (list[dict]): Job records from squeue --json output,
              each containing job_id, job_state, name, partition, nodes, time_limit

    Example:
        >>> deception_list_jobs(filters=DeceptionJobListFilters(user="rigo160"))
        {"status": "success", "cluster": "deception", "job_count": 2,
         "jobs": [{"job_id": 856200, "job_state": "RUNNING", ...}, ...]}

        >>> deception_list_jobs()  # No active jobs
        {"status": "success", "cluster": "deception", "job_count": 0, "jobs": []}
    """
    transport = await _get_transport()
    user = filters.user if filters else None
    state = filters.state if filters else None
    jobs = await transport.list_jobs(user=user, state=state)
    return {
        "status": "success",
        "cluster": "deception",
        "job_count": len(jobs),
        "jobs": jobs,
    }


@app.tool
@_log_tool_call
async def deception_get_cluster_summary() -> Dict[str, Any]:
    """Get a comprehensive overview of PNNL's Deception cluster state.

    Combines sinfo (node/partition data) and squeue (job queue) to provide
    a full picture of cluster availability. Use this before submitting jobs
    to understand current load and available resources.

    Returns:
        dict: Cluster summary with fields:
            - status (str): Always 'success'
            - cluster (str): Always 'deception'
            - node_count (int): Total nodes discovered
            - job_count (int): Total jobs in queue
            - partition_count (int): Available partitions
            - nodes (list[dict]): First 20 nodes with state, cpus, memory
            - partitions (list[dict]): All partitions with limits and availability
            - queue_summary (dict): Aggregate counts:
                - total_jobs (int)
                - running (int): Jobs currently executing
                - pending (int): Jobs waiting for resources

    Example:
        >>> deception_get_cluster_summary()
        {"status": "success", "cluster": "deception", "node_count": 128,
         "job_count": 45, "partition_count": 4,
         "queue_summary": {"total_jobs": 45, "running": 30, "pending": 15}, ...}
    """
    transport = await _get_transport()
    info = await transport.get_cluster_info()
    return {
        "status": "success",
        "cluster": "deception",
        "node_count": len(info.nodes),
        "job_count": len(info.jobs),
        "partition_count": len(info.partitions),
        "nodes": info.nodes[:20],
        "partitions": info.partitions,
        "queue_summary": {
            "total_jobs": len(info.jobs),
            "running": sum(
                1 for j in info.jobs if j.get("job_state", "") == "RUNNING"
            ),
            "pending": sum(
                1 for j in info.jobs if j.get("job_state", "") == "PENDING"
            ),
        },
    }
