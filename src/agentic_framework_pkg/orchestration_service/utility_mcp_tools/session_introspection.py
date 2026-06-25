"""Session Introspection Tools

Provides tools for querying session data, conversation history, and checkpoint snapshots.
Includes fork-chain awareness for sessions that have been auto-compacted.
"""

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from mcp import types as mcp_types
from mcp.server import Server

from agentic_framework_pkg.logger_config import get_logger
from agentic_framework_pkg.orchestration_service.context_compaction_fork_mapping import (
    get_fork_chain_session_ids,
    resolve_fork,
    resolve_fork_chain,
)
from agentic_framework_pkg.orchestration_service.persistence.session_persistence import (
    SessionNotFoundError,
    SessionPersistenceManager,
)

# Import utility modules for enhanced functionality
from .response_optimizer import optimize_response
from .telemetry_enricher import enrich_sessions_with_telemetry

logger = get_logger(__name__)


async def _verify_session_ownership(
    session_id: str,
    user_id: str,
) -> Tuple[bool, Optional[str]]:
    """Verify session ownership with fallback to checkpoint existence.

    Tier 1: Check UserSession table (sessions created via Assistants API / explicit persistence).
    Tier 2: Check LangGraph checkpoints (sessions created via Response API / CLI).

    The user_id is auto-injected from the authenticated JWT by langchain_wrappers.py,
    so if this function is reached, the caller is already authenticated. The checkpoint
    fallback skips ownership verification because checkpoint metadata from the Response
    API path does not contain owner_id.

    Returns:
        (True, None) if verified
        (False, error_message) if not verified
    """
    try:
        persistence_mgr = SessionPersistenceManager()
        session = await persistence_mgr.get_session(session_id)
        if session.user_id != user_id:
            return False, "Access denied"
        return True, None
    except SessionNotFoundError:
        # Tier 2: Session not in UserSession table (Response API / CLI sessions).
        # Check if checkpoints exist for this thread_id.
        try:
            from agentic_framework_pkg.orchestration_service.hybrid_orchestration import (
                hybrid_service,
            )

            checkpointer = hybrid_service.checkpointer
            checkpoint_tuple = await checkpointer.aget_tuple(
                {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}}
            )
            if checkpoint_tuple:
                # Session exists as checkpoints. Ownership is implicitly verified
                # because user_id was auto-injected from the authenticated JWT.
                logger.info(
                    f"[OWNERSHIP_FALLBACK] Session '{session_id}' verified via checkpoint "
                    f"(no UserSession row). checkpoint_id={checkpoint_tuple.checkpoint.get('id', '?')}"
                )
                return True, None
            else:
                return False, f"Session '{session_id}' not found"
        except Exception as e:
            logger.warning(
                f"[OWNERSHIP_FALLBACK] Checkpoint lookup failed for '{session_id}': {e}"
            )
            return False, f"Session '{session_id}' not found"


async def _extract_messages_from_checkpoints(
    session_ids: List[str],
    limit: int = 100,
    truncate_content: int = 200,
    include_tool_outputs: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Extract messages from LangGraph checkpoint state.

    Fallback for sessions without entries in the session messages table
    (e.g., Response API / CLI sessions that store messages only in checkpoints).

    Args:
        session_ids: Session/thread IDs to extract from (supports fork chains)
        limit: Max messages to return
        truncate_content: Max chars for message content (0 = no truncation)
        include_tool_outputs: Include full tool output content (vs. metadata-only)

    Returns:
        (messages_list, extraction_metadata)
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from agentic_framework_pkg.orchestration_service.hybrid_orchestration import (
        hybrid_service,
    )

    checkpointer = hybrid_service.checkpointer
    all_messages: List[Dict[str, Any]] = []
    extraction_meta: Dict[str, Any] = {
        "source": "checkpoint",
        "sessions_checked": [],
        "sessions_with_messages": [],
        "total_raw_messages": 0,
        "truncated": truncate_content > 0,
        "truncate_chars": truncate_content,
    }

    for sid in session_ids:
        extraction_meta["sessions_checked"].append(sid)
        try:
            checkpoint_tuple = await checkpointer.aget_tuple(
                {"configurable": {"thread_id": sid, "checkpoint_ns": ""}}
            )
            if not checkpoint_tuple:
                continue

            channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
            messages = channel_values.get("messages", [])
            if not messages:
                continue

            extraction_meta["sessions_with_messages"].append(sid)
            extraction_meta["total_raw_messages"] += len(messages)

            for idx, msg in enumerate(messages):
                content = ""
                if isinstance(msg.content, str):
                    content = msg.content
                elif isinstance(msg.content, list):
                    # Multi-modal content — extract text parts
                    content = " ".join(
                        part.get("text", "")
                        for part in msg.content
                        if isinstance(part, dict) and part.get("type") == "text"
                    )

                # Truncate content if configured
                full_length = len(content)
                if truncate_content > 0 and full_length > truncate_content:
                    content = content[:truncate_content] + "..."

                msg_data: Dict[str, Any] = {
                    "message_index": idx,
                    "content": content,
                    "content_length": full_length,
                }

                if isinstance(msg, HumanMessage):
                    msg_data["role"] = "user"
                elif isinstance(msg, AIMessage):
                    msg_data["role"] = "assistant"
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        if include_tool_outputs:
                            msg_data["tool_calls"] = msg.tool_calls
                        else:
                            msg_data["tool_calls"] = [
                                {"id": tc.get("id", ""), "name": tc.get("name", "")}
                                for tc in msg.tool_calls
                            ]
                elif isinstance(msg, ToolMessage):
                    msg_data["role"] = "tool"
                    msg_data["tool_call_id"] = getattr(
                        msg, "tool_call_id", "unknown"
                    )
                    tool_name = getattr(msg, "name", None)
                    if tool_name:
                        msg_data["tool_name"] = tool_name
                else:
                    msg_data["role"] = "system"

                # Add session_id if multiple sessions (fork chain)
                if len(session_ids) > 1:
                    msg_data["session_id"] = sid

                all_messages.append(msg_data)

        except Exception as e:
            logger.warning(
                f"[CHECKPOINT_EXTRACT] Failed to extract messages from "
                f"session '{sid}': {e}"
            )

    # Apply global limit (keep most recent messages)
    if len(all_messages) > limit:
        all_messages = all_messages[-limit:]
        extraction_meta["limited"] = True
        extraction_meta["limit_applied"] = limit

    return all_messages, extraction_meta


class InspectSessionForkChain:
    """Inspect the fork lineage of a session created by context auto-compaction."""

    name = "inspect_session_fork_chain"
    description = """Inspect the fork lineage of a session from context auto-compaction.

    Enables queries like:
    - "Has my session been auto-compacted?"
    - "Show the fork chain for session abc123"
    - "How many times has this session been forked?"

    Args:
        session_id: Session ID to inspect (typically the root/original session)
        user_id: User ID for authorization
        include_chain_stats: Include summary statistics (default True)

    Returns:
        Fork chain details: root_session_id, terminal_session_id, fork_count,
        is_forked flag, ordered fork_chain array, and optional chain_stats.
    """

    @staticmethod
    async def execute(
        session_id: str,
        user_id: str,
        include_chain_stats: bool = True,
    ) -> Dict[str, Any]:
        """Execute fork chain inspection."""
        try:
            # Verify session ownership (with checkpoint fallback for Response API sessions)
            verified, error = await _verify_session_ownership(session_id, user_id)
            if not verified:
                return {
                    "success": False,
                    "error": error or "Session not found or access denied",
                }

            # Resolve the full fork chain
            chain = await resolve_fork_chain(session_id)

            fork_chain_data = [
                {
                    "session_id": node.session_id,
                    "generation": node.generation,
                    "fork_reason": node.fork_reason,
                    "fork_timestamp": node.fork_timestamp,
                    "parent_session_id": node.parent_session_id,
                    "is_terminal": node.is_terminal,
                }
                for node in chain
            ]

            result = {
                "success": True,
                "root_session_id": chain[0].session_id,
                "terminal_session_id": chain[-1].session_id,
                "fork_count": len(chain) - 1,
                "is_forked": len(chain) > 1,
                "fork_chain": fork_chain_data,
            }

            if include_chain_stats and len(chain) > 1:
                reasons = [n.fork_reason for n in chain if n.fork_reason]
                result["chain_stats"] = {
                    "total_generations": chain[-1].generation,
                    "fork_reasons": reasons,
                    "first_fork_timestamp": next(
                        (n.fork_timestamp for n in chain if n.fork_timestamp), None
                    ),
                    "last_fork_timestamp": next(
                        (
                            n.fork_timestamp
                            for n in reversed(chain)
                            if n.fork_timestamp
                        ),
                        None,
                    ),
                }

            return result

        except Exception as e:
            logger.error(f"Failed to inspect fork chain: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


class QueryUserSessions:
    """Query user sessions with flexible filtering."""

    name = "query_user_sessions"
    description = """Query user sessions with flexible filtering.

    Enables introspection queries like:
    - "Show me sessions from last month with >10k tokens"
    - "Find all sessions tagged 'biology' that cost >$5"
    - "List my archived sessions from Q4 2025"

    Args:
        user_id: User ID to query sessions for
        status: Filter by session status (active, archived, pending_deletion)
        tags: Filter by tags (AND logic)
        date_from: Start date (ISO 8601 format)
        date_to: End date (ISO 8601 format)
        min_tokens: Minimum token threshold
        max_tokens: Maximum token threshold
        min_cost_usd: Minimum cost threshold
        max_cost_usd: Maximum cost threshold
        limit: Max results (default 50, max 100)
        include_telemetry: Cross-reference with Langfuse telemetry data (default False)
        include_fork_metadata: Include fork chain metadata per session (default True)
        optimize_response_size: Auto-export large responses (default True)
        max_response_tokens: Token threshold for auto-export (default 100000)

    Returns:
        JSON list of sessions with metadata (id, title, tags, tokens, cost, timestamps)
        If response exceeds max_response_tokens, auto-exports to file and returns summary + path
    """

    @staticmethod
    async def execute(
        user_id: str,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        min_tokens: Optional[int] = None,
        max_tokens: Optional[int] = None,
        min_cost_usd: Optional[float] = None,
        max_cost_usd: Optional[float] = None,
        limit: int = 50,
        include_telemetry: bool = False,
        include_fork_metadata: bool = True,
        optimize_response_size: bool = True,
        max_response_tokens: int = 100000,
    ) -> Dict[str, Any]:
        """Execute session query with filtering."""
        try:
            persistence_mgr = SessionPersistenceManager()

            # Build filter conditions
            filters = {}
            if status:
                filters["status"] = status
            if tags:
                filters["tags"] = tags
            if date_from:
                filters["date_from"] = datetime.fromisoformat(date_from)
            if date_to:
                filters["date_to"] = datetime.fromisoformat(date_to)

            # Query sessions (returns tuple: sessions list and total count)
            sessions, total_count = await persistence_mgr.list_sessions(
                user_id=user_id, **filters, limit=min(limit, 100)
            )

            # Apply token/cost filters (post-query filtering)
            filtered_sessions = []
            for session in sessions:
                if min_tokens and session.total_tokens < min_tokens:
                    continue
                if max_tokens and session.total_tokens > max_tokens:
                    continue
                if min_cost_usd and session.estimated_cost_usd < min_cost_usd:
                    continue
                if max_cost_usd and session.estimated_cost_usd > max_cost_usd:
                    continue
                filtered_sessions.append(session)

            # Format results
            result_data = [
                {
                    "session_id": s.session_id,
                    "user_id": s.user_id,
                    "title": s.title,
                    "tags": s.tags,
                    "status": s.status,
                    "total_tokens": s.total_tokens,
                    "estimated_cost_usd": (
                        float(s.estimated_cost_usd) if s.estimated_cost_usd else 0.0
                    ),
                    "created_at": s.created_at.isoformat(),
                    "last_active_at": s.last_active_at.isoformat(),
                    "session_type": s.session_type,
                }
                for s in filtered_sessions
            ]

            # Enrich with fork metadata if requested
            if include_fork_metadata:
                for session_data in result_data:
                    try:
                        chain = await resolve_fork_chain(session_data["session_id"])
                        session_data["is_forked"] = len(chain) > 1
                        session_data["fork_generation"] = chain[-1].generation
                        session_data["terminal_session_id"] = chain[-1].session_id
                        session_data["total_forks"] = len(chain) - 1
                    except Exception as e:
                        logger.debug(
                            f"Fork metadata lookup failed for {session_data['session_id']}: {e}"
                        )
                        session_data["is_forked"] = False
                        session_data["fork_generation"] = 0
                        session_data["terminal_session_id"] = session_data["session_id"]
                        session_data["total_forks"] = 0

            # Cross-reference with Langfuse telemetry if requested
            if include_telemetry:
                result_data = await enrich_sessions_with_telemetry(result_data, user_id)

            # Prepare response data
            response_data = {
                "success": True,
                "count": len(result_data),
                "sessions": result_data,
            }

            # Optimize response based on token size
            if optimize_response_size:
                return await optimize_response(
                    data=response_data,
                    user_id=user_id,
                    max_tokens=max_response_tokens,
                    category="session_queries",
                    export_prefix="sessions",
                )

            return response_data

        except Exception as e:
            logger.error(f"Failed to query user sessions: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


class GetSessionHistory:
    """Retrieve full conversation history for a session."""

    name = "get_session_history"
    description = """Retrieve full conversation history for a session.

    Enables queries like:
    - "Show me the conversation history for session abc123"
    - "What tool outputs were generated in session xyz789?"
    - "Show me full history including forked sessions"

    Args:
        session_id: Session ID to retrieve
        user_id: User ID for authorization
        include_tool_outputs: Include tool output details (large data)
        include_fork_chain: Merge messages from all sessions in the fork chain (default False)
        context_layer: Filter by context layer (active/historical/None for both)
        limit: Max messages per session (default 100)
        optimize_response_size: Auto-export large responses (default True)
        max_response_tokens: Token threshold for auto-export (default 50000, lower than sessions due to message content size)

    Returns:
        JSON array of messages with metadata (role, content, timestamps, tool calls)
        If response exceeds max_response_tokens, auto-exports to file and returns summary + path
    """

    @staticmethod
    async def execute(
        session_id: str,
        user_id: str,
        include_tool_outputs: bool = False,
        include_fork_chain: bool = False,
        context_layer: Optional[str] = None,
        limit: int = 100,
        truncate_content: int = 200,
        optimize_response_size: bool = True,
        max_response_tokens: int = 50000,
    ) -> Dict[str, Any]:
        """Execute session history retrieval.

        When the session messages table has no entries (e.g., Response API / CLI
        sessions), falls back to extracting messages from LangGraph checkpoint
        state.  Content is truncated to ``truncate_content`` characters in the
        checkpoint fallback path to conserve the agent's token window.
        """
        try:
            # Verify session ownership (with checkpoint fallback for Response API sessions)
            verified, error = await _verify_session_ownership(session_id, user_id)
            if not verified:
                return {
                    "success": False,
                    "error": error or "Session not found or access denied",
                }

            persistence_mgr = SessionPersistenceManager()

            # Determine which session IDs to query
            if include_fork_chain:
                session_ids = await get_fork_chain_session_ids(session_id)
            else:
                session_ids = [session_id]

            is_fork_chain = len(session_ids) > 1

            # Retrieve and merge messages from all sessions in chain order
            result_data: List[Dict[str, Any]] = []
            for sid in session_ids:
                messages = await persistence_mgr.get_messages(
                    session_id=sid, context_layer=context_layer, limit=limit
                )

                for msg in messages:
                    msg_data = {
                        "id": str(msg.id),
                        "message_index": msg.message_index,
                        "role": msg.message_role,
                        "content": msg.message_content,
                        "created_at": msg.created_at.isoformat(),
                        "context_layer": msg.context_layer,
                        "importance_score": msg.importance_score,
                        "tool_call_ids": msg.tool_call_ids,
                    }

                    # Track source session when querying fork chain
                    if is_fork_chain:
                        msg_data["session_id"] = sid

                    # Include tool outputs if requested
                    if include_tool_outputs and msg.has_tool_outputs:
                        tool_outputs = (
                            await persistence_mgr.get_tool_outputs_for_message(msg.id)
                        )
                        msg_data["tool_outputs"] = [
                            {
                                "tool_name": output.tool_name,
                                "output_size": output.output_size,
                                "created_at": output.created_at.isoformat(),
                            }
                            for output in tool_outputs
                        ]

                    result_data.append(msg_data)

            # Apply global limit across merged results
            if is_fork_chain and len(result_data) > limit:
                result_data = result_data[:limit]

            # Fallback: If no messages found in persistence table, try checkpoint extraction
            is_checkpoint_source = False
            extraction_meta: Optional[Dict[str, Any]] = None
            if not result_data:
                logger.info(
                    f"[SESSION_HISTORY] No messages in persistence table for "
                    f"session(s) {session_ids}. Falling back to checkpoint extraction."
                )
                checkpoint_messages, extraction_meta = (
                    await _extract_messages_from_checkpoints(
                        session_ids=session_ids,
                        limit=limit,
                        truncate_content=truncate_content,
                        include_tool_outputs=include_tool_outputs,
                    )
                )
                result_data = checkpoint_messages
                is_checkpoint_source = True

            # Prepare response data
            response_data: Dict[str, Any] = {
                "success": True,
                "session_id": session_id,
                "message_count": len(result_data),
                "messages": result_data,
            }

            if is_fork_chain:
                response_data["sessions_queried"] = session_ids
                response_data["is_fork_chain"] = True

            if is_checkpoint_source:
                response_data["data_source"] = "checkpoint"
                response_data["extraction_metadata"] = extraction_meta
                response_data["hint"] = (
                    "Messages extracted from LangGraph checkpoints (content truncated). "
                    "Use include_tool_outputs=True for full tool call details, "
                    "or ExportSessionData for complete untruncated history."
                )

            # Optimize response based on token size
            if optimize_response_size:
                return await optimize_response(
                    data=response_data,
                    user_id=user_id,
                    max_tokens=max_response_tokens,
                    category="session_history",
                    export_prefix=f"history_{session_id}",
                )

            return response_data

        except Exception as e:
            logger.error(f"Failed to get session history: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


class QueryCheckpoints:
    """Query LangGraph checkpoint snapshots for a thread."""

    name = "query_checkpoints"
    description = """Query LangGraph checkpoint snapshots for a thread.

    Enables debugging queries like:
    - "Show me the checkpoint history for thread abc123"
    - "What was the agent state at checkpoint xyz?"

    Args:
        thread_id: Thread ID to query checkpoints for
        user_id: User ID for authorization (verifies thread ownership via session)
        auto_resolve_fork: Automatically resolve to terminal fork session for checkpoint lookup (default True)
        limit: Max checkpoints to return (default 10)

    Returns:
        JSON array of checkpoints with metadata (checkpoint_id, parent_id, type, created_at)
    """

    @staticmethod
    async def execute(
        thread_id: str,
        user_id: str,
        auto_resolve_fork: bool = True,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Execute checkpoint query."""
        try:
            from agentic_framework_pkg.orchestration_service.hybrid_orchestration import (
                hybrid_service,
            )

            # Verify thread ownership (with checkpoint fallback for Response API sessions)
            verified, error = await _verify_session_ownership(thread_id, user_id)
            if not verified:
                return {
                    "success": False,
                    "error": error or "Thread not found or access denied",
                }

            # Resolve to terminal fork if auto_resolve_fork is enabled
            effective_thread_id = thread_id
            fork_resolved = False
            if auto_resolve_fork:
                resolved = await resolve_fork(thread_id)
                if resolved != thread_id:
                    effective_thread_id = resolved
                    fork_resolved = True
                    logger.debug(
                        f"[CHECKPOINT_QUERY] Fork resolved: {thread_id} -> {effective_thread_id}"
                    )

            # Query checkpoints via shared checkpointer
            checkpointer = hybrid_service.checkpointer
            config = {"configurable": {"thread_id": effective_thread_id}}

            checkpoints = []
            async for checkpoint_tuple in checkpointer.alist(config, limit=limit):
                checkpoints.append(
                    {
                        "checkpoint_id": checkpoint_tuple.checkpoint["id"],
                        "checkpoint_ns": checkpoint_tuple.config.get(
                            "configurable", {}
                        ).get("checkpoint_ns", ""),
                        "parent_checkpoint_id": (
                            checkpoint_tuple.parent_config.get("configurable", {}).get(
                                "checkpoint_id"
                            )
                            if checkpoint_tuple.parent_config
                            else None
                        ),
                        "metadata": checkpoint_tuple.metadata,
                        "created_at": (
                            checkpoint_tuple.metadata.get("created_at")
                            if checkpoint_tuple.metadata
                            else None
                        ),
                    }
                )

            result = {
                "success": True,
                "thread_id": thread_id,
                "effective_thread_id": effective_thread_id,
                "fork_resolved": fork_resolved,
                "checkpoint_count": len(checkpoints),
                "checkpoints": checkpoints,
            }

            return result

        except Exception as e:
            logger.error(f"Failed to query checkpoints: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
