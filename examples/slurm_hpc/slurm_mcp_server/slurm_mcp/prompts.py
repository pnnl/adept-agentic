"""
SLURM Job Prompts
=================

FastMCP prompts for guided SLURM job operations.
Adapted for ADEPT: no ctx parameter (auth handled at Tier 1).
"""

from typing import Optional
from fastmcp.exceptions import PromptError

# Import app instance to register prompts directly
from .app import app


@app.prompt
async def check_running_jobs() -> str:
    """Prompt to check user's running jobs."""
    try:
        return """I'd like to check the status of my running SLURM jobs. Please:

1. List my current jobs using list_cluster_jobs
2. Show details for any running jobs
3. Summarize the status - how many running, pending, completed
4. Alert me if any jobs have failed or need attention

Focus on jobs that need my attention or action."""

    except Exception as e:
        if isinstance(e, PromptError):
            raise
        raise PromptError(f"Failed to generate running jobs prompt: {str(e)}")


@app.prompt
async def submit_computation_job(project_dir: str, script_name: str) -> str:
    """Prompt to submit a computation job."""
    try:
        return f"""I need to submit a computation job with these details:

**Project Directory**: {project_dir}
**Script**: {script_name}

Please help me create and submit a SLURM job with:

1. Appropriate CPU and memory allocation
2. Reasonable time limit
3. Proper output/error file paths in the project directory
4. Environment setup
5. Error handling and logging

Use the submit_slurm_job tool with a complete job specification and script.
Check available partitions with get_cluster_summary first."""

    except Exception as e:
        if isinstance(e, PromptError):
            raise
        raise PromptError(
            f"Failed to generate computation job prompt: {str(e)}"
        )


@app.prompt
async def cluster_status_overview() -> str:
    """Prompt for comprehensive cluster status overview."""
    try:
        return """Please provide a comprehensive overview of the SLURM cluster status:

1. **Connectivity**: Test with ping to ensure the cluster is reachable
2. **Job Queue**: Show current jobs with list_cluster_jobs
3. **Resources**: Check available partitions and nodes
4. **Summary**: Provide insights on:
   - How busy is the cluster?
   - Which partitions have capacity?
   - Any patterns in job failures or long wait times?
   - Recommendations for job submission

Format the response to be clear and actionable for planning my work."""

    except Exception as e:
        if isinstance(e, PromptError):
            raise
        raise PromptError(
            f"Failed to generate cluster status prompt: {str(e)}"
        )


@app.prompt
async def job_submission_guide(job_type: Optional[str] = None) -> str:
    """Prompt for job submission guidance."""
    try:
        if job_type:
            return f"""I need help submitting a {job_type} job to SLURM. Please:

1. Show me the appropriate template from resource slurm://docs/job-templates
2. Explain the key parameters I need to set for {job_type} jobs
3. Provide a complete example with:
   - Proper resource allocation
   - Suitable partition selection
   - Good practices for file paths and output
   - Script structure and error handling

4. Help me understand any special considerations for {job_type} jobs

Make it practical and ready to use."""
        else:
            return """I need guidance on submitting SLURM jobs. Please:

1. Show me available job templates from resource slurm://docs/job-templates
2. Explain the key parameters I should understand
3. Help me choose the right approach based on my needs:
   - Single job vs job arrays
   - Short vs long-running jobs

4. Provide the SLURM guide from resource slurm://docs/usage-guide for comprehensive help

Make recommendations based on best practices."""

    except Exception as e:
        if isinstance(e, PromptError):
            raise
        raise PromptError(
            f"Failed to generate job submission guide prompt: {str(e)}"
        )
