"""
Opentrons MCP Server - Main Application

FastAPI application serving Opentrons liquid handling tools via MCP protocol.

Mount strategy:
  FastMCP's http_app() internally creates a /mcp route (Streamable HTTP).
  We mount it at root "/" so the MCP endpoint lives at /mcp (not /mcp/mcp).
  FastAPI checks its own routes (/health, /) before falling through to the mount.

Lifespan propagation:
  FastMCP 2.14+ requires StreamableHTTPSessionManager to be initialized via
  its ASGI lifespan. We pass mcp_http_app.router.lifespan_context to the
  FastAPI app so the task group is started before any MCP requests arrive.
"""

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure logging for observability
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("opentrons_mcp_server").setLevel(logging.INFO)

# Support both standalone (Docker) and subpackage (examples.opentrons_mcp_server) imports
try:
    from .server import mcp
except ImportError:
    from server import mcp

# Environment configuration
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "9003"))
HARDWARE_MODE = os.getenv("OPENTRONS_HARDWARE_MODE", "simulation")

# Get the MCP ASGI app — FastMCP internally creates a /mcp route
mcp_http_app = mcp.http_app(stateless_http=True)

# Extract lifespan from the MCP app so StreamableHTTPSessionManager is initialized.
# FastMCP stores it on the Starlette app's router.
mcp_lifespan = getattr(mcp_http_app.router, "lifespan_context", None) or getattr(
    mcp_http_app, "lifespan", None
)

# Create FastAPI app with MCP lifespan (required by FastMCP 2.14.5+)
app = FastAPI(
    title="Opentrons MCP Server",
    description="MCP server for Opentrons liquid handling protocol execution",
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
        "name": "Opentrons MCP Server",
        "version": "1.0.0",
        "hardware_mode": HARDWARE_MODE,
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "hardware_mode": HARDWARE_MODE,
        "mcp_tools": ["execute_opentrons_protocol"],
    }


# Mount FastMCP at root — its internal /mcp route becomes accessible at /mcp
# FastAPI checks its own routes (/health, /) first before falling through.
app.mount("/", mcp_http_app)


if __name__ == "__main__":
    import uvicorn

    print(f"Starting Opentrons MCP Server on port {MCP_SERVER_PORT}")
    print(f"Hardware mode: {HARDWARE_MODE}")
    uvicorn.run(app, host="0.0.0.0", port=MCP_SERVER_PORT)
