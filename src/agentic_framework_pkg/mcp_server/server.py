"""
This module initializes the FastMCP server instance for the default MCP server.

It creates a global `mcp` object that is imported by other modules in this
package to register their tools.
"""
import os
from fastmcp import FastMCP

# Initialize FastMCP instance
mcp = FastMCP(
    name=os.getenv("MCP_SERVER_NAME", "AgenticFrameworkMCP"),
    instructions="This MCP server provides tools for data analysis, general utilities, and scientific workflows.",
    # NOTE: stateless_http=True is passed to http_app() in main.py, not here.
    # FastMCP >=2.14 deprecated constructor kwargs; they must go in http_app().
)

# MCP tool, resource, and prompt definitions will be registered on this 'mcp' instance.
# Example (to be expanded in respective tool files and imported here):
# from.tools.general_tools import register_general_tools
# register_general_tools(mcp)