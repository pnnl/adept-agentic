"""
Academy MCP Server — Tool Registration

FastMCP server providing Academy federated agent lifecycle tools.
Tools are registered on import via the canonical register(mcp) pattern.
"""

import logging

from fastmcp import FastMCP

logger = logging.getLogger("academy_mcp_server")

mcp = FastMCP("Academy MCP Server")


def register_tools():
    """Register all Academy tools with FastMCP."""
    try:
        from .tools.agent_lifecycle import register as register_lifecycle
        from .tools.globus_transfer import register as register_transfer
        from .tools.globus_search import register as register_search
        from .tools.globus_compute import register as register_compute
        from .tools.globus_flows import register as register_flows
        from .tools.globus_groups import register as register_groups
    except ImportError:
        from tools.agent_lifecycle import register as register_lifecycle
        from tools.globus_transfer import register as register_transfer
        from tools.globus_search import register as register_search
        from tools.globus_compute import register as register_compute
        from tools.globus_flows import register as register_flows
        from tools.globus_groups import register as register_groups

    register_lifecycle(mcp)
    register_transfer(mcp)
    register_search(mcp)
    register_compute(mcp)
    register_flows(mcp)
    register_groups(mcp)


# Register tools on import
register_tools()
