"""
Telemetry enrichment utilities for session introspection tools.

Provides cross-reference capabilities between PostgreSQL session data
and Langfuse telemetry API (traces, tool calls, costs).

Supports fork-chain-aware enrichment for auto-compacted sessions.
"""

import os
from typing import Any, Dict, List, Optional

import requests

from ...logger_config import get_logger

logger = get_logger(__name__)


class LangfuseClient:
    """
    Simple Langfuse API client for telemetry data retrieval.

    Provides graceful fallback when Langfuse is unavailable or misconfigured.
    """

    def __init__(
        self,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        host: Optional[str] = None,
        timeout: int = 5,
    ):
        """
        Initialize Langfuse client.

        Args:
            public_key: Langfuse public API key (default: from LANGFUSE_PUBLIC_KEY env)
            secret_key: Langfuse secret API key (default: from LANGFUSE_SECRET_KEY env)
            host: Langfuse API host (default: from LANGFUSE_HOST env or https://cloud.langfuse.com)
            timeout: Request timeout in seconds (default: 5)
        """
        self.public_key = public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        self.secret_key = secret_key or os.getenv("LANGFUSE_SECRET_KEY")
        self.host = host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        self.timeout = timeout
        self.available = bool(self.public_key and self.secret_key)

        if not self.available:
            logger.warning(
                "Langfuse credentials not configured. Telemetry enrichment unavailable."
            )

    def get_traces_for_session(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """
        Get Langfuse traces for a specific session.

        Args:
            session_id: Session/thread ID
            user_id: User ID for filtering

        Returns:
            Dict with trace data or error information
        """
        if not self.available:
            return {
                "available": False,
                "error": "Langfuse credentials not configured",
            }

        try:
            # Langfuse API endpoint for traces
            url = f"{self.host}/api/public/traces"
            auth = (self.public_key, self.secret_key)

            # Query parameters
            params = {
                "userId": user_id,
                "name": session_id,  # Langfuse trace name often matches session_id
                "limit": 100,
            }

            response = requests.get(url, auth=auth, params=params, timeout=self.timeout)
            response.raise_for_status()

            traces_data = response.json()

            # Extract summary statistics
            traces = traces_data.get("data", [])
            total_traces = len(traces)
            total_tokens = sum(t.get("usage", {}).get("total", 0) for t in traces)
            total_cost = sum(t.get("calculatedTotalCost", 0) for t in traces)

            # Count tool calls across all traces
            tool_call_count = 0
            for trace in traces:
                observations = trace.get("observations", [])
                tool_call_count += sum(
                    1
                    for obs in observations
                    if obs.get("type") == "GENERATION"
                    and obs.get("name", "").startswith("tool_")
                )

            return {
                "available": True,
                "trace_count": total_traces,
                "tool_call_count": tool_call_count,
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 4) if total_cost else 0,
                "traces": traces[:5],  # Return first 5 traces for inspection
            }

        except requests.exceptions.Timeout:
            logger.warning(
                f"Langfuse API timeout for session {session_id} (user: {user_id})"
            )
            return {
                "available": False,
                "error": "Langfuse API timeout (>5s)",
            }
        except requests.exceptions.RequestException as e:
            logger.warning(
                f"Langfuse API error for session {session_id} (user: {user_id}): {e}"
            )
            return {
                "available": False,
                "error": f"Langfuse API error: {str(e)}",
            }
        except Exception as e:
            logger.error(
                f"Unexpected error querying Langfuse for session {session_id}: {e}"
            )
            return {
                "available": False,
                "error": f"Unexpected error: {str(e)}",
            }

    def get_traces_for_session_chain(
        self, session_ids: List[str], user_id: str
    ) -> Dict[str, Any]:
        """
        Get Langfuse traces across a chain of session IDs (fork chain).

        Queries each session_id and deduplicates by trace_id.

        Args:
            session_ids: Ordered list of session IDs in the fork chain.
            user_id: User ID for filtering.

        Returns:
            Aggregated dict with combined trace data from all sessions.
        """
        if not self.available:
            return {
                "available": False,
                "error": "Langfuse credentials not configured",
            }

        all_traces: List[Dict[str, Any]] = []
        seen_trace_ids: set = set()
        total_tokens = 0
        total_cost = 0.0
        total_tool_calls = 0

        for sid in session_ids:
            result = self.get_traces_for_session(sid, user_id)
            if not result.get("available"):
                continue

            total_tokens += result.get("total_tokens", 0)
            total_cost += result.get("total_cost_usd", 0)
            total_tool_calls += result.get("tool_call_count", 0)

            # Deduplicate traces by trace_id
            for trace in result.get("traces", []):
                trace_id = trace.get("id")
                if trace_id and trace_id not in seen_trace_ids:
                    seen_trace_ids.add(trace_id)
                    all_traces.append(trace)

        return {
            "available": True,
            "trace_count": len(all_traces),
            "tool_call_count": total_tool_calls,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4) if total_cost else 0,
            "sessions_queried": session_ids,
            "traces": all_traces[:10],  # Return first 10 traces across chain
        }


async def enrich_sessions_with_telemetry(
    sessions: List[Dict[str, Any]],
    user_id: str,
    langfuse_client: Optional[LangfuseClient] = None,
    follow_fork_chains: bool = False,
) -> List[Dict[str, Any]]:
    """
    Enrich session metadata with Langfuse telemetry data.

    Adds telemetry field to each session with:
    - trace_count: Number of Langfuse traces
    - tool_call_count: Number of tool calls
    - total_tokens: Token usage
    - total_cost_usd: Estimated cost

    Args:
        sessions: List of session dictionaries from PostgreSQL
        user_id: User ID for filtering Langfuse data
        langfuse_client: Optional LangfuseClient instance (creates one if None)
        follow_fork_chains: Resolve fork chains before querying Langfuse (default False)

    Returns:
        Enriched sessions list (original sessions + telemetry field)
    """
    # Create client if not provided
    if langfuse_client is None:
        langfuse_client = LangfuseClient()

    # Check if Langfuse is available
    if not langfuse_client.available:
        logger.warning("Langfuse unavailable, skipping telemetry enrichment")
        for session in sessions:
            session["telemetry"] = {
                "available": False,
                "error": "Langfuse credentials not configured",
            }
        return sessions

    # Enrich each session with telemetry data
    enriched_sessions = []
    for session in sessions:
        session_id = session.get("session_id") or session.get("thread_id")
        if not session_id:
            logger.warning(f"Session missing session_id/thread_id: {session}")
            session["telemetry"] = {
                "available": False,
                "error": "Session ID not found",
            }
            enriched_sessions.append(session)
            continue

        # If follow_fork_chains is enabled, resolve chain and query across all sessions
        if follow_fork_chains:
            try:
                from agentic_framework_pkg.orchestration_service.context_compaction_fork_mapping import (
                    get_fork_chain_session_ids,
                )

                chain_ids = await get_fork_chain_session_ids(session_id)
                if len(chain_ids) > 1:
                    telemetry_data = langfuse_client.get_traces_for_session_chain(
                        chain_ids, user_id
                    )
                else:
                    telemetry_data = langfuse_client.get_traces_for_session(
                        session_id, user_id
                    )
            except Exception as e:
                logger.debug(
                    f"Fork chain resolution failed for {session_id}, "
                    f"falling back to single session query: {e}"
                )
                telemetry_data = langfuse_client.get_traces_for_session(
                    session_id, user_id
                )
        else:
            # Query Langfuse for this session only
            telemetry_data = langfuse_client.get_traces_for_session(session_id, user_id)

        session["telemetry"] = telemetry_data
        enriched_sessions.append(session)

    return enriched_sessions


def merge_session_telemetry_summary(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create aggregate summary of telemetry data across all sessions.

    Args:
        sessions: List of sessions with telemetry data

    Returns:
        Summary dict with aggregated telemetry statistics
    """
    total_traces = 0
    total_tool_calls = 0
    total_tokens = 0
    total_cost_usd = 0.0
    sessions_with_telemetry = 0

    for session in sessions:
        telemetry = session.get("telemetry", {})
        if telemetry.get("available"):
            sessions_with_telemetry += 1
            total_traces += telemetry.get("trace_count", 0)
            total_tool_calls += telemetry.get("tool_call_count", 0)
            total_tokens += telemetry.get("total_tokens", 0)
            total_cost_usd += telemetry.get("total_cost_usd", 0)

    return {
        "sessions_with_telemetry": sessions_with_telemetry,
        "total_sessions": len(sessions),
        "total_traces": total_traces,
        "total_tool_calls": total_tool_calls,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost_usd, 4),
    }
