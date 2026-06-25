"""
Main entry point for the Sandbox MCP (Multi-Component Protocol) server.

This module initializes the FastAPI application for the sandbox server,
registers the code execution tool, and starts the Uvicorn server.

Architectural Role (in Three-Tier Model):
-   **Tier 3 (Executor):** This service is a highly specialized, stateless
    executor designed for running untrusted code in a secure, isolated
    environment.
-   **Secure Code Execution:** It exposes the `execute_code` tool, which uses
    the `llm-sandbox` library to run code in ephemeral Docker containers,
    providing a strong security boundary.
-   **Multi-Backend Support:** It is designed to support different execution
    backends (Docker or Kubernetes), determined by the `SANDBOX_BACKEND`
    environment variable.
"""
import uvicorn
import asyncio
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
import json

# Load environment variables
if os.path.exists(".env"):
    load_dotenv()
elif os.path.exists("../../.env"):
    load_dotenv(dotenv_path=os.path.join(os.getcwd(), "../../.env"))

from .server import sandbox_mcp
from .tools import code_execution_tool, file_execution_tool
from .session.session_manager import (
    cleanup_expired_sessions_periodically,
    reap_orphaned_processes_periodically,
)
from .executor import shutdown_process_pool
from ..logger_config import get_logger

logger = get_logger(__name__)

# Optional: Middleware for logging requests, similar to other servers
async def sandbox_log_request_middleware(request: Request, call_next):
    """Log incoming requests to the Sandbox server."""
    req_body_bytes = await request.body()
    logger.info(f"Sandbox Server Request: {request.method} {request.url}")
    if req_body_bytes:
        try:
            logger.info(f"Sandbox Request body (JSON): {json.loads(req_body_bytes.decode())}")
        except Exception:
            logger.info(f"Sandbox Request body (raw): {req_body_bytes[:200].decode(errors='ignore')}...")

    async def new_receive():
        return {"type": "http.request", "body": req_body_bytes, "more_body": False}
    new_request = Request(request.scope, receive=new_receive)
    response = await call_next(new_request)
    logger.info(f"Sandbox Server Response: {response.status_code}")
    return response

def setup_sandbox_mcp_server(mcp_instance=sandbox_mcp) -> FastAPI:
    """
    Sets up the Sandbox MCP server instance by registering its tools.
    """
    logger.info("Setting up Sandbox MCP server and registering tools...")
    
    # Setup plots directory for secure file serving
    from .server import setup_plots_directory
    setup_plots_directory()
    
    code_execution_tool.register_tools(mcp_instance)
    file_execution_tool.register_tools(mcp_instance)
    logger.info("Sandbox MCP tools registered.")

    # Get the FastMCP app, which is a Starlette app that expects to be at root
    # Session 62: stateless_http=True eliminates per-process session dicts, enables multi-worker
    fast_mcp_app = mcp_instance.http_app(stateless_http=True)
    original_lifespan = fast_mcp_app.lifespan

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def extended_lifespan(app):
        """Wrap original FastMCP lifespan to add background cleanup tasks."""
        async with original_lifespan(app) as state:
            # Start background cleanup tasks
            session_cleanup_task = asyncio.create_task(
                cleanup_expired_sessions_periodically(interval_minutes=60)
            )
            orphan_reaper_task = asyncio.create_task(
                reap_orphaned_processes_periodically(interval_minutes=5)
            )
            logger.info("Started background tasks: session cleanup (60m) + orphan reaper (5m)")
            try:
                yield state
            finally:
                session_cleanup_task.cancel()
                orphan_reaper_task.cancel()
                shutdown_process_pool()
                logger.info("Cancelled background tasks and shut down process pool on shutdown")

    # Create a new FastAPI app to act as the parent and mount FastMCP at root
    # CRITICAL: Pass the extended lifespan to include background cleanup tasks
    app = FastAPI(lifespan=extended_lifespan)
    
    # Add a simple health check endpoint before mounting FastMCP
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Provides a simple health check endpoint for monitoring."""
        return {"status": "ok"}

    # Create a directory for public static files if it doesn't exist
    public_dir = "/app/public"
    os.makedirs(public_dir, exist_ok=True)

    # Mount the static files directory BEFORE mounting FastMCP at root
    app.mount("/static", StaticFiles(directory=public_dir), name="static")
    logger.info(f"Serving static files from '{public_dir}' at the /static endpoint.")

    # Mount FastMCP app at root so it can handle MCP protocol correctly
    # FastMCP expects to be at the root path to handle protocol requests
    app.mount("/", fast_mcp_app)

    app.middleware("http")(sandbox_log_request_middleware)
    return app

def create_sandbox_app():
    """App factory for multi-worker mode.

    Called once per forked worker process by uvicorn.run(factory=True).
    Returns the ASGI application with lifespan-managed background tasks.
    """
    return setup_sandbox_mcp_server()


async def sandbox_main_async():
    """Asynchronous main function for single-worker mode."""
    app = setup_sandbox_mcp_server()

    server_host = os.getenv("SANDBOX_MCP_SERVER_HOST", "0.0.0.0")
    server_port = int(os.getenv("SANDBOX_MCP_SERVER_PORT", "8082"))

    config = uvicorn.Config(
        app,
        host=server_host,
        port=server_port,
        log_level=os.getenv("LOGGING_LEVEL", os.getenv("LOG_LEVEL", "info")).lower(),
    )
    server = uvicorn.Server(config)
    logger.info(f"Starting Sandbox MCP Server on {server_host}:{server_port} (single worker)...")
    await server.serve()


def start_sandbox_server_cli():
    """CLI entry point to start the Sandbox server.

    When SANDBOX_UVICORN_WORKERS > 1, uses uvicorn.run() with factory=True to fork
    multiple OS-level worker processes.
    """
    num_workers = int(os.getenv("SANDBOX_UVICORN_WORKERS", "1"))
    server_host = os.getenv("SANDBOX_MCP_SERVER_HOST", "0.0.0.0")
    server_port = int(os.getenv("SANDBOX_MCP_SERVER_PORT", "8082"))
    log_level = os.getenv("LOGGING_LEVEL", os.getenv("LOG_LEVEL", "info")).lower()

    try:
        if num_workers > 1:
            logger.info(
                f"Starting Sandbox MCP Server on {server_host}:{server_port} "
                f"with {num_workers} workers (multi-process mode)..."
            )
            uvicorn.run(
                "agentic_framework_pkg.sandbox_mcp_server.main:create_sandbox_app",
                factory=True,
                host=server_host,
                port=server_port,
                log_level=log_level,
                workers=num_workers,
            )
        else:
            asyncio.run(sandbox_main_async())
    except KeyboardInterrupt:
        logger.info("Sandbox MCP Server shutting down...")
    except Exception as e:
        logger.critical(f"Sandbox MCP Server failed to start or crashed: {e}", exc_info=True)

if __name__ == "__main__":
    start_sandbox_server_cli()