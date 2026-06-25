"""Pydantic models for Tahoma HPC tool inputs."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TahomaJobSpec(BaseModel):
    """Resource specification for a Tahoma batch job."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_name": "hello_world",
                    "partition": "normal",
                    "nodes": 1,
                    "ntasks": 1,
                    "cpus_per_task": 1,
                    "time_limit": "00:10:00",
                }
            ]
        }
    )

    job_name: str = Field(..., description="Job name for tracking")
    partition: Optional[str] = Field(
        None,
        description=(
            "Partition (queue) to submit to. Call tahoma_get_cluster_summary "
            "first to discover valid partitions. "
            "Do NOT guess partition names — invalid partitions cause submission failure."
        ),
    )
    account: Optional[str] = Field(None, description="Account for job charging")
    nodes: int = Field(1, ge=1, description="Number of nodes requested")
    ntasks: int = Field(1, ge=1, description="Number of tasks")
    cpus_per_task: int = Field(1, ge=1, description="CPUs per task")
    memory: Optional[str] = Field(
        None, description="Memory per node (e.g., '16G', '4096M')"
    )
    time_limit: str = Field("01:00:00", description="Wall time limit (HH:MM:SS)")
    working_directory: Optional[str] = Field(
        None,
        description=(
            "Working directory on the COMPUTE NODE. Output files land here. "
            "WARNING: This path may be node-local and unreachable from login nodes. "
            "Use workspace_read_file or workspace_download_file to retrieve output."
        ),
    )
    array: Optional[str] = Field(
        None, description="Job array spec (e.g., '0-9', '1-100%10')"
    )


class TahomaJobSubmissionRequest(BaseModel):
    """Complete job submission request: spec + script.

    Structure: {job_spec: {...}, script: "...", session_id: "..."}
    The script is a TOP-LEVEL field, NOT nested inside job_spec.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_spec": {
                        "job_name": "hello_world",
                        "partition": "normal",
                        "nodes": 1,
                        "ntasks": 1,
                        "cpus_per_task": 1,
                        "time_limit": "00:10:00",
                    },
                    "script": "#!/bin/bash\necho \"Hello from $(hostname)\"\ndate\n",
                    "session_id": "mcp_abc123",
                }
            ]
        }
    )

    job_spec: TahomaJobSpec
    script: str = Field(
        ...,
        description=(
            "Bash script content to execute. Must start with '#!/bin/bash'. "
            "This is a TOP-LEVEL field — do NOT nest it inside job_spec."
        ),
    )
    session_id: Optional[str] = Field(
        None,
        description=(
            "MCP session ID for workspace isolation. REQUIRED for output retrieval "
            "workflows. When provided, the script is persisted to "
            "~/adept-workspace/{session_id}/ on the cluster for provenance tracking. "
            "Without session_id, the script goes to /tmp/ and output cannot be "
            "retrieved via workspace tools."
        ),
    )


class TahomaJobListFilters(BaseModel):
    """Optional filters for listing jobs."""

    user: Optional[str] = Field(None, description="Filter by username")
    state: Optional[str] = Field(
        None, description="Filter by state (PENDING, RUNNING, COMPLETED)"
    )
