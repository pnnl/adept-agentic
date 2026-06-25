"""MCP tools for PNNL Tahoma HPC cluster.

Tahoma is a production Slurm HPC cluster at PNNL supporting both SSH
and REST API (slurmrestd) transports. Transport selection is controlled
via the TAHOMA_TRANSPORT_MODE environment variable (auto/ssh/rest).
In 'auto' mode, the REST endpoint is probed first; if unreachable,
SSH is used as fallback.

The SSH private key is configured in clusters.yaml and used internally
by Fabric — key material is never exposed to the reasoning model.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from ..app import app
from ..transport import SlurmTransport
from .config import tahoma_config
from .models import TahomaJobListFilters, TahomaJobSubmissionRequest

logger = logging.getLogger(__name__)

_transport: Optional[SlurmTransport] = None


async def _get_transport() -> SlurmTransport:
    """Get or create the Tahoma transport instance.

    Transport selection logic:
      - 'rest': Force REST transport (requires TAHOMA_REST_API_URL)
      - 'auto': Probe REST first, fallback to SSH if unreachable
      - 'ssh' (or anything else): Force SSH transport
    """
    global _transport
    if _transport is None:
        if tahoma_config.transport_mode == "rest" and tahoma_config.rest_api_url:
            from .rest_transport import TahomaRESTTransport

            _transport = TahomaRESTTransport(tahoma_config)
            logger.info("Tahoma: using REST transport (forced)")
        elif tahoma_config.transport_mode == "auto":
            if tahoma_config.rest_api_url:
                try:
                    from .rest_transport import TahomaRESTTransport

                    t = TahomaRESTTransport(tahoma_config)
                    if await t.ping():
                        _transport = t
                        logger.info("Tahoma: using REST transport (auto-probed)")
                except Exception:
                    pass
            if _transport is None:
                from ..fabric_transport import FabricSSHTransport

                _transport = FabricSSHTransport(tahoma_config)
                logger.info("Tahoma: using SSH transport (auto-fallback)")
        else:
            from ..fabric_transport import FabricSSHTransport

            _transport = FabricSSHTransport(tahoma_config)
            logger.info("Tahoma: using SSH transport")
    return _transport


@app.tool
async def tahoma_ping() -> Dict[str, Any]:
    """Test connectivity to PNNL's Tahoma HPC cluster via SSH or REST API.

    Verifies that:
    1. The configured transport (SSH key-based auth or REST JWT) succeeds
    2. The Slurm scheduler daemon (slurmctld) is responsive on Tahoma
    3. The configured user account can execute commands

    Tahoma supports dual transport (SSH + REST). The active transport is
    selected by TAHOMA_TRANSPORT_MODE: 'ssh', 'rest', or 'auto' (probe
    REST first, fallback to SSH). Call this before submitting jobs to
    confirm the cluster is reachable.

    Returns:
        dict: Connection status with fields:
            - status (str): 'connected' if Slurm responds, 'unreachable' otherwise
            - cluster (str): Always 'tahoma'
            - host (str): Cluster hostname (tahoma.pnl.gov)
            - transport (str): Active transport mode ('ssh' or 'rest')
            - username (str): Configured Slurm username

    Example:
        >>> tahoma_ping()
        {"status": "connected", "cluster": "tahoma", "host": "tahoma.pnl.gov",
         "transport": "ssh", "username": "rigo160"}
    """
    transport = await _get_transport()
    try:
        reachable = await transport.ping()
        return {
            "status": "connected" if reachable else "unreachable",
            "cluster": "tahoma",
            "host": tahoma_config.host,
            "transport": tahoma_config.transport_mode,
            "username": tahoma_config.username,
        }
    except Exception as e:
        return {"status": "error", "cluster": "tahoma", "message": str(e)}


@app.tool
async def tahoma_submit_job(request: TahomaJobSubmissionRequest) -> Dict[str, Any]:
    """Submit a batch job to PNNL's Tahoma HPC cluster.

    Uploads the script to a temporary file on the cluster login node,
    runs sbatch with the specified resource options, then cleans up.
    When using SSH transport, the private key (from clusters.yaml)
    authenticates the connection. When using REST, a JWT token is used.

    Prerequisites:
        - For SSH: Key must be provisioned (use hpc_generate_ssh_key + manual authorized_keys)
        - For REST: TAHOMA_REST_API_URL and TAHOMA_JWT_TOKEN must be configured
        - tahoma_ping() should return 'connected'

    Args:
        request: Job submission request containing:
            - job_spec.job_name (str): Job name for tracking in squeue/sacct
            - job_spec.partition (str, optional): Target partition (queue)
            - job_spec.account (str, optional): Allocation account for charging
            - job_spec.nodes (int): Number of compute nodes (default: 1)
            - job_spec.ntasks (int): Total tasks across all nodes (default: 1)
            - job_spec.cpus_per_task (int): CPU cores per task (default: 1)
            - job_spec.memory (str, optional): Memory per node (e.g., '64G', '4096M')
            - job_spec.time_limit (str): Wall time limit in HH:MM:SS (default: '01:00:00')
            - job_spec.working_directory (str, optional): Working dir on cluster
            - job_spec.array (str, optional): Array spec (e.g., '0-9', '1-100%10')
            - script (str): Bash script content to execute

    Returns:
        dict: Submission result with fields:
            - status (str): 'submitted' on success, 'error' on failure
            - job_id (str): Assigned Slurm job ID (on success)
            - cluster (str): Always 'tahoma'
            - message (str): sbatch output or error details

    Example:
        >>> tahoma_submit_job(request=TahomaJobSubmissionRequest(
        ...     job_spec=TahomaJobSpec(
        ...         job_name="genomics_pipeline",
        ...         nodes=4, ntasks=128, time_limit="04:00:00",
        ...         memory="64G", partition="normal"
        ...     ),
        ...     script="#!/bin/bash\\nsrun ./my_mpi_app --input data.h5"
        ... ))
        {"status": "submitted", "job_id": "9876543", "cluster": "tahoma",
         "message": "Submitted batch job 9876543"}
    """
    transport = await _get_transport()
    spec = request.job_spec
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
        session_id=request.session_id,
    )
    if result.success:
        response = {
            "status": "submitted",
            "job_id": result.job_id,
            "cluster": "tahoma",
            "message": result.output.strip(),
        }
        if request.session_id:
            response["workspace"] = f"~/adept-workspace/{request.session_id}"
        return response
    return {
        "status": "error",
        "cluster": "tahoma",
        "message": result.error or "Job submission failed",
        "details": result.output,
    }


@app.tool
async def tahoma_get_job_details(
    job_id: Annotated[str, Field(description="Slurm job ID to query (numeric string, e.g., '9876543')")]
) -> Dict[str, Any]:
    """Get status and details of a job on PNNL's Tahoma cluster.

    Queries the active queue via squeue (for PENDING/RUNNING jobs) and
    falls back to sacct (for COMPLETED/FAILED/CANCELLED jobs). Returns
    comprehensive job information including state, resources, timing,
    and exit codes.

    Args:
        job_id: Numeric Slurm job ID (from tahoma_submit_job output).

    Returns:
        dict: Job details with fields:
            - status (str): 'found' if job exists, 'not_found' otherwise
            - job_id (str): Queried job ID
            - cluster (str): Always 'tahoma'
            - job_data (dict): Raw Slurm JSON with job_state, nodes, partition,
              submit_time, start_time, end_time, exit_code, etc. (when found)
            - message (str): Error details (when not found)

    Example:
        >>> tahoma_get_job_details(job_id="9876543")
        {"status": "found", "job_id": "9876543", "cluster": "tahoma",
         "job_data": {"job_state": "COMPLETED", "nodes": "t001-t004",
                      "exit_code": {"return_code": 0}, ...}}
    """
    transport = await _get_transport()
    result = await transport.get_job_status(job_id)
    if result.success:
        return {
            "status": "found",
            "job_id": job_id,
            "cluster": "tahoma",
            "job_data": result.raw_data,
        }
    return {
        "status": "not_found",
        "job_id": job_id,
        "cluster": "tahoma",
        "message": result.error,
    }


@app.tool
async def tahoma_cancel_job(
    job_id: Annotated[str, Field(description="Slurm job ID to cancel (numeric string, e.g., '9876543')")]
) -> Dict[str, Any]:
    """Cancel a running or pending job on PNNL's Tahoma cluster.

    Sends SIGTERM to the job via scancel. The job may take a few seconds
    to actually terminate. Array jobs can be cancelled by specifying either
    the parent job ID (cancels all tasks) or a specific task (e.g., '9876_5').

    Args:
        job_id: Numeric Slurm job ID or array task ID to cancel.

    Returns:
        dict: Cancellation result with fields:
            - status (str): 'cancelled' on success, 'error' on failure
            - job_id (str): Job ID that was cancelled
            - cluster (str): Always 'tahoma'
            - message (str): Error details (on failure)

    Example:
        >>> tahoma_cancel_job(job_id="9876543")
        {"status": "cancelled", "job_id": "9876543", "cluster": "tahoma"}
    """
    transport = await _get_transport()
    result = await transport.cancel_job(job_id)
    if result.success:
        return {
            "status": "cancelled",
            "job_id": job_id,
            "cluster": "tahoma",
        }
    return {
        "status": "error",
        "job_id": job_id,
        "cluster": "tahoma",
        "message": result.error,
    }


@app.tool
async def tahoma_list_jobs(
    filters: Optional[TahomaJobListFilters] = None,
) -> Dict[str, Any]:
    """List jobs in the queue on PNNL's Tahoma cluster.

    Queries squeue for current jobs. Can filter by username and/or job state.
    Returns a list of jobs with their IDs, names, states, partitions,
    node assignments, and time limits.

    Args:
        filters: Optional filtering criteria:
            - user (str, optional): Show only jobs owned by this username
            - state (str, optional): Filter by state: PENDING, RUNNING,
              COMPLETED, FAILED, CANCELLED, TIMEOUT

    Returns:
        dict: Job listing with fields:
            - status (str): Always 'success'
            - cluster (str): Always 'tahoma'
            - job_count (int): Number of jobs matching filters
            - jobs (list[dict]): Job records from squeue --json output,
              each containing job_id, job_state, name, partition, nodes, etc.

    Example:
        >>> tahoma_list_jobs(filters=TahomaJobListFilters(user="rigo160", state="RUNNING"))
        {"status": "success", "cluster": "tahoma", "job_count": 12,
         "jobs": [{"job_id": "987", "job_state": "RUNNING", "name": "sim_01", ...}, ...]}
    """
    transport = await _get_transport()
    user = filters.user if filters else None
    state = filters.state if filters else None
    jobs = await transport.list_jobs(user=user, state=state)
    return {
        "status": "success",
        "cluster": "tahoma",
        "job_count": len(jobs),
        "jobs": jobs,
    }


@app.tool
async def tahoma_get_cluster_summary() -> Dict[str, Any]:
    """Get a comprehensive overview of PNNL's Tahoma cluster state.

    Combines sinfo (node/partition data) and squeue (job queue) to provide
    a full picture of cluster availability. Use this before submitting jobs
    to understand current load and available resources.

    Tahoma is a large-scale cluster with multiple partitions optimized for
    different workloads (short, normal, long, gpu, bigmem). The summary
    helps select the right partition and estimate queue wait time.

    Returns:
        dict: Cluster summary with fields:
            - status (str): Always 'success'
            - cluster (str): Always 'tahoma'
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
        >>> tahoma_get_cluster_summary()
        {"status": "success", "cluster": "tahoma", "node_count": 520,
         "job_count": 189, "partition_count": 6,
         "queue_summary": {"total_jobs": 189, "running": 142, "pending": 47}, ...}
    """
    transport = await _get_transport()
    info = await transport.get_cluster_info()
    return {
        "status": "success",
        "cluster": "tahoma",
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
