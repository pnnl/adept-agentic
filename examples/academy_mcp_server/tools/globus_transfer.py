"""
Globus Transfer Tools

MCP tool implementations for Globus Transfer API operations:
file listing, directory management, async transfers, task management,
and endpoint discovery.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastmcp import Context, FastMCP

try:
    from ..clients.globus_client import globus_manager
except ImportError:
    from clients.globus_client import globus_manager

logger = logging.getLogger("academy_mcp_server")


def _extract_user_token(mcp_session_id: Optional[str] = None) -> Optional[str]:
    """Extract user Globus token from context if available."""
    # TODO: Wire user_context injection from orchestration service
    return None


# ---------------------------------------------------------------------------
# Core implementations
# ---------------------------------------------------------------------------


async def globus_list_directory(
    endpoint_id: str,
    path: str = "/",
    show_hidden: bool = False,
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        client = globus_manager.get_transfer_client(user_token=token)
        result = client.operation_ls(endpoint_id, path=path, show_hidden=show_hidden)
        entries = [
            {
                "name": e["name"],
                "type": e["type"],
                "size": e.get("size"),
                "last_modified": e.get("last_modified"),
            }
            for e in result
        ]
        return {"status": "success", "endpoint_id": endpoint_id, "path": path, "entries": entries, "count": len(entries)}
    except Exception as e:
        logger.error("[GLOBUS] list_directory error: %s", e)
        return {"status": "error", "error": str(e), "endpoint_id": endpoint_id, "path": path}


async def globus_mkdir(
    endpoint_id: str,
    path: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        client = globus_manager.get_transfer_client(user_token=token)
        client.operation_mkdir(endpoint_id, path=path)
        return {"status": "success", "endpoint_id": endpoint_id, "path": path}
    except Exception as e:
        logger.error("[GLOBUS] mkdir error: %s", e)
        return {"status": "error", "error": str(e), "endpoint_id": endpoint_id, "path": path}


async def globus_rename(
    endpoint_id: str,
    old_path: str,
    new_path: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        client = globus_manager.get_transfer_client(user_token=token)
        client.operation_rename(endpoint_id, oldpath=old_path, newpath=new_path)
        return {"status": "success", "endpoint_id": endpoint_id, "old_path": old_path, "new_path": new_path}
    except Exception as e:
        logger.error("[GLOBUS] rename error: %s", e)
        return {"status": "error", "error": str(e)}


async def globus_stat(
    endpoint_id: str,
    path: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        client = globus_manager.get_transfer_client(user_token=token)
        # operation_ls with a single file path returns metadata
        result = client.operation_ls(endpoint_id, path=path)
        entries = list(result)
        if entries:
            e = entries[0]
            return {
                "status": "success",
                "name": e["name"],
                "type": e["type"],
                "size": e.get("size"),
                "last_modified": e.get("last_modified"),
                "endpoint_id": endpoint_id,
                "path": path,
            }
        return {"status": "success", "endpoint_id": endpoint_id, "path": path, "entries": []}
    except Exception as e:
        logger.error("[GLOBUS] stat error: %s", e)
        return {"status": "error", "error": str(e)}


async def globus_submit_transfer(
    source_endpoint: str,
    destination_endpoint: str,
    transfer_items: List[Dict[str, Any]],
    label: str = "",
    sync_level: Optional[int] = None,
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        from globus_sdk import TransferData

        client = globus_manager.get_transfer_client(user_token=token)
        tdata = TransferData(
            source_endpoint=source_endpoint,
            destination_endpoint=destination_endpoint,
            label=label or f"ADEPT transfer (session {mcp_session_id or 'default'})",
            sync_level=sync_level,
        )
        for item in transfer_items:
            tdata.add_item(
                item["source_path"],
                item["destination_path"],
                recursive=item.get("recursive", False),
            )
        result = client.submit_transfer(tdata)
        return {
            "status": "success",
            "task_id": result["task_id"],
            "submission_id": result.get("submission_id"),
            "label": label,
        }
    except Exception as e:
        logger.error("[GLOBUS] submit_transfer error: %s", e)
        return {"status": "error", "error": str(e)}


async def globus_submit_delete(
    endpoint_id: str,
    paths: List[str],
    recursive: bool = True,
    label: str = "",
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        from globus_sdk import DeleteData

        client = globus_manager.get_transfer_client(user_token=token)
        ddata = DeleteData(
            endpoint=endpoint_id,
            recursive=recursive,
            label=label or f"ADEPT delete (session {mcp_session_id or 'default'})",
        )
        for p in paths:
            ddata.add_item(p)
        result = client.submit_delete(ddata)
        return {"status": "success", "task_id": result["task_id"]}
    except Exception as e:
        logger.error("[GLOBUS] submit_delete error: %s", e)
        return {"status": "error", "error": str(e)}


async def globus_get_task(
    task_id: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        client = globus_manager.get_transfer_client(user_token=token)
        result = client.get_task(task_id)
        return {
            "status": "success",
            "task_id": task_id,
            "task_status": result["status"],
            "type": result.get("type"),
            "label": result.get("label"),
            "bytes_transferred": result.get("bytes_transferred"),
            "files_transferred": result.get("files_transferred"),
            "nice_status": result.get("nice_status"),
        }
    except Exception as e:
        logger.error("[GLOBUS] get_task error: %s", e)
        return {"status": "error", "error": str(e), "task_id": task_id}


async def globus_list_tasks(
    filter_status: Optional[str] = None,
    limit: int = 10,
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        client = globus_manager.get_transfer_client(user_token=token)
        kwargs = {"num_results": limit}
        if filter_status:
            kwargs["filter_status"] = filter_status
        result = client.task_list(**kwargs)
        tasks = [
            {
                "task_id": t["task_id"],
                "status": t["status"],
                "type": t.get("type"),
                "label": t.get("label"),
                "request_time": t.get("request_time"),
            }
            for t in result
        ]
        return {"status": "success", "tasks": tasks, "count": len(tasks)}
    except Exception as e:
        logger.error("[GLOBUS] list_tasks error: %s", e)
        return {"status": "error", "error": str(e)}


async def globus_cancel_task(
    task_id: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        client = globus_manager.get_transfer_client(user_token=token)
        result = client.cancel_task(task_id)
        return {"status": "success", "task_id": task_id, "message": result.get("message", "Cancelled")}
    except Exception as e:
        logger.error("[GLOBUS] cancel_task error: %s", e)
        return {"status": "error", "error": str(e), "task_id": task_id}


async def globus_wait_for_task(
    task_id: str,
    timeout: int = 300,
    polling_interval: int = 5,
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        client = globus_manager.get_transfer_client(user_token=token)
        elapsed = 0
        while elapsed < timeout:
            result = client.get_task(task_id)
            status = result["status"]
            if status in ("SUCCEEDED", "FAILED"):
                return {
                    "status": "success",
                    "task_id": task_id,
                    "task_status": status,
                    "bytes_transferred": result.get("bytes_transferred"),
                    "files_transferred": result.get("files_transferred"),
                    "elapsed_seconds": elapsed,
                }
            await asyncio.sleep(polling_interval)
            elapsed += polling_interval
        return {"status": "error", "error": f"Timed out after {timeout}s", "task_id": task_id, "last_status": status}
    except Exception as e:
        logger.error("[GLOBUS] wait_for_task error: %s", e)
        return {"status": "error", "error": str(e), "task_id": task_id}


async def globus_search_endpoints(
    filter_fulltext: str,
    filter_scope: str = "all",
    limit: int = 10,
    mcp_session_id: Optional[str] = None,
) -> dict:
    token = _extract_user_token(mcp_session_id)
    try:
        client = globus_manager.get_transfer_client(user_token=token)
        result = client.endpoint_search(
            filter_fulltext=filter_fulltext,
            filter_scope=filter_scope,
            num_results=limit,
        )
        endpoints = [
            {
                "id": ep["id"],
                "display_name": ep.get("display_name"),
                "owner_string": ep.get("owner_string"),
                "entity_type": ep.get("entity_type"),
            }
            for ep in result
        ]
        return {"status": "success", "endpoints": endpoints, "count": len(endpoints), "query": filter_fulltext}
    except Exception as e:
        logger.error("[GLOBUS] search_endpoints error: %s", e)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register all Globus Transfer tools with the given FastMCP instance."""

    @mcp.tool()
    async def globus_list_directory_tool(
        endpoint_id: str,
        path: str = "/",
        show_hidden: bool = False,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """List files and directories at a path on a Globus collection/endpoint.

        Args:
            endpoint_id: UUID of the Globus collection or endpoint.
            path: Directory path to list (default: root "/").
            show_hidden: Include hidden files (starting with ".").
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with entries list (name, type, size, last_modified), count.
        """
        logger.info("[GLOBUS] list_directory | endpoint=%s path=%s", endpoint_id, path)
        return await globus_list_directory(endpoint_id, path, show_hidden, mcp_session_id)

    @mcp.tool()
    async def globus_mkdir_tool(
        endpoint_id: str,
        path: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Create a directory on a Globus collection/endpoint.

        Args:
            endpoint_id: UUID of the Globus collection.
            path: Full path of directory to create.
            mcp_session_id: Session ID for resource isolation.
        """
        logger.info("[GLOBUS] mkdir | endpoint=%s path=%s", endpoint_id, path)
        return await globus_mkdir(endpoint_id, path, mcp_session_id)

    @mcp.tool()
    async def globus_rename_tool(
        endpoint_id: str,
        old_path: str,
        new_path: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Rename a file or directory on a Globus collection/endpoint.

        Args:
            endpoint_id: UUID of the Globus collection.
            old_path: Current path of the file/directory.
            new_path: New path for the file/directory.
            mcp_session_id: Session ID for resource isolation.
        """
        logger.info("[GLOBUS] rename | endpoint=%s %s -> %s", endpoint_id, old_path, new_path)
        return await globus_rename(endpoint_id, old_path, new_path, mcp_session_id)

    @mcp.tool()
    async def globus_stat_tool(
        endpoint_id: str,
        path: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Get file/directory metadata (size, type, modified time) on a Globus collection.

        Args:
            endpoint_id: UUID of the Globus collection.
            path: Path to the file or directory.
            mcp_session_id: Session ID for resource isolation.
        """
        logger.info("[GLOBUS] stat | endpoint=%s path=%s", endpoint_id, path)
        return await globus_stat(endpoint_id, path, mcp_session_id)

    @mcp.tool()
    async def globus_submit_transfer_tool(
        source_endpoint: str,
        destination_endpoint: str,
        transfer_items: list,
        label: str = "",
        sync_level: Optional[int] = None,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Submit an async file transfer between two Globus collections.

        Transfers run asynchronously on the Globus service. Use globus_get_task
        or globus_wait_for_task to check progress.

        Args:
            source_endpoint: Source collection UUID.
            destination_endpoint: Destination collection UUID.
            transfer_items: List of {source_path, destination_path, recursive?} dicts.
            label: Human-readable label for the transfer.
            sync_level: Sync level: 0=exists, 1=size, 2=mtime, 3=checksum.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with task_id for tracking the transfer.
        """
        logger.info("[GLOBUS] submit_transfer | %s -> %s (%d items)", source_endpoint, destination_endpoint, len(transfer_items))
        return await globus_submit_transfer(source_endpoint, destination_endpoint, transfer_items, label, sync_level, mcp_session_id)

    @mcp.tool()
    async def globus_submit_delete_tool(
        endpoint_id: str,
        paths: list,
        recursive: bool = True,
        label: str = "",
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Submit an async recursive delete on a Globus collection.

        Args:
            endpoint_id: UUID of the Globus collection.
            paths: List of file/directory paths to delete.
            recursive: Recursively delete directories (default: true).
            label: Human-readable label for the delete operation.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with task_id for tracking the delete.
        """
        logger.info("[GLOBUS] submit_delete | endpoint=%s paths=%d", endpoint_id, len(paths))
        return await globus_submit_delete(endpoint_id, paths, recursive, label, mcp_session_id)

    @mcp.tool()
    async def globus_get_task_tool(
        task_id: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Get status of a Globus transfer/delete task.

        Args:
            task_id: Task ID from submit_transfer or submit_delete.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with task_status, bytes_transferred, files_transferred, etc.
        """
        logger.info("[GLOBUS] get_task | task_id=%s", task_id)
        return await globus_get_task(task_id, mcp_session_id)

    @mcp.tool()
    async def globus_list_tasks_tool(
        filter_status: Optional[str] = None,
        limit: int = 10,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """List recent Globus transfer tasks with optional status filter.

        Args:
            filter_status: Filter by status (e.g., "ACTIVE", "SUCCEEDED", "FAILED").
            limit: Maximum number of tasks to return (default: 10).
            mcp_session_id: Session ID for resource isolation.
        """
        logger.info("[GLOBUS] list_tasks | filter=%s limit=%d", filter_status, limit)
        return await globus_list_tasks(filter_status, limit, mcp_session_id)

    @mcp.tool()
    async def globus_cancel_task_tool(
        task_id: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Cancel an in-progress Globus transfer or delete task.

        Args:
            task_id: Task ID to cancel.
            mcp_session_id: Session ID for resource isolation.
        """
        logger.info("[GLOBUS] cancel_task | task_id=%s", task_id)
        return await globus_cancel_task(task_id, mcp_session_id)

    @mcp.tool()
    async def globus_wait_for_task_tool(
        task_id: str,
        timeout: int = 300,
        polling_interval: int = 5,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Wait for a Globus task to complete by polling its status.

        Args:
            task_id: Task ID to wait for.
            timeout: Maximum wait time in seconds (default: 300).
            polling_interval: Seconds between polls (default: 5).
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with final task_status, bytes/files transferred, elapsed time.
        """
        logger.info("[GLOBUS] wait_for_task | task_id=%s timeout=%d", task_id, timeout)
        return await globus_wait_for_task(task_id, timeout, polling_interval, mcp_session_id)

    @mcp.tool()
    async def globus_search_endpoints_tool(
        filter_fulltext: str,
        filter_scope: str = "all",
        limit: int = 10,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Search for Globus collections/endpoints by name or keyword.

        Args:
            filter_fulltext: Text to search for in endpoint names and descriptions.
            filter_scope: Scope filter: "all", "my-endpoints", "shared-with-me", etc.
            limit: Maximum results to return (default: 10).
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with endpoints list (id, display_name, owner, entity_type).
        """
        logger.info("[GLOBUS] search_endpoints | query='%s' scope=%s", filter_fulltext, filter_scope)
        return await globus_search_endpoints(filter_fulltext, filter_scope, limit, mcp_session_id)

    logger.info("Registered 11 Globus Transfer tools")
