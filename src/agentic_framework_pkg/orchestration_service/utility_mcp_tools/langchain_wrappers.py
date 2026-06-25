"""LangChain Tool Wrappers for Utility Introspection Tools

Provides LangChain-compatible tool wrappers for the introspection tools.
"""

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import urlparse

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agentic_framework_pkg.logger_config import get_logger

from .file_operations import GeneratePresignedURL
from .observability import ExportSessionData, QueryLangfuseTelemetry
from .plotting_utility import PlottingUtility
from .session_introspection import (
    GetSessionHistory,
    InspectSessionForkChain,
    QueryCheckpoints,
    QueryUserSessions,
)

if TYPE_CHECKING:
    from ..request_context import RequestContext

logger = get_logger(__name__)


# Pydantic Schemas for Utility Tools (Session 53 Fix)
class GetSessionHistoryInput(BaseModel):
    """Input schema for GetSessionHistory tool."""

    session_id: Optional[str] = Field(
        default=None,
        description="Session ID to retrieve history for (auto-injected from session context if omitted)",
    )
    include_tool_outputs: bool = Field(
        default=False,
        description="Include tool output details in response (may be large)",
    )
    include_fork_chain: bool = Field(
        default=False,
        description="Merge messages from all sessions in the fork chain (for auto-compacted sessions)",
    )
    context_layer: Optional[str] = Field(
        default=None,
        description="Filter by context layer: 'active', 'historical', or None for both",
    )
    limit: int = Field(
        default=100, description="Maximum number of messages to return"
    )


class QueryCheckpointsInput(BaseModel):
    """Input schema for QueryCheckpoints tool."""

    thread_id: Optional[str] = Field(
        default=None,
        description="Thread ID to query checkpoints for (auto-injected from session context if omitted)",
    )
    auto_resolve_fork: bool = Field(
        default=True,
        description="Automatically resolve to terminal fork session for checkpoint lookup",
    )
    limit: int = Field(
        default=10, description="Maximum number of checkpoints to return"
    )


class QueryLangfuseTelemetryInput(BaseModel):
    """Input schema for QueryLangfuseTelemetry tool."""

    session_id: Optional[str] = Field(
        default=None, description="Session ID to filter telemetry (optional)"
    )
    mcp_session_id: Optional[str] = Field(
        default=None, description="MCP session ID to filter telemetry (optional)"
    )
    include_fork_chain: bool = Field(
        default=False,
        description="Query telemetry across all sessions in the fork chain (for auto-compacted sessions)",
    )
    limit: int = Field(
        default=10, description="Maximum number of telemetry records to return"
    )


class InspectSessionForkChainInput(BaseModel):
    """Input schema for InspectSessionForkChain tool."""

    session_id: Optional[str] = Field(
        default=None,
        description="Session ID to inspect fork chain for (auto-injected from session context if omitted)",
    )
    include_chain_stats: bool = Field(
        default=True,
        description="Include summary statistics about the fork chain",
    )


def get_thread_id_from_agent_context(
    provided_thread_id: Optional[str], session_context: Optional[Dict[str, Any]]
) -> Optional[str]:
    """
    Extract thread_id with 3-tier fallback strategy.

    Priority:
    1. Explicit provided_thread_id parameter
    2. session_context['thread_id']
    3. session_context['session_id'] (fallback)

    Args:
        provided_thread_id: Explicitly provided thread_id parameter
        session_context: Dict containing thread_id and/or session_id

    Returns:
        thread_id or None with clear error message
    """
    if provided_thread_id:
        return provided_thread_id

    if session_context:
        if "thread_id" in session_context:
            return session_context["thread_id"]
        if "session_id" in session_context:
            logger.debug("Using session_id as thread_id fallback")
            return session_context["session_id"]

    logger.warning("No thread_id available from context")
    return None


def create_query_user_sessions_tool(
    user_id: str,
    session_id: Optional[str] = None,
    mcp_session_id: Optional[str] = None,
) -> StructuredTool:
    """Create context-aware QueryUserSessions tool with auto-injected context.

    Args:
        user_id: User UUID to auto-inject for authorization
        session_id: Main session/thread ID to auto-inject for filtering (optional)
        mcp_session_id: MCP session ID for fallback session resolution (optional)

    Returns:
        StructuredTool with session context automatically provided
    """

    async def query_user_sessions_wrapper(**kwargs) -> str:
        """Wrapper function for QueryUserSessions with auto-injected session context."""
        try:
            # Auto-inject user_id if not provided by agent
            if "user_id" not in kwargs:
                kwargs["user_id"] = user_id
                logger.debug(f"[AUTO_INJECT] user_id={user_id} for query_user_sessions")

            result = await QueryUserSessions.execute(**kwargs)
            # Return JSON string for LLM consumption
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"QueryUserSessions tool error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

    return StructuredTool.from_function(
        coroutine=query_user_sessions_wrapper,
        name=QueryUserSessions.name,
        description=QueryUserSessions.description,
    )


def create_get_session_history_tool(
    user_id: str,
    thread_id: Optional[str] = None,
    mcp_session_id: Optional[str] = None,
) -> StructuredTool:
    """Create context-aware GetSessionHistory tool with auto-injected context.

    Args:
        user_id: User UUID to auto-inject for authorization
        thread_id: Main thread/session ID to auto-inject for default queries (optional)
        mcp_session_id: MCP session ID for fallback session resolution (optional)

    Returns:
        StructuredTool with session context automatically provided
    """

    async def get_session_history_wrapper(**kwargs) -> str:
        """Wrapper function for GetSessionHistory with auto-injected session context."""
        try:
            # Auto-inject user_id if not provided by agent
            if "user_id" not in kwargs:
                kwargs["user_id"] = user_id
                logger.debug(f"[AUTO_INJECT] user_id={user_id} for get_session_history")

            # Auto-inject session_id if not provided (or None) and we have it (map thread_id -> session_id)
            if not kwargs.get("session_id") and thread_id:
                kwargs["session_id"] = thread_id
                logger.debug(
                    f"[AUTO_INJECT] session_id={thread_id} for get_session_history"
                )

            # Fallback: use mcp_session_id if session_id still not set
            if not kwargs.get("session_id") and mcp_session_id:
                kwargs["session_id"] = mcp_session_id
                logger.debug(
                    f"[AUTO_INJECT] session_id={mcp_session_id} (from mcp_session_id) for get_session_history"
                )

            result = await GetSessionHistory.execute(**kwargs)
            # Return JSON string for LLM consumption
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"GetSessionHistory tool error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

    return StructuredTool.from_function(
        coroutine=get_session_history_wrapper,
        name=GetSessionHistory.name,
        description=GetSessionHistory.description,
        args_schema=GetSessionHistoryInput,  # Session 53 fix: explicit schema for LLM
    )


def create_query_checkpoints_tool(
    user_id: str,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mcp_session_id: Optional[str] = None,
) -> StructuredTool:
    """Create context-aware QueryCheckpoints tool with auto-injected context.

    Args:
        user_id: User UUID to auto-inject for authorization
        thread_id: Main thread/session ID to auto-inject for default queries (optional)
        session_id: Session ID to use as fallback for thread_id (optional)
        mcp_session_id: MCP session ID for additional fallback resolution (optional)

    Returns:
        StructuredTool with session context automatically provided
    """

    async def query_checkpoints_wrapper(**kwargs) -> str:
        """Wrapper function for QueryCheckpoints with auto-injected session context."""
        try:
            # Auto-inject user_id if not provided by agent
            if "user_id" not in kwargs:
                kwargs["user_id"] = user_id
                logger.debug(f"[AUTO_INJECT] user_id={user_id} for query_checkpoints")

            # Auto-detect thread_id from available context
            effective_thread_id = get_thread_id_from_agent_context(
                provided_thread_id=kwargs.get("thread_id"),
                session_context={"thread_id": thread_id, "session_id": session_id},
            )

            # Fallback: use mcp_session_id if thread_id still not resolved
            if not effective_thread_id and mcp_session_id:
                effective_thread_id = mcp_session_id
                logger.debug(
                    f"[AUTO_INJECT] thread_id={mcp_session_id} (from mcp_session_id) for query_checkpoints"
                )

            if not effective_thread_id:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Thread ID could not be determined. Provide thread_id parameter or ensure session context is available.",
                    }
                )

            # Inject into kwargs
            kwargs["thread_id"] = effective_thread_id

            result = await QueryCheckpoints.execute(**kwargs)
            # Return JSON string for LLM consumption
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"QueryCheckpoints tool error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

    return StructuredTool.from_function(
        coroutine=query_checkpoints_wrapper,
        name=QueryCheckpoints.name,
        description=QueryCheckpoints.description,
        args_schema=QueryCheckpointsInput,  # Session 53 fix: explicit schema for LLM
    )


def create_query_langfuse_telemetry_tool(
    user_id: str,
    session_id: Optional[str] = None,
    mcp_session_id: Optional[str] = None,
) -> StructuredTool:
    """Create context-aware QueryLangfuseTelemetry tool with auto-injected session context.

    Args:
        user_id: User UUID to auto-inject for authorization
        session_id: Main session/thread ID to auto-inject (optional)
        mcp_session_id: MCP session ID to auto-inject (optional)

    Returns:
        StructuredTool with session context automatically provided
    """

    async def query_langfuse_telemetry_wrapper(**kwargs) -> str:
        """Wrapper function for QueryLangfuseTelemetry with auto-injected session context."""
        from ..context_compaction_fork_mapping import resolve_root_session_id

        try:
            # Auto-inject user_id if not provided by agent
            if "user_id" not in kwargs:
                kwargs["user_id"] = user_id
                logger.debug(
                    f"[AUTO_INJECT] user_id={user_id} for query_langfuse_telemetry"
                )

            # Auto-inject session_id if not provided and we have it
            # Resolve to ROOT session ID so fork chain walk captures ALL forks
            if not kwargs.get("session_id") and session_id:
                root_id = resolve_root_session_id(session_id)
                kwargs["session_id"] = root_id
                # Force full fork chain visibility when auto-injecting session
                kwargs["include_fork_chain"] = True
                logger.debug(
                    f"[AUTO_INJECT] session_id={root_id} (root of {session_id}) "
                    f"include_fork_chain=True for query_langfuse_telemetry"
                )

            # Auto-inject mcp_session_id if not provided and we have it
            if not kwargs.get("mcp_session_id") and mcp_session_id:
                kwargs["mcp_session_id"] = mcp_session_id
                logger.debug(
                    f"[AUTO_INJECT] mcp_session_id={mcp_session_id} for query_langfuse_telemetry"
                )

            result = await QueryLangfuseTelemetry.execute(**kwargs)
            # Return JSON string for LLM consumption
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"QueryLangfuseTelemetry tool error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

    return StructuredTool.from_function(
        coroutine=query_langfuse_telemetry_wrapper,
        name=QueryLangfuseTelemetry.name,
        description=QueryLangfuseTelemetry.description,
        args_schema=QueryLangfuseTelemetryInput,  # Session 53 fix: explicit schema for LLM
    )


def create_export_session_data_tool(
    user_id: str,
    session_id: Optional[str] = None,
    mcp_session_id: Optional[str] = None,
) -> StructuredTool:
    """Create context-aware ExportSessionData tool with auto-injected context.

    Args:
        user_id: User UUID to auto-inject for authorization
        session_id: Session ID to auto-inject for default export (optional)
        mcp_session_id: MCP session ID for fallback session resolution (optional)

    Returns:
        StructuredTool with session context automatically provided
    """

    async def export_session_data_wrapper(**kwargs) -> str:
        """Wrapper function for ExportSessionData with auto-injected context."""
        try:
            # Auto-inject user_id if not provided by agent
            if "user_id" not in kwargs:
                kwargs["user_id"] = user_id
                logger.debug(f"[AUTO_INJECT] user_id={user_id} for export_session_data")

            # Auto-inject session_id if not provided and we have it
            if "session_id" not in kwargs and session_id:
                kwargs["session_id"] = session_id
                logger.debug(
                    f"[AUTO_INJECT] session_id={session_id} for export_session_data"
                )

            # Fallback: use mcp_session_id if session_id still not set
            if "session_id" not in kwargs and mcp_session_id:
                kwargs["session_id"] = mcp_session_id
                logger.debug(
                    f"[AUTO_INJECT] session_id={mcp_session_id} (from mcp_session_id) for export_session_data"
                )

            result = await ExportSessionData.execute(**kwargs)
            # Return JSON string for LLM consumption
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"ExportSessionData tool error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

    return StructuredTool.from_function(
        coroutine=export_session_data_wrapper,
        name=ExportSessionData.name,
        description=ExportSessionData.description,
    )


# Deprecated: Use create_export_session_data_tool() instead
def get_export_session_data_tool_langchain() -> StructuredTool:
    """Get ExportSessionData tool as LangChain StructuredTool.

    DEPRECATED: This function does not auto-inject user_id and session_id.
    Use create_export_session_data_tool() instead for proper context handling.
    """
    logger.warning(
        "get_export_session_data_tool_langchain() is deprecated. "
        "Use create_export_session_data_tool() instead."
    )

    async def export_session_data_wrapper(**kwargs) -> str:
        """Wrapper function for ExportSessionData."""
        try:
            result = await ExportSessionData.execute(**kwargs)
            # Return JSON string for LLM consumption
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"ExportSessionData tool error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

    return StructuredTool.from_function(
        coroutine=export_session_data_wrapper,
        name=ExportSessionData.name,
        description=ExportSessionData.description,
    )


def create_generate_presigned_url_tool(
    user_id: str,
    username: str,
    groups: Optional[List[str]] = None,
    request_context: Optional["RequestContext"] = None,
) -> StructuredTool:
    """Create LangChain StructuredTool wrapper for GeneratePresignedURL.

    Args:
        user_id: User UUID for authentication
        username: Username for audit logging
        groups: User groups for authorization
        request_context: HTTP request context for URL generation (optional)

    Returns:
        StructuredTool configured with user and request context
    """

    async def _execute_with_context(
        file_id: str,
        expiry_seconds: Optional[int] = 3600,
        disposition: Optional[str] = None,
    ) -> str:
        """Execute with injected user and request context."""
        # SESSION 48: Internal hostname detection for browser-accessible presigned URLs
        # List of internal Docker hostnames that should NOT be used for presigned URLs
        # (browser cannot resolve these, only Docker network can)
        INTERNAL_HOSTNAMES = {
            "agent_gateway",
            "orchestration_service",
            "mcp_server",
            "sandbox_mcp_server",
            "hpc_mcp_server",
            "gateway_registry",
        }

        base_url_override = None
        if request_context:
            # Build full base URL from request context (host + port + scheme)
            base_url = request_context.get_base_url()

            # Extract hostname from base URL
            parsed = urlparse(base_url)
            hostname = parsed.hostname or parsed.netloc.split(":")[0]

            # Only use request_context if hostname is NOT an internal Docker service
            if hostname not in INTERNAL_HOSTNAMES:
                base_url_override = base_url
                logger.debug(f"[PRESIGNED_URL] Using base URL from request context: {base_url_override}")
            else:
                logger.info(
                    f"[PRESIGNED_URL] Detected internal hostname '{hostname}', "
                    f"falling back to PUBLIC_BASE_URL for browser-accessible URLs"
                )

        result = await GeneratePresignedURL.execute(
            file_id=file_id,
            expiry_seconds=expiry_seconds,
            disposition=disposition,
            user_id=user_id,
            username=username,
            groups=groups or [],
            base_url_override=base_url_override,  # NEW: Pass full base URL
        )
        return json.dumps(result, indent=2)

    return StructuredTool(
        name=GeneratePresignedURL.name,
        description=GeneratePresignedURL.description,
        args_schema=GeneratePresignedURL.ArgsSchema,
        coroutine=_execute_with_context,
    )


def get_plotting_utility_tool_langchain() -> StructuredTool:
    """Get PlottingUtility tool as LangChain StructuredTool."""

    async def plotting_utility_wrapper(**kwargs) -> str:
        """Wrapper function for PlottingUtility."""
        try:
            result = await PlottingUtility.execute(**kwargs)
            # Return JSON string for LLM consumption
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"PlottingUtility tool error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

    return StructuredTool.from_function(
        coroutine=plotting_utility_wrapper,
        name=PlottingUtility.name,
        description=PlottingUtility.description,
        args_schema=PlottingUtility.ArgsSchema,
    )


def create_inspect_session_fork_chain_tool(
    user_id: str,
    session_id: Optional[str] = None,
    mcp_session_id: Optional[str] = None,
) -> StructuredTool:
    """Create context-aware InspectSessionForkChain tool with auto-injected context.

    Args:
        user_id: User UUID to auto-inject for authorization
        session_id: Session ID to auto-inject for default inspection (optional)
        mcp_session_id: MCP session ID for fallback session resolution (optional)

    Returns:
        StructuredTool with session context automatically provided
    """

    async def inspect_session_fork_chain_wrapper(**kwargs) -> str:
        """Wrapper function for InspectSessionForkChain with auto-injected context."""
        try:
            # Auto-inject user_id if not provided by agent
            if "user_id" not in kwargs:
                kwargs["user_id"] = user_id
                logger.debug(
                    f"[AUTO_INJECT] user_id={user_id} for inspect_session_fork_chain"
                )

            # Auto-inject session_id if not provided and we have it
            if not kwargs.get("session_id") and session_id:
                kwargs["session_id"] = session_id
                logger.debug(
                    f"[AUTO_INJECT] session_id={session_id} for inspect_session_fork_chain"
                )

            # Fallback: use mcp_session_id if session_id still not set
            if not kwargs.get("session_id") and mcp_session_id:
                kwargs["session_id"] = mcp_session_id
                logger.debug(
                    f"[AUTO_INJECT] session_id={mcp_session_id} (from mcp_session_id) for inspect_session_fork_chain"
                )

            result = await InspectSessionForkChain.execute(**kwargs)
            # Return JSON string for LLM consumption
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"InspectSessionForkChain tool error: {e}", exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

    return StructuredTool.from_function(
        coroutine=inspect_session_fork_chain_wrapper,
        name=InspectSessionForkChain.name,
        description=InspectSessionForkChain.description,
        args_schema=InspectSessionForkChainInput,
    )


def create_all_utility_tools(
    user_id: str,
    username: str,
    groups: Optional[List[str]] = None,
    include_observability: bool = True,
    request_context: Optional["RequestContext"] = None,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mcp_session_id: Optional[str] = None,
) -> List[StructuredTool]:
    """Create all utility MCP tools with user and session context.

    Args:
        user_id: User UUID
        username: Username
        groups: User groups
        include_observability: Whether to include telemetry/export tools
        request_context: HTTP request context for URL generation (optional)
        thread_id: Main session/thread ID for auto-injection (optional)
        session_id: Session ID for fallback thread_id (optional)
        mcp_session_id: MCP session ID for auto-injection (optional)

    Returns:
        List of LangChain StructuredTools with context auto-injection
    """
    tools = [
        create_query_user_sessions_tool(user_id, thread_id or session_id, mcp_session_id),
        create_get_session_history_tool(user_id, thread_id or session_id, mcp_session_id),
        create_query_checkpoints_tool(user_id, thread_id, session_id, mcp_session_id),
        create_inspect_session_fork_chain_tool(
            user_id, thread_id or session_id, mcp_session_id
        ),
        create_generate_presigned_url_tool(user_id, username, groups, request_context),
        get_plotting_utility_tool_langchain(),
    ]

    if include_observability:
        tools.extend(
            [
                create_query_langfuse_telemetry_tool(
                    user_id, thread_id or session_id, mcp_session_id
                ),
                create_export_session_data_tool(user_id, thread_id or session_id, mcp_session_id),
            ]
        )

    return tools
