"""
{{DISPLAY_NAME}} MCP Server - Main Application

FastAPI application serving {{DESCRIPTION}} tools via MCP.

Mount strategy:
  FastMCP's http_app() creates a /mcp route (Streamable HTTP).
  We mount it at root "/" so the MCP endpoint lives at /mcp.
  FastAPI checks its own routes (/health, /) first.

Lifespan propagation:
  FastMCP 2.14+ requires StreamableHTTPSessionManager to be initialized via
  its ASGI lifespan. We pass mcp_http_app.router.lifespan_context to the
  FastAPI app so the task group is started before any MCP requests arrive.
"""

import logging

from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("{{NAME}}_mcp")

from {{NAME}}_mcp.server import mcp

# Get the MCP ASGI app
mcp_http_app = mcp.http_app(stateless_http=True)

# Extract lifespan from the MCP app so session manager starts properly
mcp_lifespan = getattr(mcp_http_app.router, "lifespan_context", None) or getattr(
    mcp_http_app, "lifespan", None
)

app = FastAPI(title="{{DISPLAY_NAME}} MCP Server", lifespan=mcp_lifespan)


@app.get("/")
async def root() -> dict:
    """Root endpoint with service info."""
    from {{NAME}}_mcp import __version__

    return {
        "name": "{{DISPLAY_NAME}} MCP Server",
        "version": __version__,
        "description": "{{DESCRIPTION}}",
        "status": "running",
    }


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    from {{NAME}}_mcp import __version__

    tool_names = [t.name for t in mcp._tool_manager._tools.values()]
    return {
        "status": "healthy",
        "service": "{{NAME}}_mcp",
        "version": __version__,
        "mcp_tools": tool_names,
    }


# Mount FastMCP at root — its internal /mcp route becomes accessible at /mcp
app.mount("/", mcp_http_app)
