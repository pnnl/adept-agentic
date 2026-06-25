"""Observability and Export Tools

Provides tools for querying telemetry data and exporting session data.
Includes fork-chain awareness for sessions that have been auto-compacted.
"""

import gzip
import json
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from agentic_framework_pkg.logger_config import get_logger
from agentic_framework_pkg.orchestration_service.context_compaction_fork_mapping import (
    get_fork_chain_session_ids,
    resolve_fork_chain,
)
from agentic_framework_pkg.orchestration_service.persistence.session_persistence import (
    SessionPersistenceManager,
)

# Import utility modules for enhanced functionality
from .response_optimizer import optimize_response
from .session_introspection import _verify_session_ownership

logger = get_logger(__name__)


class QueryLangfuseTelemetry:
    """Query Langfuse observability data for token usage, tool calls, and errors."""

    name = "query_langfuse_telemetry"
    description = """Query Langfuse observability data for token usage, tool calls, and errors.

    By default, queries the FULL session history including all context-compaction forks.
    The session_id is auto-resolved to the root and the fork chain is walked forward
    to capture traces from every fork generation. Set include_fork_chain=False to query
    only a specific session_id.

    Enables observability queries like:
    - "What tools were used in this session?"
    - "Show me the token usage breakdown for last week"
    - "What errors occurred in multi-agent session xyz?"
    - "Show me all telemetry across forked sessions"

    Args:
        user_id: User ID for authorization
        session_id: Filter by session_id (auto-resolved to root of fork chain)
        mcp_session_id: Filter by mcp_session_id (in trace metadata)
        multi_agent_session_id: Filter by multi_agent_session_id
        include_fork_chain: Query all sessions in the fork chain (default True when auto-injected)
        date_from: Start date (ISO 8601)
        date_to: End date (ISO 8601)
        limit: Max traces to return (default 50)
        optimize_response_size: Auto-export large responses (default True)
        max_response_tokens: Token threshold for auto-export (default 100000)

    Returns:
        JSON array of traces with tool calls, token usage, and costs
        If response exceeds max_response_tokens, auto-exports to file and returns summary + path
    """

    @staticmethod
    async def execute(
        user_id: str,
        session_id: Optional[str] = None,
        mcp_session_id: Optional[str] = None,
        multi_agent_session_id: Optional[str] = None,
        include_fork_chain: bool = False,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
        optimize_response_size: bool = True,
        max_response_tokens: int = 100000,
    ) -> Dict[str, Any]:
        """Execute Langfuse telemetry query."""
        try:
            LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")
            LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
            LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")

            if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
                return {
                    "success": False,
                    "status": "unavailable",
                    "error": "Langfuse credentials not configured",
                    "hint": "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY environment variables",
                }

            # Determine which session IDs to query
            session_ids_to_query: List[str] = []
            if session_id:
                if include_fork_chain:
                    session_ids_to_query = await get_fork_chain_session_ids(session_id)
                else:
                    session_ids_to_query = [session_id]

            # Collect traces across all session IDs
            all_filtered_traces: List[Dict[str, Any]] = []
            seen_trace_ids: set = set()
            sessions_queried: List[str] = []

            query_targets = session_ids_to_query if session_ids_to_query else [None]
            for sid in query_targets:
                # Build query parameters
                params: Dict[str, Any] = {"page": 1, "limit": limit}

                if sid:
                    params["sessionId"] = sid
                    sessions_queried.append(sid)
                if date_from:
                    params["fromTimestamp"] = date_from
                if date_to:
                    params["toTimestamp"] = date_to

                # Query Langfuse REST API with async httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        f"{LANGFUSE_HOST}/api/public/traces",
                        params=params,
                        auth=(LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY),
                    )

                if response.status_code != 200:
                    logger.warning(
                        f"Langfuse API error for session {sid}: {response.status_code}"
                    )
                    continue

                traces = response.json().get("data", [])

                # Filter by mcp_session_id, multi_agent_session_id, and user ownership
                for trace in traces:
                    metadata = trace.get("metadata", {})

                    if (
                        mcp_session_id
                        and metadata.get("adept_mcp_session_id") != mcp_session_id
                    ):
                        continue
                    if (
                        multi_agent_session_id
                        and metadata.get("adept_multi_agent_session_id")
                        != multi_agent_session_id
                    ):
                        continue

                    # Verify user ownership
                    if metadata.get("adept_user_id") != user_id:
                        continue

                    # Deduplicate by trace_id across fork chain queries
                    trace_id = trace.get("id")
                    if trace_id in seen_trace_ids:
                        continue
                    seen_trace_ids.add(trace_id)

                    all_filtered_traces.append(
                        {
                            "trace_id": trace_id,
                            "name": trace.get("name"),
                            "session_id": trace.get("sessionId"),
                            "timestamp": trace.get("timestamp"),
                            "metadata": metadata,
                            "usage": trace.get("usage", {}),
                            "observations": len(trace.get("observations", [])),
                        }
                    )

            # Handle empty results gracefully
            total_traces = len(all_filtered_traces)
            if total_traces == 0:
                return {
                    "success": True,
                    "status": "empty",
                    "total_traces": 0,
                    "message": f"No Langfuse traces found for session {session_id}. Ensure tracing is enabled and session ID matches.",
                    "traces": [],
                }

            # Prepare response data
            response_data: Dict[str, Any] = {
                "success": True,
                "status": "success",
                "trace_count": total_traces,
                "traces": all_filtered_traces,
            }

            if include_fork_chain and len(sessions_queried) > 1:
                response_data["sessions_queried"] = sessions_queried
                response_data["is_fork_chain"] = True

            # Optimize response based on token size
            if optimize_response_size:
                return await optimize_response(
                    data=response_data,
                    user_id=user_id,
                    max_tokens=max_response_tokens,
                    category="telemetry",
                    export_prefix="traces",
                )

            return response_data

        except Exception as e:
            logger.error(f"Failed to query Langfuse telemetry: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


class ExportSessionData:
    """Export session data to file."""

    name = "export_session_data"
    description = """Export session data to file.

    Enables export queries like:
    - "Export session abc123 to JSON"
    - "Generate a PDF report for my last session"
    - "Export my session as compressed markdown"
    - "Export my session with fork lineage"

    Args:
        session_id: Session ID to export
        user_id: User ID for authorization
        export_format: Export format (json, markdown, jupyter, pdf)
        include_tool_outputs: Include full tool outputs (can be large)
        include_fork_lineage: Include fork chain metadata and messages from all forked sessions (default False)
        compress: Compress output with gzip (default False)

    Returns:
        File path to exported data (with .gz extension if compressed)
    """

    @staticmethod
    async def execute(
        session_id: str,
        user_id: str,
        export_format: str = "json",
        include_tool_outputs: bool = False,
        include_fork_lineage: bool = False,
        compress: bool = False,
    ) -> Dict[str, Any]:
        """Execute session data export."""
        try:
            # Verify session ownership (with checkpoint fallback for Response API sessions)
            verified, error = await _verify_session_ownership(session_id, user_id)
            if not verified:
                return {
                    "success": False,
                    "error": error or "Session not found or access denied",
                }

            persistence_mgr = SessionPersistenceManager()

            # Try to load session metadata (may not exist for Response API sessions)
            try:
                session = await persistence_mgr.get_session(session_id)
            except Exception:
                session = None

            # Determine session IDs to export
            if include_fork_lineage:
                session_ids = await get_fork_chain_session_ids(session_id)
                fork_chain = await resolve_fork_chain(session_id)
            else:
                session_ids = [session_id]
                fork_chain = None

            # Collect messages from all sessions in the chain
            all_messages = []
            for sid in session_ids:
                messages = await persistence_mgr.get_messages(
                    session_id=sid, limit=1000
                )
                for msg in messages:
                    msg_data = {
                        "message_index": msg.message_index,
                        "role": msg.message_role,
                        "content": msg.message_content,
                        "created_at": msg.created_at.isoformat(),
                        "tool_call_ids": msg.tool_call_ids,
                    }

                    if include_fork_lineage and len(session_ids) > 1:
                        msg_data["session_id"] = sid

                    if include_tool_outputs and msg.has_tool_outputs:
                        tool_outputs = (
                            await persistence_mgr.get_tool_outputs_for_message(msg.id)
                        )
                        msg_data["tool_outputs"] = [
                            {
                                "tool_name": output.tool_name,
                                "output_content": output.output_content,
                                "created_at": output.created_at.isoformat(),
                            }
                            for output in tool_outputs
                        ]

                    all_messages.append(msg_data)

            # Format export data (use defaults if no UserSession row exists)
            export_data: Dict[str, Any] = {
                "session_id": session_id,
                "title": session.title if session else session_id,
                "created_at": (
                    session.created_at.isoformat() if session else datetime.utcnow().isoformat()
                ),
                "last_active_at": (
                    session.last_active_at.isoformat() if session else datetime.utcnow().isoformat()
                ),
                "total_tokens": session.total_tokens if session else 0,
                "estimated_cost_usd": (
                    float(session.estimated_cost_usd)
                    if session and session.estimated_cost_usd
                    else 0.0
                ),
                "messages": all_messages,
            }

            # Add fork lineage metadata if requested
            if include_fork_lineage and fork_chain:
                export_data["fork_lineage"] = {
                    "is_forked": len(fork_chain) > 1,
                    "fork_count": len(fork_chain) - 1,
                    "root_session_id": fork_chain[0].session_id,
                    "terminal_session_id": fork_chain[-1].session_id,
                    "sessions_included": session_ids,
                    "chain": [
                        {
                            "session_id": node.session_id,
                            "generation": node.generation,
                            "fork_reason": node.fork_reason,
                            "fork_timestamp": node.fork_timestamp,
                            "parent_session_id": node.parent_session_id,
                            "is_terminal": node.is_terminal,
                        }
                        for node in fork_chain
                    ],
                }

            # Export to file
            export_dir = os.getenv("EXPORT_DIR", "/app/data/exports")
            os.makedirs(export_dir, exist_ok=True)

            if export_format == "json":
                export_path = os.path.join(export_dir, f"{session_id}.json")
                with open(export_path, "w") as f:
                    json.dump(export_data, f, indent=2)

            elif export_format == "markdown":
                export_path = os.path.join(export_dir, f"{session_id}.md")
                with open(export_path, "w") as f:
                    f.write(f"# Session: {export_data['title']}\n\n")
                    f.write(
                        f"**Created**: {export_data['created_at']}  \n"
                        f"**Last Active**: {export_data['last_active_at']}  \n"
                        f"**Tokens**: {export_data['total_tokens']:,}  \n"
                        f"**Cost**: ${export_data['estimated_cost_usd']:.4f}\n\n"
                    )

                    # Write fork lineage info if present
                    if "fork_lineage" in export_data:
                        lineage = export_data["fork_lineage"]
                        f.write("## Fork Lineage\n\n")
                        f.write(f"**Forked**: {lineage['is_forked']}  \n")
                        f.write(f"**Fork Count**: {lineage['fork_count']}  \n")
                        f.write(
                            f"**Root Session**: {lineage['root_session_id']}  \n"
                        )
                        f.write(
                            f"**Terminal Session**: {lineage['terminal_session_id']}\n\n"
                        )

                    f.write("---\n\n")
                    f.write("## Conversation\n\n")

                    for msg in export_data["messages"]:
                        f.write(f"### {msg['role'].upper()}\n\n")
                        f.write(f"{msg['content']}\n\n")
                        if msg.get("tool_outputs"):
                            f.write("**Tool Outputs:**\n")
                            for output in msg["tool_outputs"]:
                                f.write(f"- {output['tool_name']}\n")

            elif export_format == "jupyter":
                export_path = os.path.join(export_dir, f"{session_id}.ipynb")
                # Create Jupyter notebook structure
                notebook = {
                    "cells": [],
                    "metadata": {},
                    "nbformat": 4,
                    "nbformat_minor": 4,
                }

                # Add markdown cell with session info
                notebook["cells"].append(
                    {
                        "cell_type": "markdown",
                        "metadata": {},
                        "source": [
                            f"# Session: {export_data['title']}\n",
                            f"\n**Created**: {export_data['created_at']}  \n",
                            f"**Tokens**: {export_data['total_tokens']:,}  \n",
                            f"**Cost**: ${export_data['estimated_cost_usd']:.4f}",
                        ],
                    }
                )

                # Add conversation cells
                for msg in export_data["messages"]:
                    notebook["cells"].append(
                        {
                            "cell_type": "markdown",
                            "metadata": {},
                            "source": [f"## {msg['role'].upper()}\n", msg["content"]],
                        }
                    )

                with open(export_path, "w") as f:
                    json.dump(notebook, f, indent=2)

            elif export_format == "pdf":
                # PDF export requires additional dependencies (reportlab, etc.)
                return {
                    "success": False,
                    "error": "PDF export not yet implemented (requires reportlab)",
                }

            else:
                return {
                    "success": False,
                    "error": f"Unsupported export format: {export_format}",
                }

            # Apply compression if requested
            final_export_path = export_path
            if compress:
                compressed_path = f"{export_path}.gz"
                with open(export_path, "rb") as f_in:
                    with gzip.open(compressed_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)

                # Remove uncompressed file
                os.remove(export_path)
                final_export_path = compressed_path
                logger.info(f"Compressed export to {compressed_path}")

            return {
                "success": True,
                "export_path": final_export_path,
                "format": export_format,
                "compressed": compress,
                "message": f"Session exported to {final_export_path}",
            }

        except Exception as e:
            logger.error(f"Failed to export session data: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
