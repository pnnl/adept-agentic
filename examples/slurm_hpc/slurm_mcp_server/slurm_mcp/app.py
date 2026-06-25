#!/usr/bin/env python3
"""
SLURM MCP Server
================

FastMCP server with SLURM cluster management capabilities.
Adapted for ADEPT framework: no inbound authentication (handled by Tier 1 gateway).
"""

import argparse
import logging
import os

from fastmcp import FastMCP

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure logging based on SLURM_MCP_LOG_LEVEL env var (default: INFO)
_log_level = os.getenv("SLURM_MCP_LOG_LEVEL", "INFO").upper()
_log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_log_datefmt = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format=_log_format,
    datefmt=_log_datefmt,
    force=True,
)
logger = logging.getLogger("slurm_mcp")


def _apply_log_format_to_uvicorn():
    """Force our timestamp format onto Uvicorn's access/error loggers."""
    formatter = logging.Formatter(_log_format, datefmt=_log_datefmt)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        for handler in uv_logger.handlers:
            handler.setFormatter(formatter)
        if not uv_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            uv_logger.addHandler(handler)
            uv_logger.propagate = False


def _uvicorn_log_config():
    """Build a Uvicorn log_config dict that uses our timestamp format.

    Uvicorn replaces logger formatters at startup unless log_config is provided.
    Uses Uvicorn's own AccessFormatter (which supports %(client_addr)s etc.)
    but with our timestamp-prefixed format string.
    """
    _access_fmt = "%(asctime)s %(levelname)s [uvicorn.access] %(client_addr)s - \"%(request_line)s\" %(status_code)s"
    _default_fmt = _log_format
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(asctime)s %(levelprefix)s [%(name)s] %(message)s",
                "datefmt": _log_datefmt,
                "use_colors": False,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": _access_fmt,
                "datefmt": _log_datefmt,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }

# Create the FastMCP app instance (no auth — ADEPT handles auth at Tier 1)
app = FastMCP(
    name="SLURM HPC Cluster Management",
    instructions="""
    SLURM HPC cluster management server for submitting and monitoring batch jobs
    on a high-performance computing cluster.

    WORKFLOW FOR SUBMITTING JOBS:
    1. Use get_cluster_summary to check cluster availability and partitions
    2. Use submit_slurm_job to submit a batch job with a script and job spec
    3. Use get_job_details with the returned job_id to monitor progress
    4. Use list_cluster_jobs to see all jobs in the queue

    AVAILABLE TOOLS:
    - submit_slurm_job: Submit a batch job (requires job spec + bash script)
    - get_job_details: Check status of a specific job by ID
    - cancel_slurm_job: Cancel a running or pending job
    - ping: Test cluster connectivity
    - list_cluster_jobs: List jobs with optional filters (state, user, partition)
    - get_cluster_summary: Full cluster overview (nodes, jobs, partitions, recommendations)

    JOB SCRIPT EXAMPLE:
    #!/bin/bash
    echo "Running on $(hostname)"
    python3 my_analysis.py

    The current_working_directory for jobs defaults to /data (shared workspace).
    Job outputs (stdout/stderr) are written to /data by default.
    """,
)


@app.custom_route("/health", methods=["GET"])
async def health(request):
    """Health check endpoint for Docker healthcheck and nginx proxy."""
    from starlette.responses import JSONResponse
    return JSONResponse({
        "status": "healthy",
        "server": "slurm-mcp",
        "mcp_tools": [
            "submit_slurm_job",
            "get_job_details",
            "cancel_slurm_job",
            "ping",
            "list_cluster_jobs",
            "get_cluster_summary",
            "deception_ping",
            "deception_submit_job",
            "deception_get_job_details",
            "deception_cancel_job",
            "deception_list_jobs",
            "deception_get_cluster_summary",
            "tahoma_ping",
            "tahoma_submit_job",
            "tahoma_get_job_details",
            "tahoma_cancel_job",
            "tahoma_list_jobs",
            "tahoma_get_cluster_summary",
            "hpc_list_clusters",
            "hpc_check_ssh_key",
            "hpc_generate_ssh_key",
            "hpc_test_ssh_connectivity",
            "hpc_get_provisioning_instructions",
            "workspace_list_files",
            "workspace_upload_file",
            "workspace_download_file",
            "workspace_read_file",
        ],
    })


def main():
    """Main entry point for the SLURM MCP server."""
    # Import modules to register tools, resources, and prompts via decorators
    from . import tools
    from . import resources
    from . import prompts
    from .deception import tools as _deception_tools  # noqa: F401
    from .tahoma import tools as _tahoma_tools  # noqa: F401
    from . import ssh_key_tools as _ssh_key_tools  # noqa: F401
    from . import workspace_tools as _workspace_tools  # noqa: F401

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="SLURM MCP Server")
    parser.add_argument(
        "--transport",
        default="streamable-http",
        choices=["stdio", "streamable-http", "sse"],
        help="Transport type (default: streamable-http)",
    )
    parser.add_argument(
        "--port", type=int, default=8002, help="Port for HTTP/SSE transport"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host for HTTP/SSE transport"
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("SLURM_MCP_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO, override with SLURM_MCP_LOG_LEVEL env var)",
    )
    args = parser.parse_args()

    # Apply CLI log level override
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    logger.info(
        "Starting SLURM MCP Server (transport=%s, port=%s, log_level=%s)",
        args.transport, args.port, args.log_level,
    )

    # Force our log format onto Uvicorn's loggers (adds timestamps to access logs)
    _apply_log_format_to_uvicorn()

    # Start server
    try:
        if args.transport in ("streamable-http", "sse"):
            app.run(
                transport=args.transport,
                port=args.port,
                host=args.host,
                uvicorn_config={"log_config": _uvicorn_log_config()},
            )
        else:
            app.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error("Server error: %s", e)
        exit(1)


# Main entry point
if __name__ == "__main__":
    main()
