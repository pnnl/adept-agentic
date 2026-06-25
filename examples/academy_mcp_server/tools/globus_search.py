"""
Globus Search Tools

MCP tool implementations for Globus Search API operations:
full-text and faceted search, scroll pagination, metadata ingestion,
subject management, and index discovery.
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


async def globus_search_query(
    index_id: str,
    q: str,
    limit: int = 10,
    offset: int = 0,
    filters: Optional[List[Dict[str, Any]]] = None,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_search_client()
        query_params: Dict[str, Any] = {
            "q": q,
            "limit": limit,
            "offset": offset,
        }
        if filters:
            query_params["filters"] = filters
        result = client.post_search(index_id, query_params)
        entries = []
        for gme in result.get("gmeta", []):
            entries.append({
                "subject": gme.get("subject"),
                "entries": [
                    {
                        "content": e.get("content", {}),
                        "entry_id": e.get("entry_id"),
                    }
                    for e in gme.get("entries", [])
                ],
            })
        return {
            "status": "success",
            "index_id": index_id,
            "query": q,
            "total": result.get("total", 0),
            "count": result.get("count", 0),
            "results": entries,
        }
    except Exception as e:
        logger.error("[GLOBUS] search_query error: %s", e)
        return {"status": "error", "error": str(e), "index_id": index_id}


async def globus_search_scroll(
    index_id: str,
    q: str = "*",
    limit: int = 100,
    marker: Optional[str] = None,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_search_client()
        kwargs: Dict[str, Any] = {"q": q, "limit": limit}
        if marker:
            kwargs["marker"] = marker
        result = client.scroll(index_id, **kwargs)
        entries = []
        for gme in result.get("gmeta", []):
            entries.append({
                "subject": gme.get("subject"),
                "entries": [e.get("content", {}) for e in gme.get("entries", [])],
            })
        return {
            "status": "success",
            "index_id": index_id,
            "count": len(entries),
            "has_next_page": result.get("has_next_page", False),
            "marker": result.get("marker"),
            "results": entries,
        }
    except Exception as e:
        logger.error("[GLOBUS] search_scroll error: %s", e)
        return {"status": "error", "error": str(e), "index_id": index_id}


async def globus_ingest_entries(
    index_id: str,
    entries: List[Dict[str, Any]],
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_search_client()
        ingest_doc = {
            "ingest_type": "GMetaList",
            "ingest_data": {
                "gmeta": [
                    {
                        "subject": entry["subject"],
                        "visible_to": entry.get("visible_to", ["public"]),
                        "content": entry.get("content", {}),
                    }
                    for entry in entries
                ]
            },
        }
        result = client.ingest(index_id, ingest_doc)
        return {
            "status": "success",
            "index_id": index_id,
            "task_id": result.get("task_id"),
            "entries_ingested": len(entries),
        }
    except Exception as e:
        logger.error("[GLOBUS] ingest_entries error: %s", e)
        return {"status": "error", "error": str(e), "index_id": index_id}


async def globus_get_search_subject(
    index_id: str,
    subject: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_search_client()
        result = client.get_subject(index_id, subject)
        entries = [
            {
                "entry_id": e.get("entry_id"),
                "content": e.get("content", {}),
            }
            for e in result.get("entries", [])
        ]
        return {
            "status": "success",
            "index_id": index_id,
            "subject": subject,
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        logger.error("[GLOBUS] get_search_subject error: %s", e)
        return {"status": "error", "error": str(e), "index_id": index_id, "subject": subject}


async def globus_delete_search_subject(
    index_id: str,
    subject: str,
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_search_client()
        client.delete_subject(index_id, subject)
        return {"status": "success", "index_id": index_id, "subject": subject, "message": "Subject deleted"}
    except Exception as e:
        logger.error("[GLOBUS] delete_search_subject error: %s", e)
        return {"status": "error", "error": str(e), "index_id": index_id, "subject": subject}


async def globus_list_search_indices(
    mcp_session_id: Optional[str] = None,
) -> dict:
    try:
        client = globus_manager.get_search_client()
        # The SDK method is get_index_list or similar
        result = client.get("/v1/index_list")
        indices = [
            {
                "id": idx.get("id"),
                "display_name": idx.get("display_name"),
                "description": idx.get("description"),
                "status": idx.get("status"),
            }
            for idx in result.get("index_list", [])
        ]
        return {"status": "success", "indices": indices, "count": len(indices)}
    except Exception as e:
        logger.error("[GLOBUS] list_search_indices error: %s", e)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register all Globus Search tools with the given FastMCP instance."""

    @mcp.tool()
    async def globus_search_query_tool(
        index_id: str,
        q: str,
        limit: int = 10,
        offset: int = 0,
        filters: Optional[list] = None,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Full-text and faceted search on a Globus Search index.

        Args:
            index_id: UUID of the Globus Search index to query.
            q: Search query string (supports Lucene syntax).
            limit: Maximum results to return (default: 10).
            offset: Result offset for pagination (default: 0).
            filters: Optional list of filter dicts ({field, values, type}).
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with total count, results list (subject + content entries).
        """
        logger.info("[GLOBUS] search_query | index=%s q='%s'", index_id, q)
        return await globus_search_query(index_id, q, limit, offset, filters, mcp_session_id)

    @mcp.tool()
    async def globus_search_scroll_tool(
        index_id: str,
        q: str = "*",
        limit: int = 100,
        marker: Optional[str] = None,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Paginated scroll through large result sets in a Globus Search index.

        Use the returned 'marker' value in subsequent calls to page through results.

        Args:
            index_id: UUID of the Globus Search index.
            q: Search query string (default: "*" for all).
            limit: Results per page (default: 100).
            marker: Pagination marker from previous scroll call.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with results, has_next_page flag, and next marker.
        """
        logger.info("[GLOBUS] search_scroll | index=%s marker=%s", index_id, marker)
        return await globus_search_scroll(index_id, q, limit, marker, mcp_session_id)

    @mcp.tool()
    async def globus_ingest_entries_tool(
        index_id: str,
        entries: list,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Ingest metadata entries into a Globus Search index.

        Each entry must have a 'subject' (URI) and 'content' (metadata dict).
        Optionally include 'visible_to' for access control (default: public).

        Args:
            index_id: UUID of the Globus Search index.
            entries: List of {subject, content, visible_to?} dicts.
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with task_id for tracking ingestion progress.
        """
        logger.info("[GLOBUS] ingest_entries | index=%s count=%d", index_id, len(entries))
        return await globus_ingest_entries(index_id, entries, mcp_session_id)

    @mcp.tool()
    async def globus_get_search_subject_tool(
        index_id: str,
        subject: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Get all entries for a specific subject URI in a Globus Search index.

        Args:
            index_id: UUID of the Globus Search index.
            subject: Subject URI to retrieve.
            mcp_session_id: Session ID for resource isolation.
        """
        logger.info("[GLOBUS] get_search_subject | index=%s subject=%s", index_id, subject)
        return await globus_get_search_subject(index_id, subject, mcp_session_id)

    @mcp.tool()
    async def globus_delete_search_subject_tool(
        index_id: str,
        subject: str,
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """Delete a subject and all its entries from a Globus Search index.

        Args:
            index_id: UUID of the Globus Search index.
            subject: Subject URI to delete.
            mcp_session_id: Session ID for resource isolation.
        """
        logger.info("[GLOBUS] delete_search_subject | index=%s subject=%s", index_id, subject)
        return await globus_delete_search_subject(index_id, subject, mcp_session_id)

    @mcp.tool()
    async def globus_list_search_indices_tool(
        mcp_session_id: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """List all Globus Search indices accessible to the current user.

        Args:
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with indices list (id, display_name, description, status).
        """
        logger.info("[GLOBUS] list_search_indices")
        return await globus_list_search_indices(mcp_session_id)

    logger.info("Registered 6 Globus Search tools")
