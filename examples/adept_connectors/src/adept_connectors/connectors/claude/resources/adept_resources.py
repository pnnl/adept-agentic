"""MCP resources — adept://models, adept://sessions, adept://files/{file_id}."""

from __future__ import annotations

import json

from ..server import get_context, mcp


@mcp.resource("adept://models")
async def get_models() -> str:
    """Available models on the ADEPT instance."""
    ctx = get_context()
    resp = await ctx.client.get("/responses/models")
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.resource("adept://sessions")
async def get_sessions() -> str:
    """Active ADEPT sessions tracked by this connector."""
    ctx = get_context()
    sessions = ctx.session_mgr.list_sessions()
    return json.dumps(sessions, indent=2)


@mcp.resource("adept://files/{file_id}")
async def get_file_metadata(file_id: str) -> str:
    """Metadata for a specific file stored in ADEPT."""
    ctx = get_context()
    resp = await ctx.client.get(f"/files/{file_id}")
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)
