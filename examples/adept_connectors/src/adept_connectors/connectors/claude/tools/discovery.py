"""Discovery tools — adept_list_tools, adept_call_tool, adept_list_models."""

from __future__ import annotations

import json
from typing import Any, Optional

from ..server import get_context, mcp


@mcp.tool()
async def adept_list_tools() -> str:
    """Discover all scientific tools available on the ADEPT server.

    Use this as one of the first steps when connecting to ADEPT to understand
    what capabilities are available. ADEPT provides tools for scientific
    workflows including websearch, BLAST sequence search, UniProt protein
    lookup, PubChem chemical queries, code execution, file processing,
    RAG (retrieval-augmented generation), and more.

    After discovering tools, use adept_call_tool to invoke any of them
    by name with the appropriate arguments.

    Example workflow:
    1. adept_list_tools() — see what's available
    2. adept_call_tool("websearch", '{"query": "CRISPR 2026"}') — call a tool

    Returns:
        JSON array of tool objects with name, description, and inputSchema.
    """
    ctx = get_context()
    from ....core.clients.mcp_proxy import MCPProxyClient

    proxy = MCPProxyClient(ctx.config, ctx.auth, instance_id=ctx.client.instance_id)
    tools = await proxy.list_tools()
    return json.dumps(tools, indent=2)


@mcp.tool()
async def adept_call_tool(
    tool_name: str,
    arguments: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Call a specific tool on the ADEPT MCP server by name.

    Use this to invoke any tool discovered via adept_list_tools. Pass the
    tool name exactly as returned by adept_list_tools, plus a JSON string
    of arguments matching that tool's inputSchema.

    Common tools you can call:
    - websearch: Web search for scientific literature and general queries
    - blast_search: NCBI BLAST sequence alignment
    - uniprot_search: UniProt protein database lookup
    - pubchem_search: PubChem chemical compound search
    - execute_code: Run Python code in a sandboxed environment
    - list_models: List available LLM models on the server

    Example:
        adept_call_tool("websearch", '{"query": "CRISPR gene editing 2026"}')

    Args:
        tool_name: Name of the tool to call (from adept_list_tools output).
        arguments: JSON string of tool arguments (e.g. '{"query": "..."}').
        session_id: Session ID for stateful tools that need context.

    Returns:
        Tool execution result as a string.
    """
    ctx = get_context()
    from ....core.clients.mcp_proxy import MCPProxyClient

    proxy = MCPProxyClient(ctx.config, ctx.auth, instance_id=ctx.client.instance_id)

    args: dict[str, Any] | None = None
    if arguments:
        args = json.loads(arguments)
    if session_id:
        args = args or {}
        args["session_id"] = session_id

    return await proxy.call_tool(tool_name, args)


@mcp.tool()
async def adept_list_models() -> str:
    """List available LLM models on the ADEPT instance.

    Use this to verify connectivity to ADEPT and to see which models are
    available for chat. The default model is typically
    'agentic-framework:scientific-agent-v1', but other models (Azure OpenAI,
    AWS Bedrock, etc.) may be configured by the administrator.

    This is a good first call to make after setup to confirm the connector
    is working correctly.

    Returns:
        JSON array of model objects with id, object, and owned_by fields.
    """
    ctx = get_context()
    resp = await ctx.client.get("/responses/models")
    resp.raise_for_status()
    data = resp.json()
    # Handle {"data": [...]} or direct list
    models = data.get("data", data) if isinstance(data, dict) else data
    return json.dumps(models, indent=2)
