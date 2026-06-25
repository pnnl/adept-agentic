"""
SLURM MCP Resources
===================

SLURM cluster documentation and information resources.
Adapted for ADEPT: uses service credentials instead of ctx auth.
"""

import json

from fastmcp.exceptions import ResourceError

from .client import get_service_client
from .config import config

# Import app instance to register resources directly
from .app import app


# === Documentation Resources ===


@app.resource("slurm://docs/job-templates")
async def get_job_templates() -> str:
    """
    Get job submission templates and examples.

    Returns:
        JSON-formatted job templates with examples for different use cases
    """
    templates = {
        "simple_cpu_job": {
            "name": "Simple CPU Job",
            "description": "Basic CPU-only job template",
            "example": {
                "job": {
                    "name": "cpu_task",
                    "partition": "normal",
                    "nodes": "1",
                    "cpus_per_task": 4,
                    "memory": "8G",
                    "time_limit": 60,
                    "current_working_directory": "/data",
                    "standard_output": "/data/job_%j.out",
                    "standard_error": "/data/job_%j.err",
                },
                "script": (
                    "#!/bin/bash\n"
                    "#SBATCH --job-name=cpu_task\n"
                    "echo 'Starting CPU job'\n"
                    "date\n"
                    "# Your commands here\n"
                    "sleep 30\n"
                    "echo 'Job completed'\n"
                    "date"
                ),
            },
        },
        "multi_node_job": {
            "name": "Multi-Node Job",
            "description": "Job running across multiple compute nodes",
            "example": {
                "job": {
                    "name": "multi_node_task",
                    "partition": "normal",
                    "nodes": "2",
                    "cpus_per_task": 2,
                    "memory": "4G",
                    "time_limit": 120,
                    "current_working_directory": "/data",
                    "standard_output": "/data/multi_%j.out",
                    "standard_error": "/data/multi_%j.err",
                },
                "script": (
                    "#!/bin/bash\n"
                    "#SBATCH --job-name=multi_node_task\n"
                    "echo 'Multi-node job on $(hostname)'\n"
                    "echo 'Allocated nodes: $SLURM_JOB_NODELIST'\n"
                    "echo 'Number of nodes: $SLURM_JOB_NUM_NODES'\n"
                    "# Your parallel commands here\n"
                    "echo 'Job completed'"
                ),
            },
        },
        "array_job": {
            "name": "Array Job",
            "description": "Job array for parameter sweeps",
            "example": {
                "job": {
                    "name": "param_sweep",
                    "partition": "normal",
                    "nodes": "1",
                    "cpus_per_task": 2,
                    "memory": "4G",
                    "time_limit": 120,
                    "current_working_directory": "/data",
                    "standard_output": "/data/sweep_%A_%a.out",
                    "standard_error": "/data/sweep_%A_%a.err",
                },
                "script": (
                    "#!/bin/bash\n"
                    "#SBATCH --job-name=param_sweep\n"
                    "#SBATCH --array=1-10\n"
                    "echo 'Array job ${SLURM_ARRAY_JOB_ID} task ${SLURM_ARRAY_TASK_ID}'\n"
                    "PARAM_VALUE=$(sed -n \"${SLURM_ARRAY_TASK_ID}p\" parameters.txt)\n"
                    "echo \"Running with parameter: $PARAM_VALUE\"\n"
                    "# Your parametric computation here\n"
                    "python3 experiment.py --param $PARAM_VALUE"
                ),
            },
        },
    }

    return json.dumps(
        {
            "templates": templates,
            "usage": "Use these templates as starting points for job submissions with submit_slurm_job",
        },
        indent=2,
    )


@app.resource("slurm://docs/usage-guide")
async def get_slurm_guide() -> str:
    """
    Get comprehensive SLURM usage guide.

    Returns:
        Markdown-formatted SLURM guide
    """
    guide = [
        "# SLURM Usage Guide",
        "",
        "## Quick Start",
        "",
        "1. **Check cluster status**: Use `ping` to test connectivity",
        "2. **List jobs**: Use `list_cluster_jobs` to see current queue",
        "3. **Submit job**: Use `submit_slurm_job` with job spec and script",
        "4. **Monitor job**: Use `get_job_details` with job ID",
        "5. **Cancel if needed**: Use `cancel_slurm_job` with job ID",
        "",
        "## Job Specification Fields",
        "",
        "### Required Fields",
        "- `script`: Job script content (bash script starting with #!/bin/bash)",
        "",
        "### Common Optional Fields",
        "- `name`: Job name (for identification)",
        "- `partition`: Which queue/partition to use",
        "- `nodes`: Number of nodes (default: 1)",
        "- `cpus_per_task`: CPUs per task",
        "- `memory`: Memory allocation (e.g., '8G', '512M')",
        "- `time_limit`: Max runtime in minutes",
        "- `current_working_directory`: Working directory (default: /data)",
        "- `standard_output`: Output file path (use %j for job ID)",
        "- `standard_error`: Error file path",
        "",
        "## Environment Variables",
        "",
        "Key SLURM variables available in jobs:",
        "- `SLURM_JOB_ID`: Unique job identifier",
        "- `SLURM_JOB_NAME`: Job name",
        "- `SLURM_ARRAY_TASK_ID`: Array task ID (for array jobs)",
        "- `SLURM_CPUS_PER_TASK`: Allocated CPUs",
        "- `SLURM_JOB_NODELIST`: Allocated nodes",
        "",
        "## Job States",
        "",
        f"- {config.JOB_STATE_EMOJIS['PENDING']} **PENDING**: Waiting for resources",
        f"- {config.JOB_STATE_EMOJIS['RUNNING']} **RUNNING**: Currently executing",
        f"- {config.JOB_STATE_EMOJIS['COMPLETED']} **COMPLETED**: Finished successfully",
        f"- {config.JOB_STATE_EMOJIS['FAILED']} **FAILED**: Terminated with error",
        f"- {config.JOB_STATE_EMOJIS['CANCELLED']} **CANCELLED**: User cancelled",
        f"- {config.JOB_STATE_EMOJIS['TIMEOUT']} **TIMEOUT**: Exceeded time limit",
        "",
        "## Best Practices",
        "",
        "1. **Always specify time limits** - helps scheduler optimize placement",
        "2. **Use specific partitions** - don't rely on defaults",
        "3. **Redirect output** - capture stdout/stderr to /data",
        "4. **Test small** - verify with short test jobs first",
        "5. **Monitor resources** - check job efficiency",
        "",
        "## Troubleshooting",
        "",
        "- **Job pending too long**: Check partition availability with get_cluster_summary",
        "- **Job failed immediately**: Check script syntax and paths",
        "- **Out of memory**: Increase memory allocation",
        "- **Time limit exceeded**: Extend time_limit or optimize code",
        "",
        "## Need More Help?",
        "",
        "- Check job templates: `slurm://docs/job-templates`",
        "- View cluster resources: `slurm://cluster/partitions`",
        "- List current jobs: Use `list_cluster_jobs` tool",
    ]

    return "\n".join(guide)


@app.resource("slurm://cluster/tres")
async def get_cluster_tres() -> str:
    """Get TRES (Trackable RESource) information."""
    lines = [
        "# SLURM TRES (Trackable RESource) Types",
        "",
        "TRES allows SLURM to track and limit various resource types:",
        "",
        "## Common TRES Types",
        "",
        "| Type | Description | Example Usage |",
        "|------|-------------|---------------|",
        "| `cpu` | CPU cores | `--tres-per-job=cpu=4` |",
        "| `mem` | Memory in MB | `--tres-per-job=mem=8G` |",
        "| `node` | Nodes | `--tres-per-job=node=1` |",
        "| `billing` | Billing units | `--tres-per-job=billing=100` |",
        "",
        "## Usage Examples",
        "",
        "- **CPU Job**: `tres_per_job: 'cpu=8,mem=16G'`",
        "",
        "## In Job Submissions",
        "",
        "```json",
        "{",
        '  "job": {',
        '    "tres_per_job": "cpu=8,mem=16G",',
        '    "partition": "normal"',
        "  }",
        "}",
        "```",
    ]

    return "\n".join(lines)


# === Cluster Information Resources ===


@app.resource(
    "slurm://cluster/nodes",
    description="Get cluster compute nodes information and status",
)
async def get_cluster_nodes() -> str:
    """Get cluster nodes information."""
    try:
        username, client_ctx = get_service_client()

        async with client_ctx as client:
            result = await client.request(
                "GET", f"/slurm/{config.api_version}/nodes"
            )

        nodes = result.get("nodes", [])

        lines = ["# SLURM Cluster Nodes", ""]
        lines.append(f"Found **{len(nodes)}** nodes:")
        lines.append("")

        if nodes:
            lines.append("| Name | State | CPUs | Memory | Partitions |")
            lines.append("|------|-------|------|--------|------------|")

            for node in nodes[:20]:
                name = node.get("name", "Unknown")
                state = (
                    node.get("state", ["UNKNOWN"])[0]
                    if node.get("state")
                    else "UNKNOWN"
                )
                cpus = node.get("cpus", "N/A")

                real_memory = node.get("real_memory", "N/A")
                if isinstance(real_memory, dict):
                    memory = (
                        f"{real_memory.get('number', 'N/A')} MB"
                        if real_memory.get("number")
                        else "N/A"
                    )
                else:
                    memory = str(real_memory) if real_memory else "N/A"

                partitions = ", ".join(node.get("partitions", [])) or "N/A"

                state_emoji = config.NODE_STATE_EMOJIS.get(state, "")
                lines.append(
                    f"| {name} | {state_emoji} {state} | {cpus} | {memory} | {partitions} |"
                )

            if len(nodes) > 20:
                lines.append(f"\n*... and {len(nodes) - 20} more nodes*")
        else:
            lines.append("No nodes found.")

        return "\n".join(lines)

    except Exception as e:
        if isinstance(e, ResourceError):
            raise
        raise ResourceError(f"Failed to retrieve cluster nodes: {str(e)}")


@app.resource(
    "slurm://cluster/partitions",
    description="Get cluster partitions and scheduling information",
)
async def get_cluster_partitions() -> str:
    """Get cluster partitions information."""
    try:
        username, client_ctx = get_service_client()

        async with client_ctx as client:
            result = await client.request(
                "GET", f"/slurm/{config.api_version}/partitions"
            )

        partitions = result.get("partitions", [])

        lines = ["# SLURM Cluster Partitions", ""]
        lines.append(f"Found **{len(partitions)}** partitions:")
        lines.append("")

        if partitions:
            lines.append(
                "| Name | State | Nodes | Time Limit | Default Memory |"
            )
            lines.append(
                "|------|-------|-------|------------|----------------|"
            )

            for partition in partitions:
                name = partition.get("name", "Unknown")
                state = (
                    partition.get("state", ["UNKNOWN"])[0]
                    if partition.get("state")
                    else "UNKNOWN"
                )
                total_nodes = partition.get("total_nodes", "N/A")
                max_time = partition.get("maximum_time", {})
                if isinstance(max_time, dict):
                    time_limit = (
                        f"{max_time.get('number', 'N/A')} min"
                        if max_time.get("number")
                        else "N/A"
                    )
                else:
                    time_limit = str(max_time) if max_time else "N/A"

                default_memory = partition.get("default_memory_per_node", "N/A")
                if isinstance(default_memory, dict):
                    default_memory = (
                        f"{default_memory.get('number', 'N/A')} MB"
                        if default_memory.get("number")
                        else "N/A"
                    )

                lines.append(
                    f"| {name} | {state} | {total_nodes} | {time_limit} | {default_memory} |"
                )
        else:
            lines.append("No partitions found.")

        return "\n".join(lines)

    except Exception as e:
        if isinstance(e, ResourceError):
            raise
        raise ResourceError(
            f"Failed to retrieve cluster partitions: {str(e)}"
        )
