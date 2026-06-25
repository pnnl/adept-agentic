"""
Globus Compute Tools

MCP tool implementations for Globus Compute API operations:
remote function submission, task status, endpoint management,
and function registration.
"""

import logging
from typing import Any, Dict, List, Optional

from fastmcp import Context, FastMCP

try:
    from ..clients.globus_client import globus_manager
except ImportError:
    from clients.globus_client import globus_manager

logger = logging.getLogger("academy_mcp_server")


# ---------------------------------------------------------------------------
# Core implementations
# ---------------------------------------------------------------------------


async def globus_compute_submit(
    endpoint_id: str,
    function_id: str,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        from globus_compute_sdk import Client as ComputeClient, Executor

        gcc = ComputeClient()
        task_id = gcc.run(
            *args or [],
            **kwargs or {},
            endpoint_id=endpoint_id,
            function_id=function_id,
        )
        return {"status": "success", "task_id": task_id, "endpoint_id": endpoint_id, "function_id": function_id}
    except ImportError:
        return {"status": "error", "error": "globus-compute-sdk not installed. Install with: pip install globus-compute-sdk"}
    except Exception as e:
        logger.error("[GLOBUS] compute_submit error: %s", e)
        return {"status": "error", "error": str(e)}


async def globus_compute_get_task(
    task_id: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        from globus_compute_sdk import Client as ComputeClient

        gcc = ComputeClient()
        result = gcc.get_result(task_id)
        return {"status": "success", "task_id": task_id, "result": result}
    except ImportError:
        return {"status": "error", "error": "globus-compute-sdk not installed"}
    except Exception as e:
        if "pending" in str(e).lower():
            return {"status": "success", "task_id": task_id, "task_status": "PENDING", "result": None}
        logger.error("[GLOBUS] compute_get_task error: %s", e)
        return {"status": "error", "error": str(e), "task_id": task_id}


async def globus_compute_get_endpoint(
    endpoint_id: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        from globus_compute_sdk import Client as ComputeClient

        gcc = ComputeClient()
        result = gcc.get_endpoint_status(endpoint_id)
        return {
            "status": "success",
            "endpoint_id": endpoint_id,
            "endpoint_status": result.get("status"),
            "details": result,
        }
    except ImportError:
        return {"status": "error", "error": "globus-compute-sdk not installed"}
    except Exception as e:
        logger.error("[GLOBUS] compute_get_endpoint error: %s", e)
        return {"status": "error", "error": str(e), "endpoint_id": endpoint_id}


async def globus_compute_list_endpoints(
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        from globus_compute_sdk import Client as ComputeClient

        gcc = ComputeClient()
        result = gcc.get_endpoints()
        endpoints = [
            {
                "id": ep.get("uuid"),
                "name": ep.get("name"),
                "status": ep.get("status"),
            }
            for ep in result
        ] if isinstance(result, list) else []
        return {"status": "success", "endpoints": endpoints, "count": len(endpoints)}
    except ImportError:
        return {"status": "error", "error": "globus-compute-sdk not installed"}
    except Exception as e:
        logger.error("[GLOBUS] compute_list_endpoints error: %s", e)
        return {"status": "error", "error": str(e)}


async def globus_compute_register_function(
    function_code: str,
    function_name: str = "",
    description: str = "",
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        from globus_compute_sdk import Client as ComputeClient

        gcc = ComputeClient()
        # Create function from code string
        local_ns: Dict[str, Any] = {}
        exec(function_code, local_ns)  # noqa: S102 — user-provided code
        func = None
        for val in local_ns.values():
            if callable(val):
                func = val
                break
        if func is None:
            return {"status": "error", "error": "No callable function found in provided code"}
        function_id = gcc.register_function(func, function_name=function_name or func.__name__, description=description)
        return {"status": "success", "function_id": function_id, "function_name": function_name or func.__name__}
    except ImportError:
        return {"status": "error", "error": "globus-compute-sdk not installed"}
    except Exception as e:
        logger.error("[GLOBUS] compute_register_function error: %s", e)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register all Globus Compute tools with the given FastMCP instance."""

    @mcp.tool()
    async def globus_compute_submit_tool(
        endpoint_id: str,
        function_id: str,
        args: Optional[list] = None,
        kwargs: Optional[dict] = None,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Submit a function execution to a Globus Compute endpoint.

        Args:
            endpoint_id: UUID of the Globus Compute endpoint.
            function_id: UUID of a previously registered function.
            args: Positional arguments for the function.
            kwargs: Keyword arguments for the function.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with task_id for tracking the execution.
        """
        logger.info("[GLOBUS] compute_submit | endpoint=%s function=%s", endpoint_id, function_id)
        return await globus_compute_submit(endpoint_id, function_id, args, kwargs, mcp_session_id)

    @mcp.tool()
    async def globus_compute_get_task_tool(
        task_id: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Get the result or status of a Globus Compute task.

        Args:
            task_id: Task ID from compute_submit.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with result (if complete) or task_status (if pending).
        """
        logger.info("[GLOBUS] compute_get_task | task_id=%s", task_id)
        return await globus_compute_get_task(task_id, mcp_session_id)

    @mcp.tool()
    async def globus_compute_get_endpoint_tool(
        endpoint_id: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Get details and status of a Globus Compute endpoint.

        Args:
            endpoint_id: UUID of the Globus Compute endpoint.
            mcp_session_id: Session ID for resource isolation.
        """
        logger.info("[GLOBUS] compute_get_endpoint | endpoint=%s", endpoint_id)
        return await globus_compute_get_endpoint(endpoint_id, mcp_session_id)

    @mcp.tool()
    async def globus_compute_list_endpoints_tool(
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """List Globus Compute endpoints accessible to the current user.

        Args:
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with endpoints list (id, name, status).
        """
        logger.info("[GLOBUS] compute_list_endpoints")
        return await globus_compute_list_endpoints(mcp_session_id)

    @mcp.tool()
    async def globus_compute_register_function_tool(
        function_code: str,
        function_name: str = "",
        description: str = "",
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Register a Python function for remote execution on Globus Compute.

        The function_code must define at least one callable function.
        Example: "def add(a, b):\\n    return a + b"

        Args:
            function_code: Python source code defining the function.
            function_name: Display name (defaults to function's __name__).
            description: Human-readable description.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with function_id for use with compute_submit.
        """
        logger.info("[GLOBUS] compute_register_function | name=%s", function_name)
        return await globus_compute_register_function(function_code, function_name, description, mcp_session_id)

    logger.info("Registered 5 Globus Compute tools")
