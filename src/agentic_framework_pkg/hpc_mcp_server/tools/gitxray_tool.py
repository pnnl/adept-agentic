"""
This module registers the GitXRay tool with the HPC MCP server.

It provides a tool for scanning public GitHub repositories for secrets and
sensitive data using the GitXRay tool, orchestrated via a Nextflow pipeline.
"""
from fastmcp import FastMCP, Context
from ...logger_config import get_logger
import asyncio
from typing import Dict, Any, Optional
import uuid
import tempfile
import os
import json

logger = get_logger(__name__)

async def _run_in_thread(func, *args, **kwargs):
    """Runs a synchronous function in a separate thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

NEXTFLOW_GITXRAY_SCRIPT_PATH_ENV_VAR = "NEXTFLOW_GITXRAY_SCRIPT_PATH"
CURR_DIR = os.path.dirname(os.path.abspath(__file__))
# Use the specific env var for this pipeline, falling back to a relative path
NEXTFLOW_SCRIPT_PATH = os.getenv(NEXTFLOW_GITXRAY_SCRIPT_PATH_ENV_VAR, "./gitxray_pipeline.nf")
if not os.path.exists(NEXTFLOW_SCRIPT_PATH):
    # If it's not absolute, make it relative to the current directory (where this tool file is)
    NEXTFLOW_SCRIPT_PATH = os.path.join(CURR_DIR, NEXTFLOW_SCRIPT_PATH)

# Ensure the script exists at the resolved path
if not os.path.exists(NEXTFLOW_SCRIPT_PATH):
    logger.warning(f"Nextflow gitxray script not found at {NEXTFLOW_SCRIPT_PATH} (resolved from env var '{NEXTFLOW_GITXRAY_SCRIPT_PATH_ENV_VAR}' or default).")

def register_tools(mcp: FastMCP):
    """Registers the GitXRay scan tool with the MCP server."""
    @mcp.tool()
    async def scan_github_repository_with_gitxray(
        ctx: Context,
        repo_url: str,
        output_format: str = "json",
        enable_debug: bool = False,
        mcp_session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Scans a public GitHub repository for secrets using GitXRay via Nextflow.
        """
        session_id_for_log = mcp_session_id or f"gitxray_scan_{uuid.uuid4()}"
        await ctx.info(f"Session {session_id_for_log}: Received GitXRay scan request for repository: {repo_url}")

        if not repo_url.startswith("https://github.com/"):
            await ctx.error("Invalid repository URL. Only public GitHub repositories are supported.")
            return {"status": "error", "message": "Invalid repository URL. Must be a public GitHub repository URL."}

        with tempfile.TemporaryDirectory(prefix="nextflow_gitxray_") as temp_work_dir:
            try:
                output_dir = os.path.join(temp_work_dir, "results")
                os.makedirs(output_dir, exist_ok=True)
                output_file_name = "gitxray_report.json"
                enable_debug = False # Hardcoded for simplicity, can be exposed if needed

                # Prepare environment for Nextflow, passing through the GitHub token
                nextflow_env = os.environ.copy()
                gh_token = os.getenv("GH_ACCESS_TOKEN_GITXRAY", "").strip()
                if gh_token:
                    nextflow_env["GH_ACCESS_TOKEN"] = gh_token
                    logger.info("GH_ACCESS_TOKEN set for Nextflow gitxray process.")
                else:
                    logger.warning("GH_ACCESS_TOKEN not set. GitXRay may be rate-limited by GitHub.")

                nextflow_command = [
                    "nextflow", "run", NEXTFLOW_SCRIPT_PATH,
                    "--repo_url", repo_url,
                    "--output_dir", output_dir,
                    "--output_file", output_file_name,
                    "--output_format", output_format,
                    "--enable_debug", str(enable_debug).lower(),
                ]
                await ctx.info(f"Starting GitXRay scan for {repo_url}. This may take a while...")
                logger.info(f"Executing Nextflow gitxray: {' '.join(nextflow_command)}")

                process = await asyncio.create_subprocess_exec(
                    *nextflow_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=nextflow_env,
                    cwd=temp_work_dir  # Ensure Nextflow runs in the temp directory
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    err_msg = f"Nextflow gitxray pipeline execution failed. Return code: {process.returncode}. Stderr: {stderr.decode(errors='ignore')}"
                    await ctx.error(err_msg)
                    logger.error(err_msg)
                    return {"status": "error", "message": "Nextflow gitxray pipeline execution failed.",
                            "details": stderr.decode(errors='ignore'), "log_stdout": stdout.decode(errors='ignore')}

                # Load the report from file
                report_path = os.path.join(output_dir, output_file_name)
                if not os.path.exists(report_path):
                    err_msg = f"Nextflow completed, but result file not found at {report_path}."
                    await ctx.error(err_msg)
                    logger.error(f"{err_msg} Stdout: {stdout.decode(errors='ignore')}")
                    return {"status": "error", "message": err_msg, "log_stdout": stdout.decode(errors='ignore'), "log_stderr": stderr.decode(errors='ignore')}

                with open(report_path, "r") as f:
                    scan_results = json.load(f)

                await ctx.info(f"GitXRay scan completed for {repo_url}.")

                # The result from gitxray is a dictionary. We can return it directly.
                return {"status": "success", "results": scan_results}

            except Exception as e:
                logger.error(f"Error running GitXRay scan for {repo_url}: {e}", exc_info=True)
                await ctx.error(f"Failed to execute GitXRay scan for {repo_url}: {e}")
                return {"status": "error", "message": f"An unexpected error occurred during the GitXRay scan: {str(e)}"}

    logger.info("HPC GitXRay tool registered.")
