"""FastMCP server instance and tool registration."""

from fastmcp import FastMCP

mcp = FastMCP("{{DISPLAY_NAME}} Server")


def register_tools() -> None:
    """Import and register all tool modules with the MCP server."""
    from {{NAME}}_mcp.tools import example_tool, get_job_status

    example_tool.register(mcp)
    get_job_status.register(mcp)


register_tools()
