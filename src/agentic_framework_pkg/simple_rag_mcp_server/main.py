"""
Main entry point for the Simple RAG MCP server.

This module initializes the FastAPI application for the simple RAG server,
registers its specialized RAG tools, and starts the Uvicorn server.

Architectural Role:
-   **Tier 3 (Executor):** This service acts as a specialized, stateless executor
    for a self-contained, in-memory RAG workflow.
-   **Tutorial Component:** It is primarily designed as a tutorial component to
    demonstrate the modularity of the framework and how new tool servers can be
    easily created and integrated.
-   **In-Memory State:** Unlike other services, it uses an in-memory vector store
    (FAISS) and an in-memory SQLite database, meaning its state is ephemeral and
    resets on restart.
"""
# src/agentic_framework_pkg/simple_rag_mcp_server/main.py
import uvicorn
import asyncio
import os
from dotenv import load_dotenv

from .server import simple_rag_mcp
from .tools import simple_rag_tool
from ..logger_config import get_logger

logger = get_logger(__name__)

def setup_simple_rag_mcp_server(mcp_instance=simple_rag_mcp):
    """
    Sets up the Simple RAG MCP server instance by registering its tools.
    """
    logger.info("Setting up Simple RAG MCP server and registering tools...")
    simple_rag_tool.register_tools(mcp_instance)
    logger.info("Simple RAG MCP tools registered.")
    # Session 62: stateless_http=True eliminates per-process session dicts, enables multi-worker
    return mcp_instance.http_app(stateless_http=True)

async def main_async():
    """Asynchronous main function to set up and start the Simple RAG server."""
    app = setup_simple_rag_mcp_server()
    server_host = os.getenv("SIMPLE_RAG_MCP_SERVER_HOST", "0.0.0.0")
    server_port = int(os.getenv("SIMPLE_RAG_MCP_SERVER_PORT", "8085"))
    
    config = uvicorn.Config(app, host=server_host, port=server_port, log_level=os.getenv("LOG_LEVEL", "info").lower())
    server = uvicorn.Server(config)
    logger.info(f"Starting Simple RAG MCP Server on {server_host}:{server_port}...")
    await server.serve()

def start_server_cli():
    """CLI entry point to start the Simple RAG server."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Simple RAG MCP Server shutting down...")
    except Exception as e:
        logger.critical(f"Simple RAG MCP Server failed to start or crashed: {e}", exc_info=True)

if __name__ == "__main__":
    start_server_cli()
