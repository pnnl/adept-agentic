"""Tool routes — GET /v1/tools, POST /v1/tools/{name}.

ADEPT MCP tool discovery and invocation via REST.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)


class ToolInfo(BaseModel):
    """Tool metadata from MCP tools/list."""

    name: str
    description: str = ""
    input_schema: Optional[dict[str, Any]] = Field(
        default=None, alias="inputSchema"
    )

    model_config = {"populate_by_name": True}


class ToolCallRequest(BaseModel):
    """Request body for POST /v1/tools/{name}."""

    arguments: Optional[dict[str, Any]] = Field(
        default=None, description="Tool arguments as a JSON object"
    )
    session_id: Optional[str] = Field(
        default=None, description="Session ID for stateful tools"
    )


class ToolCallResponse(BaseModel):
    """Response from a tool call."""

    tool_name: str
    result: str = ""
    success: bool = True
    error: Optional[str] = None


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools(request: Request) -> list[ToolInfo]:
    """Discover all scientific tools available on the ADEPT server.

    Use this to see what capabilities ADEPT provides: websearch, BLAST,
    UniProt, PubChem, code execution, file processing, RAG, and more.
    """
    facade = request.app.state.facade
    raw_tools = await facade.mcp.list_tools()
    return [
        ToolInfo(
            name=t.get("name", ""),
            description=t.get("description", ""),
            inputSchema=t.get("inputSchema"),
        )
        for t in raw_tools
    ]


@router.post("/tools/{tool_name}", response_model=ToolCallResponse)
async def call_tool(
    request: Request,
    tool_name: str,
    body: ToolCallRequest,
) -> ToolCallResponse:
    """Call a specific tool on the ADEPT MCP server.

    Pass the tool name from GET /v1/tools and arguments matching
    that tool's inputSchema.
    """
    facade = request.app.state.facade

    args = body.arguments
    if body.session_id:
        args = args or {}
        args["session_id"] = body.session_id

    try:
        result = await facade.mcp.call_tool(tool_name, args)
        return ToolCallResponse(
            tool_name=tool_name,
            result=result,
            success=True,
        )
    except Exception as e:
        logger.error("Tool call failed: %s(%s) — %s", tool_name, args, e)
        return ToolCallResponse(
            tool_name=tool_name,
            result="",
            success=False,
            error=str(e),
        )
