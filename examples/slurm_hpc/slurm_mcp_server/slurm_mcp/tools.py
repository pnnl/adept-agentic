"""
SLURM MCP Tools
===============

All SLURM cluster management tools: job management, cluster info, and monitoring.
Adapted for ADEPT: no ctx auth param, uses service credentials via JWTTokenManager.
"""

import asyncio
from typing import Dict, Any, Optional

from fastmcp.exceptions import ToolError

from .client import get_service_client
from .models import JobSubmissionRequest, JobListFilters
from .utils import format_job_details, format_job_list
from .config import config

# Import app instance to register tools directly
from .app import app


# === Job Management Tools ===


@app.tool
async def submit_slurm_job(request: JobSubmissionRequest) -> Dict[str, Any]:
    """Submit a batch job to a SLURM cluster via the slurmrestd REST API.

    WARNING: This tool requires a running slurmrestd daemon accessible from this
    server. It does NOT work for clusters accessed via SSH (like Deception or Tahoma).
    For SSH-based clusters, use the cluster-specific submission tool instead:
      - Deception: use deception_submit_job
      - Tahoma: use tahoma_submit_job

    Creates and submits a new batch job with the specified resource requirements
    (nodes, CPUs per node, memory, time limit, partition) and a bash script to
    execute on the allocated compute nodes.

    Backend: HTTP POST to slurmrestd at /slurm/{api_version}/job/submit
    Authentication: JWT token via JWTTokenManager

    The request must include a JobSubmissionRequest with:
    - job: A Slurm job specification (job_name, partition, nodes, ntasks,
      cpus_per_task, memory_per_node, time_limit, standard_output, standard_error,
      current_working_directory, environment)
    - script: A complete bash script (with shebang line) to execute on the
      allocated compute node(s)

    Returns a dict with:
    - success (bool): Whether the submission was accepted by slurmctld
    - job_id (str): The numeric Slurm job ID for tracking
    - message (str): Human-readable confirmation
    - errors/warnings (list, optional): Any scheduler warnings

    Raises ToolError if the submission fails (e.g., invalid partition, resource
    limits exceeded, slurmrestd unreachable, authentication failure).
    """
    try:
        username, client_ctx = get_service_client()

        # Serialize job data
        job_data = {
            "job": request.job.model_dump(exclude_none=True),
            "script": request.script,
        }

        async with client_ctx as client:
            result = await client.request(
                "POST",
                f"/slurm/{config.api_version}/job/submit",
                json=job_data,
            )

        return {
            "success": True,
            "job_id": result.get("job_id"),
            "message": f"Job {result.get('job_id')} submitted successfully",
            **{k: v for k, v in result.items() if k in ["errors", "warnings"] and v},
        }

    except Exception as e:
        raise ToolError(f"Job submission failed: {str(e)}") from e


@app.tool
async def get_job_details(job_id: str) -> str:
    """Get detailed status and resource usage for a SLURM job via slurmrestd REST API.

    WARNING: This tool requires a running slurmrestd daemon accessible from this
    server. It does NOT work for clusters accessed via SSH (like Deception or Tahoma).
    For SSH-based clusters, use the cluster-specific tool instead:
      - Deception: use deception_get_job_details
      - Tahoma: use tahoma_get_job_details

    Queries slurmrestd (the Slurm REST API daemon) for comprehensive information
    about a single job, including its current state (PENDING, RUNNING, COMPLETED,
    FAILED, etc.), allocated nodes and CPUs, start and end timestamps, exit code,
    working directory, and standard output/error file paths.

    Backend: HTTP GET to slurmrestd at /slurm/{api_version}/job/{job_id}
    Authentication: JWT token via JWTTokenManager

    The result is returned as a Markdown-formatted report suitable for display
    in chat interfaces.

    Args:
        job_id: The numeric Slurm job ID (e.g., '12345') returned by
            submit_slurm_job or visible in list_cluster_jobs output.

    Returns:
        A Markdown-formatted string containing the job's full details:
        name, state, partition, nodes, CPUs, memory, time limit,
        start/end times, exit code, and working directory.

    Raises ToolError if the job ID is not found, slurmrestd returns an error
    (e.g., HTTP 422 if API version mismatch), or authentication fails.
    """
    try:
        username, client_ctx = get_service_client()

        async with client_ctx as client:
            result = await client.request(
                "GET", f"/slurm/{config.api_version}/job/{job_id}"
            )

        jobs = result.get("jobs", [])
        if not jobs:
            return f"# Job Not Found\n\nJob `{job_id}` not found."

        return format_job_details(jobs[0], job_id, config)

    except Exception as e:
        raise ToolError(f"Failed to get job details: {str(e)}") from e


@app.tool(
    tags=["job", "cancel", "terminate", "management"],
)
async def cancel_slurm_job(job_id: str) -> Dict[str, Any]:
    """Cancel a running or pending SLURM job by its numeric job ID.

    Sends a cancellation (scancel equivalent) request to slurmctld via the
    slurmrestd REST API. This terminates RUNNING jobs immediately (sends
    SIGTERM then SIGKILL) and removes PENDING jobs from the scheduler queue.

    Use this to stop jobs that are stuck, consuming excessive resources, or
    were submitted with incorrect parameters. The cancellation is immediate
    but allocated resources may take a few seconds to be released.

    Args:
        job_id: The numeric Slurm job ID to cancel (e.g., '12345').
            Must be a job owned by the authenticated service user.

    Returns:
        A dict with:
        - success (bool): Whether the cancellation was accepted
        - job_id (str): The cancelled job ID
        - message (str): Human-readable confirmation
        - errors/warnings (list, optional): Any scheduler warnings

    Raises ToolError if the job cannot be cancelled (e.g., already completed,
    not found, or insufficient permissions).
    """
    try:
        username, client_ctx = get_service_client()

        async with client_ctx as client:
            result = await client.request(
                "DELETE", f"/slurm/{config.api_version}/job/{job_id}"
            )

        return {
            "success": True,
            "job_id": job_id,
            "message": f"Job {job_id} cancelled successfully",
            **{k: v for k, v in result.items() if k in ["errors", "warnings"] and v},
        }

    except Exception as e:
        raise ToolError(f"Failed to cancel job {job_id}: {str(e)}") from e


# === Cluster Information Tools ===


@app.tool(
    tags=["connectivity", "test", "ping", "auth"],
)
async def ping() -> Dict[str, Any]:
    """Test connectivity to the SLURM HPC cluster and verify authentication.

    Performs a lightweight health check that verifies:
    1. The MCP server can reach the slurmrestd REST API endpoint
    2. The JWT authentication token is valid and not expired
    3. The configured API version is correct

    **Use this as the first tool call** when starting a new HPC session to
    confirm the cluster is reachable before attempting job submissions or
    queries. A successful ping confirms the entire auth chain: MCP server →
    JWT token manager → slurmrestd → slurmctld.

    Returns:
        A dict with:
        - success (bool): True if cluster is reachable and authenticated
        - message (str): Human-readable status message
        - cluster_url (str): The slurmrestd API base URL
        - api_version (str): Slurm REST API version (e.g., 'v0.0.40')
        - user (str): The authenticated Slurm username

    Raises ToolError if authentication fails or the cluster is unreachable.
    """
    try:
        username, client_ctx = get_service_client()

        return {
            "success": True,
            "message": "Pong! SLURM MCP server is connected and authenticated.",
            "cluster_url": config.api_url,
            "api_version": config.api_version,
            "user": username,
        }

    except Exception as e:
        if isinstance(e, ToolError):
            raise
        raise ToolError(f"Ping test failed: {str(e)}")


@app.tool(
    tags=["job", "list", "filter", "queue"],
)
async def list_cluster_jobs(filters: Optional[JobListFilters] = None) -> str:
    """List jobs in the SLURM cluster queue via slurmrestd REST API.

    WARNING: This tool requires a running slurmrestd daemon accessible from this
    server. It does NOT work for clusters accessed via SSH (like Deception or Tahoma).
    For SSH-based clusters, use the cluster-specific listing tool instead:
      - Deception: use deception_list_jobs
      - Tahoma: use tahoma_list_jobs

    Queries slurmrestd for the current job queue (equivalent to `squeue`).
    Only shows ACTIVE jobs (PENDING, RUNNING). Completed/failed jobs disappear
    from squeue within seconds of finishing — use get_job_details or the
    cluster-specific tool with sacct fallback to query completed job history.

    Backend: HTTP GET to slurmrestd at /slurm/{api_version}/jobs
    Authentication: JWT token via JWTTokenManager

    Args:
        filters: Optional JobListFilters with:
            - state (list[str]): Filter by job states, e.g. ['RUNNING', 'PENDING']
            - user (str): Filter by submitting username
            - partition (str): Filter by partition name
            - limit (int): Maximum number of jobs to return

    Returns:
        A Markdown-formatted table string. Returns a "no jobs found" message
        if the queue is empty or no jobs match the filter criteria.

    Raises ToolError if slurmrestd is unreachable or authentication is invalid.
    """
    try:
        username, client_ctx = get_service_client()

        # Build query parameters
        params = {}
        if filters:
            filter_dict = filters.model_dump(exclude_none=True)
            if filter_dict.get("user"):
                params["user"] = filter_dict["user"]
            if filter_dict.get("state"):
                params["state"] = ",".join(filter_dict["state"])
            if filter_dict.get("partition"):
                params["partition"] = filter_dict["partition"]

        async with client_ctx as client:
            result = await client.request(
                "GET", f"/slurm/{config.api_version}/jobs", params=params
            )

        jobs = result.get("jobs", [])
        return format_job_list(jobs, config)

    except Exception as e:
        if isinstance(e, ToolError):
            raise
        raise ToolError(f"Failed to list cluster jobs: {str(e)}")


@app.tool(
    tags=["cluster", "summary", "status", "overview"],
)
async def get_cluster_summary(partition: Optional[str] = None) -> str:
    """Get a comprehensive overview of the SLURM cluster including job queue depth, node availability, partition configuration, and resource recommendations.

    Fetches live data from slurmrestd by querying three endpoints in parallel
    (jobs, partitions, nodes) and assembles a Markdown-formatted dashboard
    showing:
    - **Job Queue Status**: Counts by state (RUNNING, PENDING, COMPLETED, etc.)
      with percentages
    - **Node Status**: Total/available CPUs, memory, and per-state node counts
    - **Available Partitions**: Table of partition names, states, node counts,
      and time limits (cluster-wide view only)
    - **Recommendations**: Actionable guidance based on queue depth and node
      availability (e.g., 'High queue load', 'N idle nodes available')
    - **Quick Actions**: Pointers to other available tools

    **Recommended first call** when starting an HPC workflow — provides the
    context needed to choose the right partition, resource limits, and timing
    for job submissions.

    Args:
        partition: Optional partition name to focus the summary on. When set,
            only shows jobs and nodes belonging to that partition. When omitted,
            shows cluster-wide overview with all partitions listed.

    Returns:
        A comprehensive Markdown-formatted cluster dashboard string, suitable
        for display in chat interfaces or rendering in documentation.

    Raises ToolError if the cluster is unreachable or API queries fail.
    """
    try:
        username, client_ctx = get_service_client()

        async with client_ctx as client:
            # Fetch cluster data in parallel
            jobs_task = client.request("GET", f"/slurm/{config.api_version}/jobs")
            partitions_task = client.request(
                "GET", f"/slurm/{config.api_version}/partitions"
            )
            nodes_task = client.request("GET", f"/slurm/{config.api_version}/nodes")

            jobs_result, partitions_result, nodes_result = await asyncio.gather(
                jobs_task, partitions_task, nodes_task
            )

        jobs = jobs_result.get("jobs", [])
        partitions_list = partitions_result.get("partitions", [])
        nodes = nodes_result.get("nodes", [])

        # Start building summary
        summary_lines = [
            "# SLURM Cluster Summary",
            "",
            f"**Cluster**: {config.api_url}",
            f"**User**: {username}",
            f"**Generated**: Live data from API v{config.api_version}",
            "",
        ]

        # Filter data by partition if specified
        if partition:
            partition_jobs = [
                job for job in jobs if job.get("partition") == partition
            ]
            partition_nodes = []
            for node in nodes:
                node_partitions = node.get("partitions", [])
                if partition in node_partitions:
                    partition_nodes.append(node)

            summary_lines.extend(
                [f"## Partition Focus: `{partition}`", ""]
            )
        else:
            partition_jobs = jobs
            partition_nodes = nodes
            summary_lines.extend(["## Cluster-Wide Overview", ""])

        # Job Statistics
        job_states = {}
        for job in partition_jobs:
            state = job.get("job_state", ["UNKNOWN"])
            state = state[0] if isinstance(state, list) else state
            job_states[state] = job_states.get(state, 0) + 1

        summary_lines.extend(["### Job Queue Status", ""])

        if job_states:
            total_jobs = sum(job_states.values())
            summary_lines.append(f"**Total Jobs**: {total_jobs}")
            summary_lines.append("")

            for state, count in sorted(job_states.items()):
                emoji = config.JOB_STATE_EMOJIS.get(state, "")
                percentage = (count / total_jobs) * 100
                summary_lines.append(
                    f"- {emoji} **{state}**: {count} jobs ({percentage:.1f}%)"
                )
        else:
            summary_lines.append("- **No jobs currently in queue**")

        summary_lines.extend(["", "### Node Status", ""])

        # Node Statistics
        if partition_nodes:
            node_states = {}
            total_cpus = 0
            available_cpus = 0
            total_memory = 0

            for node in partition_nodes:
                state = node.get("state", ["UNKNOWN"])
                state = state[0] if isinstance(state, list) else state
                node_states[state] = node_states.get(state, 0) + 1

                cpus = node.get("cpus", 0)
                total_cpus += cpus

                if state in ["IDLE", "MIXED"]:
                    available_cpus += cpus

                memory = node.get("real_memory", 0)
                if isinstance(memory, dict):
                    memory = memory.get("number", 0)
                total_memory += memory

            summary_lines.append(f"**Total Nodes**: {len(partition_nodes)}")
            summary_lines.append(f"**Total CPUs**: {total_cpus}")
            summary_lines.append(f"**Available CPUs**: {available_cpus}")
            summary_lines.append(f"**Total Memory**: {total_memory:,} MB")
            summary_lines.append("")

            for state, count in sorted(node_states.items()):
                emoji = config.NODE_STATE_EMOJIS.get(state, "")
                percentage = (count / len(partition_nodes)) * 100
                summary_lines.append(
                    f"- {emoji} **{state}**: {count} nodes ({percentage:.1f}%)"
                )
        else:
            summary_lines.append("- **No nodes found**")

        # Partition Information
        if not partition:
            summary_lines.extend(["", "### Available Partitions", ""])
            if partitions_list:
                summary_lines.append("| Partition | State | Nodes | Max Time |")
                summary_lines.append("|-----------|-------|-------|----------|")

                for part in partitions_list[:10]:
                    name = part.get("name", "Unknown")
                    state = part.get("state", ["UNKNOWN"])
                    state = state[0] if isinstance(state, list) else state
                    total_nodes = part.get("total_nodes", "N/A")

                    max_time = part.get("maximum_time", {})
                    if isinstance(max_time, dict):
                        time_limit = f"{max_time.get('number', 'N/A')} min"
                    else:
                        time_limit = "N/A"

                    summary_lines.append(
                        f"| `{name}` | {state} | {total_nodes} | {time_limit} |"
                    )

                if len(partitions_list) > 10:
                    summary_lines.append(
                        f"\n*... and {len(partitions_list) - 10} more partitions*"
                    )
            else:
                summary_lines.append("- **No partitions found**")

        # Recommendations
        summary_lines.extend(["", "### Recommendations", ""])

        if job_states:
            pending_jobs = job_states.get("PENDING", 0)
            running_jobs = job_states.get("RUNNING", 0)

            if pending_jobs > running_jobs * 0.5:
                summary_lines.append(
                    "- **High queue load** - Consider using less busy partitions"
                )

            if partition_nodes:
                idle_nodes = node_states.get("IDLE", 0)
                if idle_nodes > 0:
                    summary_lines.append(
                        f"- **{idle_nodes} idle nodes available** - Good time to submit jobs"
                    )
                else:
                    summary_lines.append(
                        "- **No idle nodes** - Expect longer queue times"
                    )

        # Quick Actions
        summary_lines.extend(
            [
                "",
                "### Quick Actions",
                "",
                "- **Submit a job**: Use `submit_slurm_job` tool",
                "- **Check job details**: Use `get_job_details` with job ID",
                "- **List all jobs**: Use `list_cluster_jobs` tool",
                "- **View job templates**: Check resource `slurm://docs/job-templates`",
            ]
        )

        return "\n".join(summary_lines)

    except Exception as e:
        if isinstance(e, ToolError):
            raise
        raise ToolError(
            f"Failed to get cluster summary"
            f"{' for partition ' + partition if partition else ''}: {str(e)}"
        )
