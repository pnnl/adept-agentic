"""
SLURM Job Models
================

Pydantic models for SLURM job specifications and requests.
Enhanced with verbose field descriptions for agent effectiveness.
"""

from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class JobSpec(BaseModel):
    """SLURM job specification. Defines resource requirements and execution parameters
    for a batch job on the HPC cluster."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "hello_world",
                    "partition": "normal",
                    "nodes": "1",
                    "cpus_per_task": 1,
                    "time_limit": 10,
                    "current_working_directory": "/data",
                    "standard_output": "/data/job_%j.out",
                    "environment": ["PATH=/bin:/usr/bin:/usr/local/bin:."],
                }
            ]
        }
    )

    name: Optional[str] = Field(
        None,
        description=(
            "Human-readable job name for identification in queue listings. "
            "Must contain only alphanumeric characters, hyphens, and underscores. "
            "Example: 'protein-folding-run-42'"
        ),
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    nodes: Optional[str] = Field(
        None,
        description=(
            "Number of compute nodes to allocate. Can be a single number ('1') "
            "or a range ('1-4') for flexible allocation. Most jobs need '1' unless "
            "running MPI or multi-node workflows."
        ),
        pattern=r"^\d+(-\d+)?$",
    )
    partition: Optional[str] = Field(
        None,
        description=(
            "Target partition (queue) for the job. Use get_cluster_summary to see "
            "available partitions and their current load. Common names: 'normal', "
            "'batch', 'debug'. If omitted, uses the cluster default partition."
        ),
        max_length=32,
    )
    current_working_directory: str = Field(
        "/data",
        description=(
            "Directory where the job script executes. Defaults to '/data' which is "
            "the shared workspace visible to all compute nodes. Job output files "
            "will be written relative to this directory."
        ),
    )
    environment: List[str] = Field(
        default=["PATH=/bin:/usr/bin:/usr/local/bin:."],
        description=(
            "List of environment variables passed to the job as 'KEY=VALUE' strings. "
            "Always include PATH. Example: ['PATH=/bin:/usr/bin', 'MY_DATA=/data/input']"
        ),
    )
    time_limit: Optional[int] = Field(
        None,
        description=(
            "Maximum wall-clock time in minutes. Job is killed if exceeded. "
            "Examples: 60 (1 hour), 1440 (1 day), 10080 (1 week max). "
            "Set conservatively — shorter limits get higher queue priority."
        ),
        gt=0,
        le=10080,
    )
    memory: Optional[str] = Field(
        None,
        description=(
            "Memory per node. Specify with unit suffix: '4G' (gigabytes), '512M' (megabytes). "
            "If omitted, uses partition default. Over-requesting wastes resources."
        ),
        pattern=r"^\d+[KMG]?$",
    )
    cpus_per_task: Optional[int] = Field(
        None,
        description=(
            "Number of CPU cores per task. Use 1 for serial jobs. "
            "For multithreaded Python/NumPy, match your thread count. Max 128."
        ),
        gt=0,
        le=128,
    )
    standard_output: Optional[str] = Field(
        None,
        description=(
            "File path for stdout. Use %%j for job ID substitution. "
            "Example: '/data/job_%%j.out'. Defaults to slurm-%%j.out in working directory."
        ),
    )
    standard_error: Optional[str] = Field(
        None,
        description=(
            "File path for stderr. Use %%j for job ID substitution. "
            "Example: '/data/job_%%j.err'. Defaults to slurm-%%j.out in working directory."
        ),
    )
    tres_per_job: Optional[str] = Field(
        None,
        description=(
            "TRES (Trackable RESource) specification for advanced resource requests. "
            "Example: 'cpu=8,mem=16G'. For GPU jobs: 'gres/gpu=1,mem=30G'."
        ),
    )
    account: Optional[str] = Field(
        None,
        description="Account to charge for resource usage.",
        max_length=32,
    )


class JobSubmissionRequest(BaseModel):
    """Complete job submission request for slurmrestd REST API (NOT SSH-based clusters).

    WARNING: This model is used by submit_slurm_job which calls slurmrestd.
    For SSH-based clusters (Deception, Tahoma), use the cluster-specific tools:
      - Deception: deception_submit_job (uses DeceptionJobSubmissionRequest)
      - Tahoma: tahoma_submit_job (uses TahomaJobSubmissionRequest)

    Structure: {job: {...}, script: "..."}
    The script is a TOP-LEVEL field, NOT nested inside job.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job": {
                        "name": "hello_world",
                        "partition": "normal",
                        "nodes": "1",
                        "cpus_per_task": 1,
                        "time_limit": 10,
                        "current_working_directory": "/data",
                        "standard_output": "/data/job_%j.out",
                        "environment": ["PATH=/bin:/usr/bin:/usr/local/bin:."],
                    },
                    "script": "#!/bin/bash\necho \"Hello from $(hostname)\"\ndate\n",
                }
            ]
        }
    )

    job: JobSpec = Field(
        ...,
        description=(
            "Job specification defining resource requirements (nodes, CPUs, memory, "
            "time limit, partition). All fields are optional except the request itself."
        ),
    )
    script: str = Field(
        ...,
        description=(
            "Bash script content to execute on the cluster. Must start with '#!/bin/bash'. "
            "This is a TOP-LEVEL field — do NOT nest it inside job. "
            "The script runs in the current_working_directory specified in the job spec "
            "(default: /data). "
            "Example: '#!/bin/bash\\necho Hello from $(hostname)\\npython3 analysis.py'"
        ),
    )


class JobListFilters(BaseModel):
    """Filters for list_cluster_jobs (slurmrestd REST API, NOT SSH-based clusters).

    WARNING: This model is used by list_cluster_jobs which calls slurmrestd.
    For SSH-based clusters (Deception, Tahoma), use the cluster-specific tools:
      - Deception: deception_list_jobs (uses DeceptionJobListFilters)
      - Tahoma: tahoma_list_jobs (uses TahomaJobListFilters)

    All fields are optional — omit to list all jobs.
    """

    state: Optional[List[str]] = Field(
        None,
        description=(
            "Filter by job state(s). Valid values: RUNNING, PENDING, COMPLETED, "
            "FAILED, CANCELLED, TIMEOUT. Multiple states can be specified."
        ),
    )
    user: Optional[str] = Field(
        None,
        description="Filter by username. Only shows jobs owned by this user.",
        max_length=32,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    partition: Optional[str] = Field(
        None,
        description="Filter by partition name (e.g., 'normal', 'batch').",
        max_length=32,
    )
    limit: Optional[int] = Field(
        20,
        description="Maximum number of jobs to return (default: 20, max: 1000).",
        gt=0,
        le=1000,
    )
    offset: Optional[int] = Field(
        0,
        description="Number of jobs to skip for pagination.",
        ge=0,
    )
