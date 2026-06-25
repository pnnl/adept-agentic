"""
Academy MCP Server - Main Application

FastAPI application serving Academy federated agent lifecycle tools via MCP protocol.

Mount strategy:
  FastMCP's http_app() internally creates a /mcp route (Streamable HTTP).
  We mount it at root "/" so the MCP endpoint lives at /mcp (not /mcp/mcp).
  FastAPI checks its own routes (/health, /) before falling through to the mount.

Lifespan propagation:
  FastMCP 2.14+ requires StreamableHTTPSessionManager to be initialized via
  its ASGI lifespan. We pass mcp_http_app.router.lifespan_context to the
  FastAPI app so the task group is started before any MCP requests arrive.
"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure logging for observability
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Support both standalone (Docker) and subpackage (examples.academy_mcp_server) imports
try:
    from .server import mcp
    from .config import settings
except ImportError:
    from server import mcp
    from config import settings

logging.getLogger("academy_mcp_server").setLevel(
    getattr(logging, settings.log_level.upper(), logging.INFO)
)

# Get the MCP ASGI app — FastMCP internally creates a /mcp route
mcp_http_app = mcp.http_app(stateless_http=True)

# Extract lifespan from the MCP app so StreamableHTTPSessionManager is initialized.
# FastMCP stores it on the Starlette app's router.
mcp_lifespan = getattr(mcp_http_app.router, "lifespan_context", None) or getattr(
    mcp_http_app, "lifespan", None
)

# Create FastAPI app with MCP lifespan (required by FastMCP 2.14.5+)
app = FastAPI(
    title="Academy MCP Server",
    description="MCP server for Academy federated agent lifecycle management",
    version="1.0.0",
    lifespan=mcp_lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Academy MCP Server",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "mcp_tools": [
            "launch_academy_agent",
            "invoke_agent_action",
            "list_academy_agents",
            "shutdown_academy_agent",
        ],
    }


# Mount FastMCP at root — its internal /mcp route becomes accessible at /mcp
# FastAPI checks its own routes (/health, /) first before falling through.
app.mount("/", mcp_http_app)


if __name__ == "__main__":
    import uvicorn

    print(f"Starting Academy MCP Server on port {settings.port}")
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
