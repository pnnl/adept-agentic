"""
Main entrypoint for the default MCP (Multi-Component Protocol) server.

This module is responsible for initializing the FastAPI application, setting up
necessary middleware (like request logging), and registering all the tool modules
that this server will expose.

Architectural Role (in Three-Tier Model):
-   **Tier 3 (Executor):** This service acts as a stateless executor for a wide
    range of general-purpose and scientific tools. It receives tool call
    requests from the `orchestration_service` and executes them.
-   **Tool Provider:** It exposes tools over the Multi-Component Protocol (MCP),
    allowing them to be called remotely.
-   **Statelessness:** This server is designed to be stateless. All state related
    to conversations or sessions is managed by the `orchestration_service`.
"""
import uvicorn
import asyncio
import os
from dotenv import load_dotenv
from fastapi import Request, FastAPI
import json # Ensure json is imported if not already for the refined middleware

# Load environment variables from.env file for local development
# In Docker, env vars are passed through docker-compose.yml
if os.path.exists(".env"):
    load_dotenv()

from .server import mcp
from .state_manager import initialize_db
from .tools import (general_tools, csv_rag_tool, uniprot_tool,
                    websearch_tool, blast_tool, blastq_tool, pubchem_tool,
                    alphafold_tool, file_processor_tool, rag_processing_tool,
                    sql_transformation_tool, file_management_tools,
                    batch_file_operations)
from ..core.llm_agnostic_layer import LLMAgnosticClient 
from ..logger_config import get_logger # Use centralized logger

# Configure logging
logger = get_logger(__name__) # Gets logger with default level from logger_config

# Define the middleware function (will be applied later)
async def log_request_middleware(request: Request, call_next):
    """Log incoming requests and their metadata."""

    logger.info(f"🌐 MCP SERVER DEBUG: {request.method} {request.url} from {request.client.host}")  # Debug enabled
    
    # Note: Uncomment the next line if you want to log headers, but be cautious with sensitive data.
    # This is useful for debugging anything related to headers for any of the MCP tool servers. 
    # I've used this to debug issues with Claude's expectations around headers and integration with local or remote 
    # MCP servers.
    
    #logger.debug(f"Request Headers: {dict(request.headers)}"). # Uncomment to log headers

    # Read the full request body once. This consumes the original stream but caches it.
    req_body_bytes = await request.body()

    if req_body_bytes:
        try:
            # Attempt to parse as JSON for logging
            body_json = json.loads(req_body_bytes.decode('utf-8'))
            logger.info(f"📥 MCP SERVER DEBUG: Request body (JSON): {body_json}")
            
            # Check for session IDs in the request
            if isinstance(body_json, dict):
                session_fields = ['session_id', 'mcp_session_id', 'multi_agent_session_id', 'gateway_session_id']
                sessions = {field: body_json.get(field) for field in session_fields if field in body_json}
                if sessions:
                    logger.info(f"🔗 MCP SERVER DEBUG: Session context found: {sessions}")
                    
        except json.JSONDecodeError:
            logger.info(f"📥 MCP SERVER DEBUG: Request body (raw, not JSON): {req_body_bytes[:500].decode(errors='ignore')}...")
        except UnicodeDecodeError: # Handle cases where body is not valid UTF-8
            logger.info(f"📥 MCP SERVER DEBUG: Request body (raw, non-UTF-8): {req_body_bytes[:500]}...") # Log raw bytes
    else:
        logger.info("Request body: Empty")

    # Create a new 'receive' awaitable that will replay the consumed body.
    # This allows the downstream application (FastMCP) to read the body
    # as if it hadn't been touched by the middleware.
    async def new_receive():
        return {"type": "http.request", "body": req_body_bytes, "more_body": False}

    # Create a new Request object using the original scope, the new 'receive' channel,
    # and preserving the original 'send' channel to maintain headers.
    new_request = Request(scope=request.scope, receive=new_receive, send=request._send)

    response = await call_next(new_request) # Pass the new_request to the next handler
    logger.info(f"Outgoing response: {response.status_code}")
    return response

# Initialize the LLM client (can be a singleton or passed via dependency injection)
# For simplicity, tools might access this global instance or have it passed during registration.
llm_agnostic_client_instance = LLMAgnosticClient()

def setup_mcp_server(mcp_instance: mcp = mcp, init_db_in_lifespan: bool = False) -> FastAPI:
    """
    Sets up the MCP server instance by registering all its tool modules.

    Args:
        mcp_instance: The FastMCP server instance.
        init_db_in_lifespan: If True, wrap the lifespan to call initialize_db()
            on startup. Used in multi-worker mode where DB init cannot happen
            in the factory (the factory runs inside an existing event loop).
    """
    from contextlib import asynccontextmanager

    logger.info("Setting up MCP server and registering tools...")
    general_tools.register_tools(mcp) # Pass mcp instance
    csv_rag_tool.register_tools(mcp, llm_agnostic_client_instance) # Pass mcp and llm client
    uniprot_tool.register_tools(mcp) # Register UniProt tool
    websearch_tool.register_tools(mcp) # Register WebSearch tool
    blast_tool.register_tools(mcp) # Register BLAST tool
    blastq_tool.register_tools(mcp) # Register the new Biopython-based BLAST tool
    pubchem_tool.register_tools(mcp) # Register PubChem tool
    alphafold_tool.register_tools(mcp, llm_agnostic_client_instance) # Register AlphaFold tool

    # Register new file processing tools
    file_management_tools.register_tools(mcp) # Register file management tools (list_uploaded_files, etc.)
    file_processor_tool.register_tools(mcp) # Register file processor tool
    rag_processing_tool.register_tools(mcp, llm_agnostic_client_instance) # Register RAG tools
    sql_transformation_tool.register_tools(mcp) # Register SQL transformation tool
    batch_file_operations.register_tools(mcp) # Register batch file operation tools

    # Note: Session introspection tools are now provided as utility tools in orchestration_service
    # (see src/agentic_framework_pkg/orchestration_service/utility_mcp_tools/session_introspection.py
    # and observability.py for QueryCheckpoints, QueryLangfuseTelemetry, etc.)

    # Register other tool modules here as they are created
    logger.info("MCP tools registered.")

    # Get the FastMCP app, which is a Starlette app that expects to be at root
    # Session 62: stateless_http=True eliminates per-process session dicts, enables multi-worker
    fast_mcp_app = mcp_instance.http_app(stateless_http=True)
    original_lifespan = fast_mcp_app.lifespan

    if init_db_in_lifespan:
        @asynccontextmanager
        async def lifespan_with_db_init(app):
            """Wraps FastMCP lifespan to include DB initialization on startup."""
            logger.info("Initializing database in worker process (lifespan)...")
            await initialize_db()
            async with original_lifespan(app) as state:
                yield state

        app = FastAPI(lifespan=lifespan_with_db_init)
    else:
        # CRITICAL: Pass the FastMCP app's lifespan to fix task group initialization
        app = FastAPI(lifespan=original_lifespan)

    # Add a simple health check endpoint before mounting FastMCP
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Provides a simple health check endpoint for monitoring."""
        return {"status": "ok"}

    # Mount FastMCP app at root so it can handle MCP protocol correctly
    # FastMCP expects to be at the root path to handle protocol requests
    app.mount("/", fast_mcp_app)

    # Add the middleware to the parent app so it covers all routes
    app.middleware("http")(log_request_middleware)
    logger.info("Request logging middleware added.")
    return app

def create_app():
    """App factory for multi-worker mode.

    Called once per forked worker process by uvicorn.run(factory=True).
    Returns the ASGI application. Database initialization happens during
    the app lifespan startup (inside the worker's event loop).
    """
    return setup_mcp_server(init_db_in_lifespan=True)


async def main_async():
    """Asynchronous main function for single-worker mode.

    Uses uvicorn.Server.serve() which runs within the current event loop.
    This path is used when UVICORN_WORKERS=1 (default).
    """
    logger.info("Initializing database...")
    await initialize_db()

    app = setup_mcp_server()

    server_host = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
    server_port = int(os.getenv("MCP_SERVER_PORT", "8080"))

    config = uvicorn.Config(
        app,
        host=server_host,
        port=server_port,
        log_level=os.getenv("LOG_LEVEL", "INFO").lower(),
    )
    server = uvicorn.Server(config)
    logger.info(f"Starting MCP Server on {server_host}:{server_port} (single worker)...")
    await server.serve()


def start_server_cli():
    """CLI entry point to start the server.

    When UVICORN_WORKERS > 1, uses uvicorn.run() with factory=True to fork
    multiple OS-level worker processes. uvicorn.Server.serve() does NOT fork
    workers — the 'workers' config param is silently ignored in that code path.
    """
    num_workers = int(os.getenv("UVICORN_WORKERS", "1"))
    server_host = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
    server_port = int(os.getenv("MCP_SERVER_PORT", "8080"))
    log_level = os.getenv("LOG_LEVEL", "INFO").lower()

    try:
        if num_workers > 1:
            logger.info(
                f"Starting MCP Server on {server_host}:{server_port} "
                f"with {num_workers} workers (multi-process mode)..."
            )
            uvicorn.run(
                "agentic_framework_pkg.mcp_server.main:create_app",
                factory=True,
                host=server_host,
                port=server_port,
                log_level=log_level,
                workers=num_workers,
            )
        else:
            asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("MCP Server shutting down...")
    except Exception as e:
        logger.critical(f"MCP Server failed to start or crashed: {e}", exc_info=True)

if __name__ == "__main__":
    # This allows running the server directly using `python -m agentic_framework_pkg.mcp_server.main`
    start_server_cli()