"""
Output Formatting Utilities
============================

Utility functions for formatting SLURM data for display.
"""

from typing import Dict, Any, Union
from datetime import datetime


def format_job_details(
    job: Dict[str, Any],
    job_id: str,
    config,
    resource_prefix: str = "Job Details",
) -> str:
    """
    Format job data into markdown for consistent presentation.

    Args:
        job: Job data from SLURM API
        job_id: Job ID string
        config: SLURM configuration for emojis
        resource_prefix: Prefix for the header

    Returns:
        Markdown-formatted job details
    """

    def safe_get_value(data: Union[Dict, Any], default: str = "N/A") -> str:
        """Safely extract value from dict or return as string."""
        if isinstance(data, dict):
            return str(data.get("number", default))
        return str(data) if data else default

    def format_timestamp(ts):
        if isinstance(ts, dict):
            ts = ts.get("number", 0)
        if ts and ts != 0:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        return "N/A"

    def format_duration(seconds):
        if isinstance(seconds, str):
            try:
                seconds = int(seconds)
            except (ValueError, TypeError):
                return "N/A"
        if not seconds or seconds <= 0:
            return "N/A"
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    # Get job state and add emoji
    job_state = job.get("job_state", ["UNKNOWN"])[0]
    state_emoji = config.JOB_STATE_EMOJIS.get(job_state, "")

    # Build markdown output
    lines = [
        f"# {resource_prefix}: {job.get('name', 'Unnamed')} (ID: {job_id})",
        "",
        "## Status",
        f"- **State**: {state_emoji} **{job_state}**",
        f"- **User**: {job.get('user_name', 'Unknown')}",
        f"- **Partition**: {job.get('partition', 'N/A')}",
        f"- **Account**: {job.get('account', 'N/A')}",
        "",
        "## Resources",
        f"- **Nodes**: {job.get('nodes', 'N/A')}",
        f"- **CPUs**: {safe_get_value(job.get('cpus'), 'N/A')}",
        f"- **Memory**: {job.get('tres_alloc_str', 'N/A')}",
        f"- **Working Directory**: {job.get('current_working_directory', 'N/A')}",
        "",
        "## Timing",
        f"- **Submitted**: {format_timestamp(job.get('submit_time'))}",
        f"- **Started**: {format_timestamp(job.get('start_time'))}",
        f"- **Ended**: {format_timestamp(job.get('end_time'))}",
        f"- **Time Limit**: {format_duration(safe_get_value(job.get('time_limit'), '0'))}",
        f"- **Elapsed Time**: {format_duration(safe_get_value(job.get('run_time'), '0'))}",
        "",
        "## Files",
        f"- **Standard Output**: `{job.get('standard_output', 'N/A')}`",
        f"- **Standard Error**: `{job.get('standard_error', 'N/A')}`",
        "",
    ]

    # Add node allocation info if available
    if job.get("job_resources", {}).get("nodes"):
        lines.extend(["## Node Allocation", ""])
        nodes = job["job_resources"]["nodes"]
        if isinstance(nodes, list):
            for node in nodes[:5]:
                node_name = node.get("name", "Unknown")
                cpus = node.get("cpus", "N/A")
                lines.append(f"- **{node_name}**: {cpus} CPUs")
            if len(nodes) > 5:
                lines.append(f"- *(... and {len(nodes) - 5} more nodes)*")
        lines.append("")

    # Add exit status if job is completed
    if job.get("exit_code") is not None:
        exit_code = int(safe_get_value(job["exit_code"], "0"))
        lines.extend(
            [
                "## Exit Status",
                f"- **Exit Code**: {exit_code}",
                f"- **Status**: {'Success' if exit_code == 0 else 'Failed'}",
                "",
            ]
        )

    # Add job script if available
    if job.get("batch_script"):
        script = job["batch_script"]
        lines.extend(["## Job Script", "```bash", script, "```", ""])

    # Add any error or reason information
    if job.get("state_reason"):
        lines.extend(
            [
                "## Additional Information",
                f"- **State Reason**: {job['state_reason']}",
                "",
            ]
        )

    return "\n".join(lines)


def format_job_list(jobs: list, config) -> str:
    """Format job list as markdown table."""
    lines = ["# SLURM Cluster Jobs", ""]
    lines.append(f"Found **{len(jobs)}** jobs:")
    lines.append("")

    if jobs:
        lines.append(
            "| Job ID | Name | User | State | Partition | Nodes | Submit Time |"
        )
        lines.append(
            "|--------|------|------|-------|-----------|-------|-------------|"
        )

        for job in jobs:
            job_id = job.get("job_id", "?")
            name = job.get("name", "-") or "-"
            user = job.get("user_name", "?")
            state = (
                job.get("job_state", ["UNKNOWN"])[0]
                if job.get("job_state")
                else "UNKNOWN"
            )
            partition_name = job.get("partition", "-") or "-"
            nodes = job.get("nodes", "-") or "-"

            submit_time = job.get("submit_time")
            if submit_time and isinstance(submit_time, int):
                submit_str = datetime.fromtimestamp(submit_time).strftime(
                    "%m-%d %H:%M"
                )
            else:
                submit_str = "-"

            lines.append(
                f"| {job_id} | {name} | {user} | {state} | {partition_name} | {nodes} | {submit_str} |"
            )
    else:
        lines.append("No jobs found matching the specified criteria.")

    return "\n".join(lines)
