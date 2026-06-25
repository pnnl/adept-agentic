"""Pydantic models for Deception HPC tool inputs.

These models are used by the deception_* family of MCP tools which operate
via SSH to deception.pnl.gov. They are NOT used by the generic slurmrestd-based
tools (submit_slurm_job, get_job_details, list_cluster_jobs).
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DeceptionJobSpec(BaseModel):
    """Resource specification for a batch job on PNNL's Deception HPC cluster.

    Defines compute resources requested via sbatch. These parameters map directly
    to sbatch CLI options: --job-name, --partition, --account, --nodes, --ntasks,
    --cpus-per-task, --mem, --time, --chdir, --array.

    The transport layer (FabricSSHTransport) converts these fields into an sbatch
    command that runs on deception.pnl.gov via SSH.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_name": "hello_world",
                    "partition": "short",
                    "nodes": 1,
                    "ntasks": 1,
                    "cpus_per_task": 1,
                    "time_limit": "00:10:00",
                },
                {
                    "job_name": "fba_cobrapy",
                    "nodes": 1,
                    "ntasks": 1,
                    "cpus_per_task": 4,
                    "memory": "16G",
                    "time_limit": "01:00:00",
                },
            ]
        }
    )

    job_name: str = Field(
        ...,
        description=(
            "Job name visible in squeue/sacct output (e.g., 'fba_cobrapy', "
            "'build_sif'). Keep short — truncated at 128 chars by Slurm."
        ),
    )
    partition: Optional[str] = Field(
        None,
        description=(
            "Partition (queue) to submit to. Call deception_get_cluster_summary "
            "first to discover valid partitions. Common: 'short', 'slurm'. "
            "Do NOT guess partition names — invalid partitions cause submission failure. "
            "When omitted, Slurm uses the cluster default partition."
        ),
    )
    account: Optional[str] = Field(
        None,
        description=(
            "Slurm account for job charging (e.g., 'famous'). Required on clusters "
            "with mandatory accounting. Omit to use the user's default account."
        ),
    )
    nodes: int = Field(
        1, ge=1,
        description="Number of compute nodes requested. Use 1 for single-node jobs.",
    )
    ntasks: int = Field(
        1, ge=1,
        description=(
            "Total number of tasks (MPI ranks) across all nodes. "
            "For single-process jobs, use 1. For MPI jobs, set to total rank count."
        ),
    )
    cpus_per_task: int = Field(
        1, ge=1,
        description=(
            "CPU cores allocated per task. Use >1 for multi-threaded applications "
            "(OpenMP, Python multiprocessing). Each task gets this many cores."
        ),
    )
    memory: Optional[str] = Field(
        None,
        description=(
            "Memory per node (e.g., '16G', '4096M', '512000K'). "
            "Omit to use partition default. Jobs exceeding this limit are killed by Slurm."
        ),
    )
    time_limit: str = Field(
        "01:00:00",
        description=(
            "Maximum wall-clock time in HH:MM:SS format. Jobs exceeding this are "
            "killed with TIMEOUT state. Short jobs (<10min) use 'short' partition well. "
            "Max depends on partition (check deception_get_cluster_summary)."
        ),
    )
    working_directory: Optional[str] = Field(
        None,
        description=(
            "Working directory for sbatch --chdir. When session_id is provided on "
            "the parent DeceptionJobSubmissionRequest, this is automatically set to "
            "~/adept-workspace/{session_id}/ — you rarely need to set this manually. "
            "Output files (slurm-{jobid}.out) land here."
        ),
    )
    array: Optional[str] = Field(
        None,
        description=(
            "Job array specification for submitting many similar tasks. "
            "Examples: '0-9' (10 tasks), '1-100%10' (100 tasks, max 10 concurrent). "
            "Each array task gets environment variable SLURM_ARRAY_TASK_ID."
        ),
    )


class DeceptionJobSubmissionRequest(BaseModel):
    """Complete job submission request for Deception cluster: spec + script + session_id.

    Structure: {job_spec: {...}, script: "...", session_id: "..."}
    The script is a TOP-LEVEL field, NOT nested inside job_spec.

    This model is used by deception_submit_job which submits via SSH + sbatch
    (NOT via slurmrestd REST API). The transport layer (FabricSSHTransport)
    writes the script to the cluster and runs sbatch with the spec parameters.

    IMPORTANT: Always provide session_id if you plan to read the job's output
    later via workspace_read_file. Without session_id, output goes to a
    non-deterministic location and cannot be retrieved programmatically.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_spec": {
                        "job_name": "hello_world",
                        "partition": "short",
                        "nodes": 1,
                        "ntasks": 1,
                        "cpus_per_task": 1,
                        "time_limit": "00:10:00",
                    },
                    "script": "#!/bin/bash\necho \"Hello from $(hostname)\"\ndate\n",
                    "session_id": "mcp_abc123",
                },
                {
                    "job_spec": {
                        "job_name": "fba_cobrapy",
                        "nodes": 1,
                        "ntasks": 1,
                        "cpus_per_task": 4,
                        "memory": "16G",
                        "time_limit": "01:00:00",
                    },
                    "script": "#!/bin/bash\nmodule load python/3.11 gurobi/11.0\npython run_fba.py model.xml\n",
                    "session_id": "mcp_session_xyz789",
                },
            ]
        }
    )

    job_spec: DeceptionJobSpec = Field(
        ...,
        description=(
            "Resource specification for the batch job (nodes, CPUs, memory, time). "
            "Maps to sbatch CLI options."
        ),
    )
    script: str = Field(
        ...,
        description=(
            "Complete bash script content to execute on the compute node. "
            "MUST start with '#!/bin/bash' shebang line. "
            "This is a TOP-LEVEL field — do NOT nest it inside job_spec. "
            "Include all module load commands, environment setup, and the "
            "actual computation. Output goes to slurm-{jobid}.out in the "
            "workspace directory when session_id is provided."
        ),
    )
    session_id: Optional[str] = Field(
        None,
        description=(
            "MCP session ID for workspace isolation and output routing. "
            "CRITICAL for output retrieval: when provided, the transport layer "
            "sets --chdir and --output to $HOME/adept-workspace/{session_id}/, "
            "guaranteeing output lands where workspace_read_file can find it. "
            "Without session_id, output goes to Slurm's default location and "
            "cannot be retrieved via workspace tools. "
            "Use the MCP Session ID from your system prompt. "
            "You MUST pass this on every job submission."
        ),
    )
    output_dir: Optional[str] = Field(
        None,
        description=(
            "Explicit absolute path for Slurm output files (slurm-%j.out). "
            "Overrides the default session workspace output path. Use this when "
            "you need output in a specific directory (e.g., /scratch/{user}/logs/). "
            "The directory MUST exist on the cluster before job submission. "
            "When omitted, output goes to $HOME/adept-workspace/{session_id}/ "
            "if session_id is provided, or Slurm's default CWD otherwise."
        ),
    )
    timeout_seconds: Optional[int] = Field(
        None,
        ge=1,
        le=300,
        description=(
            "SSH command timeout in seconds. Overrides the cluster default "
            "(30 seconds). Use for jobs with large scripts or slow network "
            "conditions. Range: 1-300 seconds. Example: 60 for a complex "
            "submission with large heredoc content."
        ),
    )


class DeceptionJobListFilters(BaseModel):
    """Optional filters for deception_list_jobs (squeue-based, active jobs only).

    IMPORTANT: This filters the ACTIVE scheduler queue only. Jobs that have
    already completed, failed, or been cancelled are NOT visible via list_jobs.
    To check a specific completed job, use deception_get_job_details with the job ID.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"user": "rigo160"},
                {"user": "rigo160", "state": "RUNNING"},
            ]
        }
    )

    user: Optional[str] = Field(
        None,
        description=(
            "Filter by Slurm username (e.g., 'rigo160'). Shows only jobs owned by "
            "this user. Without this, shows all jobs visible to the authenticated user."
        ),
    )
    state: Optional[str] = Field(
        None,
        description=(
            "Filter by active job state. Valid values: PENDING, RUNNING, SUSPENDED. "
            "NOTE: COMPLETED, FAILED, CANCELLED, TIMEOUT will always return empty "
            "because finished jobs leave squeue immediately. Use "
            "deception_get_job_details to query completed job history via sacct."
        ),
    )
