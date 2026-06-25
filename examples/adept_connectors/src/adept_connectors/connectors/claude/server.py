"""FastMCP server for ADEPT Claude Connector.

Exposes ADEPT capabilities as MCP tools, resources, and prompts.
Runs as STDIO transport for Claude Desktop or HTTP for Claude Pro.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from fastmcp import FastMCP

from ...core.auth import AuthManager
from ...core.clients.base import BaseAdeptClient
from ...core.config import AdeptConnectorConfig
from ...core.session import SessionManager

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Shared application state available to all tools."""

    config: AdeptConnectorConfig
    auth: AuthManager
    session_mgr: SessionManager
    client: BaseAdeptClient


# Global context set during lifespan
_ctx: AppContext | None = None


def get_context() -> AppContext:
    """Get the current application context. Raises if server not started."""
    if _ctx is None:
        raise RuntimeError("Server not initialized — call via FastMCP lifespan")
    return _ctx


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize and tear down shared resources."""
    global _ctx

    config = AdeptConnectorConfig()
    auth = AuthManager(config)
    session_mgr = SessionManager(persist=config.session_persistence)
    client = BaseAdeptClient(config, auth, client_source="claude-connector")

    await client._ensure_client()
    logger.info(
        "ADEPT connector started — %s auth, target: %s",
        config.auth_method.value,
        config.base_url,
    )

    _ctx = AppContext(
        config=config,
        auth=auth,
        session_mgr=session_mgr,
        client=client,
    )

    try:
        yield
    finally:
        await client.close()
        _ctx = None
        logger.info("ADEPT connector stopped")


mcp = FastMCP(
    "ADEPT Connector",
    version="0.1.0",
    lifespan=lifespan,
)


# --- Phase 3: Register tools and resources via module imports ---
# Each module uses @mcp.tool() / @mcp.resource() decorators on import.
from .tools import chat, files, sessions, discovery  # noqa: F401, E402
from .resources import adept_resources  # noqa: F401, E402


def create_server() -> FastMCP:
    """Return the configured FastMCP server instance."""
    return mcp
