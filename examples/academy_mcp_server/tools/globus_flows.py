"""
Globus Flows Tools

MCP tool implementations for Globus Flows API operations:
workflow listing, execution, monitoring, and cancellation.
"""

import logging
from typing import Any, Dict, Optional

from fastmcp import Context, FastMCP

try:
    from ..clients.globus_client import globus_manager
except ImportError:
    from clients.globus_client import globus_manager

logger = logging.getLogger("academy_mcp_server")


# ---------------------------------------------------------------------------
# Core implementations
# ---------------------------------------------------------------------------


async def globus_list_flows(
    filter_role: str = "flow_owner",
    limit: int = 10,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_flows_client()
        result = client.list_flows(filter_role=filter_role, marker=None, per_page=limit)
        flows = [
            {
                "id": f.get("id"),
                "title": f.get("title"),
                "description": f.get("description"),
                "owner": f.get("flow_owner"),
            }
            for f in result.get("flows", [])
        ]
        return {"status": "success", "flows": flows, "count": len(flows)}
    except Exception as e:
        logger.error("[GLOBUS] list_flows error: %s", e)
        return {"status": "error", "error": str(e)}


async def globus_run_flow(
    flow_id: str,
    flow_input: Dict[str, Any],
    label: str = "",
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_flows_client()
        body = {"body": flow_input}
        if label:
            body["label"] = label
        result = client.run_flow(flow_id, body=body)
        return {
            "status": "success",
            "run_id": result.get("run_id") or result.get("action_id"),
            "flow_id": flow_id,
            "label": label,
        }
    except Exception as e:
        logger.error("[GLOBUS] run_flow error: %s", e)
        return {"status": "error", "error": str(e), "flow_id": flow_id}


async def globus_get_flow_run(
    run_id: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_flows_client()
        result = client.get_run(run_id)
        return {
            "status": "success",
            "run_id": run_id,
            "run_status": result.get("status"),
            "label": result.get("label"),
            "start_time": result.get("start_time"),
            "completion_time": result.get("completion_time"),
            "details": result.get("details"),
        }
    except Exception as e:
        logger.error("[GLOBUS] get_flow_run error: %s", e)
        return {"status": "error", "error": str(e), "run_id": run_id}


async def globus_cancel_flow_run(
    run_id: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_flows_client()
        client.cancel_run(run_id)
        return {"status": "success", "run_id": run_id, "message": "Flow run cancelled"}
    except Exception as e:
        logger.error("[GLOBUS] cancel_flow_run error: %s", e)
        return {"status": "error", "error": str(e), "run_id": run_id}


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register all Globus Flows tools with the given FastMCP instance."""

    @mcp.tool()
    async def globus_list_flows_tool(
        filter_role: str = "flow_owner",
        limit: int = 10,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """List available Globus Flows (workflow definitions).

        Args:
            filter_role: Role filter: "flow_owner", "flow_viewer", etc.
            limit: Maximum number of flows to return (default: 10).
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with flows list (id, title, description, owner).
        """
        logger.info("[GLOBUS] list_flows | role=%s", filter_role)
        return await globus_list_flows(filter_role, limit, mcp_session_id)

    @mcp.tool()
    async def globus_run_flow_tool(
        flow_id: str,
        flow_input: dict,
        label: str = "",
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Start a Globus Flow run with input parameters.

        Args:
            flow_id: UUID of the Globus Flow to run.
            flow_input: Input parameters dict for the flow.
            label: Human-readable label for this run.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with run_id for tracking the flow execution.
        """
        logger.info("[GLOBUS] run_flow | flow=%s label=%s", flow_id, label)
        return await globus_run_flow(flow_id, flow_input, label, mcp_session_id)

    @mcp.tool()
    async def globus_get_flow_run_tool(
        run_id: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Get status and details of a Globus Flow run.

        Args:
            run_id: Run ID from run_flow.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with run_status, start/completion times, and details.
        """
        logger.info("[GLOBUS] get_flow_run | run_id=%s", run_id)
        return await globus_get_flow_run(run_id, mcp_session_id)

    @mcp.tool()
    async def globus_cancel_flow_run_tool(
        run_id: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Cancel an in-progress Globus Flow run.

        Args:
            run_id: Run ID to cancel.
            mcp_session_id: Session ID for resource isolation.
        """
        logger.info("[GLOBUS] cancel_flow_run | run_id=%s", run_id)
        return await globus_cancel_flow_run(run_id, mcp_session_id)

    logger.info("Registered 4 Globus Flows tools")
