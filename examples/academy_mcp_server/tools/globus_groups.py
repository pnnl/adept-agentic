"""
Globus Groups Tools

MCP tool implementations for Globus Groups API operations:
group listing and group detail retrieval.
"""

import logging
from typing import Optional

from fastmcp import Context, FastMCP

try:
    from ..clients.globus_client import globus_manager
except ImportError:
    from clients.globus_client import globus_manager

logger = logging.getLogger("academy_mcp_server")


# ---------------------------------------------------------------------------
# Core implementations
# ---------------------------------------------------------------------------


async def globus_list_groups(
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_groups_client()
        result = client.get_my_groups()
        groups = [
            {
                "id": g.get("id"),
                "name": g.get("name"),
                "description": g.get("description"),
                "group_type": g.get("group_type"),
            }
            for g in result
        ]
        return {"status": "success", "groups": groups, "count": len(groups)}
    except Exception as e:
        logger.error("[GLOBUS] list_groups error: %s", e)
        return {"status": "error", "error": str(e)}


async def globus_get_group(
    group_id: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_groups_client()
        result = client.get_group(group_id)
        return {
            "status": "success",
            "group_id": group_id,
            "name": result.get("name"),
            "description": result.get("description"),
            "group_type": result.get("group_type"),
            "enforce_session": result.get("enforce_session"),
            "members_count": len(result.get("members", [])),
        }
    except Exception as e:
        logger.error("[GLOBUS] get_group error: %s", e)
        return {"status": "error", "error": str(e), "group_id": group_id}


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register all Globus Groups tools with the given FastMCP instance."""

    @mcp.tool()
    async def globus_list_groups_tool(
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """List Globus groups the current user belongs to.

        Args:
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with groups list (id, name, description, group_type).
        """
        logger.info("[GLOBUS] list_groups")
        return await globus_list_groups(mcp_session_id)

    @mcp.tool()
    async def globus_get_group_tool(
        group_id: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Get details and membership info for a Globus group.

        Args:
            group_id: UUID of the Globus group.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with group name, description, type, and member count.
        """
        logger.info("[GLOBUS] get_group | group_id=%s", group_id)
        return await globus_get_group(group_id, mcp_session_id)

    logger.info("Registered 2 Globus Groups tools")
