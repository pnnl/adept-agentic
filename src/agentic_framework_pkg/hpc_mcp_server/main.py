"""
Main entry point for the HPC (High-Performance Computing) MCP server.

This module is responsible for initializing the FastAPI application for the HPC
server, setting up middleware, and registering all the specialized HPC tool
modules that this server will expose.

Architectural Role (in Three-Tier Model):
-   **Tier 3 (Executor):** This service acts as a specialized, stateless executor
    for computationally intensive or long-running tasks, such as bioinformatics
    pipelines (Nextflow) or video processing.
-   **HPC Tool Provider:** It exposes tools that often involve running external
    processes (like Nextflow or GitXRay) over the Multi-Component Protocol (MCP).
"""
import uvicorn
import asyncio
import os
from dotenv import load_dotenv
from fastapi import Request, FastAPI # For middleware, if needed
import json

# Load environment variables from .env file for local development
if os.path.exists(".env"): # Check relative to this file
    load_dotenv()
elif os.path.exists("../../.env"): # Check from root if running as module
    load_dotenv(dotenv_path=os.path.join(os.getcwd(), "../../.env"))


from .server import hpc_mcp # Import the HPC MCP instance
from .tools import nextflow_blast_tool, video_processing_tool, gitxray_tool # Import HPC tools
# from ..state_manager import initialize_db # If HPC server needs its own state
from ..core.llm_agnostic_layer import LLMAgnosticClient # For passing to tools that need LLM
from ..logger_config import get_logger # Assuming reuse of central logger

logger = get_logger(__name__)

# Initialize the LLM client for the HPC server
llm_agnostic_client_hpc_instance = LLMAgnosticClient()

# Middleware for logging (optional, can be adapted from the main MCP server)
async def hpc_log_request_middleware(request: Request, call_next):
    """Log incoming requests to the HPC server."""
    req_body_bytes = await request.body()
    # Enhanced debug logging
    logger.info(f"🏔️ HPC SERVER DEBUG: {request.method} {request.url} from {request.client.host}")
    if req_body_bytes:
        try:
            body_json = json.loads(req_body_bytes.decode())
            logger.info(f"📥 HPC SERVER DEBUG: Request body (JSON): {body_json}")
            
            # Check for session IDs in the request
            if isinstance(body_json, dict):
                session_fields = ['session_id', 'mcp_session_id', 'multi_agent_session_id', 'gateway_session_id']
                sessions = {field: body_json.get(field) for field in session_fields if field in body_json}
                if sessions:
                    logger.info(f"🔗 HPC SERVER DEBUG: Session context found: {sessions}")
                    
        except Exception:
            logger.info(f"📥 HPC SERVER DEBUG: Request body (raw): {req_body_bytes[:200].decode(errors='ignore')}...")

    async def new_receive():
        return {"type": "http.request", "body": req_body_bytes, "more_body": False}
    new_request = Request(request.scope, receive=new_receive)
    response = await call_next(new_request)
    logger.info(f"📤 HPC SERVER DEBUG: Response {response.status_code}")
    return response

def setup_hpc_mcp_server(mcp_instance = hpc_mcp) -> FastAPI:
    """
    Sets up the HPC MCP server instance by registering all its tool modules.
    """
    logger.info("Setting up HPC MCP server and registering tools...")
    
    # Register tools with the HPC MCP instance
    nextflow_blast_tool.register_tools(mcp_instance)
    video_processing_tool.register_tools(mcp_instance, llm_agnostic_client_hpc_instance) # Pass LLM client
    gitxray_tool.register_tools(mcp_instance)
    
    # Register other HPC tool modules here
    logger.info("HPC MCP tools registered.")

    # Get the FastMCP app, which is a Starlette app that expects to be at root
    # Session 62: stateless_http=True eliminates per-process session dicts, enables multi-worker
    fast_mcp_app = mcp_instance.http_app(stateless_http=True)
    
    # Create a new FastAPI app to act as the parent and mount FastMCP at root
    # CRITICAL: Pass the FastMCP app's lifespan to fix task group initialization
    app = FastAPI(lifespan=fast_mcp_app.lifespan)
    
    # Add a simple health check endpoint before mounting FastMCP
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Provides a simple health check endpoint for monitoring."""
        return {"status": "ok"}

    # Mount FastMCP app at root so it can handle MCP protocol correctly
    # FastMCP expects to be at the root path to handle protocol requests
    app.mount("/", fast_mcp_app)

    # Add the middleware to the parent app
    app.middleware("http")(hpc_log_request_middleware) # Optional logging
    return app

def create_hpc_app():
    """App factory for multi-worker mode.

    Called once per forked worker process by uvicorn.run(factory=True).
    Returns the ASGI application.
    """
    return setup_hpc_mcp_server()


async def hpc_main_async():
    """Asynchronous main function for single-worker mode."""
    app = setup_hpc_mcp_server()

    server_host = os.getenv("HPC_MCP_SERVER_HOST", "0.0.0.0")
    server_port = int(os.getenv("HPC_MCP_SERVER_PORT", "8081"))

    config = uvicorn.Config(
        app,
        host=server_host,
        port=server_port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
    server = uvicorn.Server(config)
    logger.info(f"Starting HPC MCP Server on {server_host}:{server_port} (single worker)...")
    await server.serve()


def start_hpc_server_cli():
    """CLI entry point to start the HPC server.

    When HPC_UVICORN_WORKERS > 1, uses uvicorn.run() with factory=True to fork
    multiple OS-level worker processes.
    """
    num_workers = int(os.getenv("HPC_UVICORN_WORKERS", "1"))
    server_host = os.getenv("HPC_MCP_SERVER_HOST", "0.0.0.0")
    server_port = int(os.getenv("HPC_MCP_SERVER_PORT", "8081"))
    log_level = os.getenv("LOG_LEVEL", "info").lower()

    try:
        if num_workers > 1:
            logger.info(
                f"Starting HPC MCP Server on {server_host}:{server_port} "
                f"with {num_workers} workers (multi-process mode)..."
            )
            uvicorn.run(
                "agentic_framework_pkg.hpc_mcp_server.main:create_hpc_app",
                factory=True,
                host=server_host,
                port=server_port,
                log_level=log_level,
                workers=num_workers,
            )
        else:
            asyncio.run(hpc_main_async())
    except KeyboardInterrupt:
        logger.info("HPC MCP Server shutting down...")
    except Exception as e:
        logger.critical(f"HPC MCP Server failed to start or crashed: {e}", exc_info=True)

if __name__ == "__main__":
    start_hpc_server_cli()
