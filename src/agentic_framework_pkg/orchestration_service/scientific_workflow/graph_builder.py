"""
This module provides the `AgentGraphBuilder` class, which is responsible for
constructing the custom LangGraph `StateGraph` for the `ScientificWorkflowAgent`.

Architectural Role:
-   **Graph Construction:** Encapsulates the logic for defining the nodes
    (agent, action) and edges (conditional logic) of the agent's workflow.
-   **Decoupling:** It decouples the agent's core logic (`ScientificWorkflowAgent`)
    from the specific implementation details of the LangGraph, making both
    components easier to maintain and modify.
-   **Split-Stream Implementation:** This is where the "split-stream" strategy for
    handling large tool outputs is implemented. The `_custom_tool_node` method
    is the key component that intercepts tool outputs, sanitizes them before
    they are sent back to the LLM, and stores the full, raw output in the
    agent's state. This prevents large data (like plot images) from consuming
    the LLM's limited context window.
"""

import hashlib
import json
import os
import re
import uuid
import time
from collections import Counter
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, StateGraph

from ...logger_config import get_logger
from .agent_state import AgentState
from ..context_manager import ContextManager
from ..tool_execution import (
    ToolExecutionFactory,
    ToolExecutionContext,
    AsyncTaskManagerExecutor,
)
from .streaming_tool_executor import StreamingToolExecutor

if TYPE_CHECKING:
    from .langchain_agent import ScientificWorkflowAgent

logger = get_logger(__name__)


def _extract_errors_for_tool(messages, tool_name: str) -> list:
    """
    Extract error messages from ToolMessages that correspond to a specific tool.

    Walks the message list and finds ToolMessages that follow AIMessages
    containing tool_calls for the given tool_name. Returns error strings
    found in those ToolMessages.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    errors = []
    # Build a set of tool_call_ids for the target tool
    target_call_ids = set()
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tc_name == tool_name and tc_id:
                    target_call_ids.add(tc_id)

    # Find ToolMessages matching those call IDs that contain errors
    for msg in messages:
        if isinstance(msg, ToolMessage) and getattr(msg, "tool_call_id", None) in target_call_ids:
            try:
                content = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                if isinstance(content, dict):
                    if content.get("status") == "error" or "error" in content:
                        error_info = content.get("error") or content.get("message", "Unknown error")
                        errors.append(str(error_info)[:200])
            except (json.JSONDecodeError, TypeError):
                if isinstance(msg.content, str) and (
                    "error" in msg.content.lower() or "failed" in msg.content.lower()
                ):
                    errors.append(msg.content[:200])

    return errors


class AgentGraphBuilder:
    """
    Builds the custom LangGraph StateGraph for the ScientificWorkflowAgent.
    """

    def __init__(
        self,
        llm,
        tools: List[Any],
        agent_instance: Optional["ScientificWorkflowAgent"] = None,
        db_connection_string: Optional[str] = None,
        context_manager: Optional[ContextManager] = None,
    ):
        """
        Initializes the graph builder.

        Args:
            llm: The LangChain LLM instance to be used by the agent node.
            tools: A list of LangChain Tool objects available to the action node.
            agent_instance: Optional reference to parent agent for context access.
            db_connection_string: PostgreSQL connection string for async task execution.
            context_manager: Optional ContextManager for context truncation during agent invocation.
        """
        self.llm = llm
        self.tools = tools
        self.agent_instance = agent_instance
        self.context_manager = context_manager

        # Initialize tool execution factory for async task management
        self.tool_factory = ToolExecutionFactory()

        # Initialize streaming tool executor for tools that support streaming
        # This enables optional mid-stream file redirection for large outputs
        self.streaming_executor = None  # Initialized on first use with session context

        # Get database connection string (fallback to default if not provided)
        db_conn_str = db_connection_string or os.getenv(
            "DATABASE_URL",
            "postgresql://admin:password@postgres:5432/agentic_orchestrator",
        )

        # Read wait_for_completion configuration from environment
        # Default: False (asynchronous mode with enhanced ToolMessage format)
        # Prevents UI blocking during long-running tasks (5-10 min ExecuteApprovedPlan)
        # Set to "true" to enable synchronous mode (waits for actual results)
        wait_for_completion = (
            os.getenv("TOOL_EXECUTION_WAIT_FOR_COMPLETION", "false").lower() == "true"
        )

        # Read user overrides for specific tools
        # Allows forcing specific tools to execute synchronously via environment variable
        # Format: Comma-separated list of tool names
        # Example: TOOL_EXECUTION_SYNC_OVERRIDES="video_processing_tool,gitxray_tool"
        user_override_str = os.getenv("TOOL_EXECUTION_SYNC_OVERRIDES", "")
        user_overrides = set(tool.strip() for tool in user_override_str.split(",") if tool.strip())

        if user_overrides:
            logger.info(f"[TOOL_CLASSIFICATION] User overrides loaded: {user_overrides}")

        # Register AsyncTaskManagerExecutor as default
        # Supports both synchronous (default) and asynchronous execution modes
        # Tool classification system:
        # - Tier 1: SYNCHRONOUS_TOOLS whitelist (planning + RAG tools, always sync)
        # - Tier 2: user_overrides (configurable via TOOL_EXECUTION_SYNC_OVERRIDES)
        # - Tier 3: All other tools (asynchronous by default)
        self.tool_factory.register_strategy(
            AsyncTaskManagerExecutor(
                db_conn_str,
                retention_days=30,
                wait_for_completion=wait_for_completion,
                user_overrides=user_overrides
            ),
            is_default=True,
        )

        execution_mode = (
            "synchronous (wait for completion)"
            if wait_for_completion
            else "asynchronous (background execution)"
        )
        logger.info(
            f"ToolExecutionFactory initialized with AsyncTaskManagerExecutor "
            f"in {execution_mode} mode, {len(user_overrides)} user override(s)"
        )

    async def call_model(self, state: AgentState) -> dict:
        """
        The "agent" node. It invokes the LLM with the current message history
        to decide the next step (either call a tool or finish).

        Dynamically binds tools to the LLM for each invocation to support
        runtime tool changes and user-specific tool authorization.

        Args:
            state: Current agent state with messages and metadata
        """
        messages = list(state["messages"])  # Create a mutable copy

        # Apply context truncation before LLM invocation (if enabled)
        # Use agent_instance's context_manager if available (allows dynamic reconfiguration)
        context_manager = (
            self.agent_instance.context_manager
            if self.agent_instance
            else self.context_manager
        )
        new_session_id = None
        already_forked = state.get("forked_session_id")
        if context_manager and context_manager.enabled:
            if already_forked:
                # Skip prepare_context if a fork already occurred in this graph run.
                # Without this guard, each call_model() invocation (one per LLM turn
                # after tool calls) would re-fork from the same parent, creating
                # orphan sub-sessions that waste checkpoint storage.
                logger.info(
                    f"[CONTEXT_TRUNCATION] Skipping prepare_context — fork already occurred "
                    f"in this graph run: {already_forked}"
                )
            else:
                original_count = len(messages)
                # Get thread_id from agent_instance if available (Phase 3A: required for forking)
                thread_id = self.agent_instance.thread_id_override if self.agent_instance else None
                # Phase 3B Fix: Pass available tools so fork detection includes tool schema tokens
                messages, new_session_id, metadata = await context_manager.prepare_context(
                    messages, thread_id=thread_id, available_tools=self.tools
                )
                logger.info(
                    f"[CONTEXT_TRUNCATION] Context prepared: {original_count} -> {len(messages)} messages, "
                    f"fork={new_session_id is not None}"
                )

            # If fork occurred, update state with new session ID
            if new_session_id:
                logger.info(
                    f"[SUB_SESSION_FORK] Session forked: {thread_id} -> {new_session_id}, "
                    f"generation={metadata.session_lineage.generation}"
                )
                # Store new session ID in state for caller to handle
                # Note: Actual thread_id update happens at higher layer (responses.py, runs.py)
                state["forked_session_id"] = new_session_id
                state["fork_metadata"] = {
                    "parent_session_id": metadata.session_lineage.parent_session_id,
                    "generation": metadata.session_lineage.generation,
                    "fork_reason": metadata.session_lineage.fork_reason.value,
                    "bootstrap_message_count": metadata.session_lineage.bootstrap_message_count,
                }

                # Persist fork mapping in Redis so subsequent requests on
                # the parent thread_id are transparently routed to this
                # sub-session (prevents fork loop on next request).
                from ..context_compaction_fork_mapping import persist_fork_mapping

                await persist_fork_mapping(
                    parent_id=thread_id,
                    child_id=new_session_id,
                    generation=metadata.session_lineage.generation,
                    fork_reason=metadata.session_lineage.fork_reason.value,
                )

        # PHASE 1 DIAGNOSTIC: Log agent state before processing
        logger.warning(f"[RECURSION_DEBUG] call_model() invoked with {len(messages)} messages")
        if messages:
            last_msg_type = type(messages[-1]).__name__
            logger.warning(f"[RECURSION_DEBUG] Last message type: {last_msg_type}")
            if hasattr(messages[-1], "tool_calls"):
                tool_calls = messages[-1].tool_calls if messages[-1].tool_calls else []
                logger.warning(f"[RECURSION_DEBUG] Last message has {len(tool_calls)} tool_calls")
                if tool_calls:
                    tool_names = [tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None) for tc in tool_calls]
                    logger.warning(f"[RECURSION_DEBUG] Tool names: {tool_names}")
            if hasattr(messages[-1], "content"):
                content_preview = str(messages[-1].content)[:200]
                logger.warning(f"[RECURSION_DEBUG] Last message content preview: {content_preview}")

        # CRITICAL FIX: Position-aware orphaned tool_calls repair
        # This fix addresses position shifting between call_model() invocations
        # Problem: Synthetic ToolMessages get separated from AIMessages by intervening messages
        # Solution: Detect mispositioned ToolMessages and re-insert at correct positions

        # Position-aware detection: Check if ToolMessages are immediately after AIMessages
        problematic_tool_calls = []  # List of (ai_message_index, tool_call_id) tuples
        mispositioned_tool_call_ids = set()

        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                # Extract expected tool_call_ids from this AIMessage
                expected_tool_call_ids = []
                for tc in msg.tool_calls:
                    tc_id = tc.id if hasattr(tc, "id") else tc.get("id") if isinstance(tc, dict) else None
                    if tc_id:
                        expected_tool_call_ids.append(tc_id)

                if not expected_tool_call_ids:
                    continue

                # Check if NEXT messages are ToolMessages for these tool_calls
                next_pos = i + 1
                found_tool_call_ids = set()

                # Look ahead to find ToolMessages that should be immediately after
                while next_pos < len(messages) and isinstance(messages[next_pos], ToolMessage):
                    if messages[next_pos].tool_call_id in expected_tool_call_ids:
                        found_tool_call_ids.add(messages[next_pos].tool_call_id)
                    next_pos += 1

                # Identify missing or mispositioned tool_calls
                for tc_id in expected_tool_call_ids:
                    if tc_id not in found_tool_call_ids:
                        problematic_tool_calls.append((i, tc_id))
                        mispositioned_tool_call_ids.add(tc_id)

        # If we found problematic tool_calls, repair them
        if problematic_tool_calls:
            logger.warning(
                f"[ORPHANED_TOOL_CALLS_FIX] Detected {len(problematic_tool_calls)} orphaned/mispositioned tool_calls"
            )

            # Step 1: Remove any mispositioned ToolMessages from the list
            # These exist elsewhere but not immediately after their AIMessages
            messages_to_keep = []
            for msg in messages:
                if isinstance(msg, ToolMessage) and msg.tool_call_id in mispositioned_tool_call_ids:
                    logger.info(
                        f"[ORPHANED_TOOL_CALLS_FIX] Removing mispositioned ToolMessage for: {msg.tool_call_id}"
                    )
                else:
                    messages_to_keep.append(msg)
            messages = messages_to_keep

            # Step 2: Create synthetic ToolMessages for all problematic tool_calls
            # CRITICAL: Synthetic ToolMessages must include:
            # - name: Explicit tool identifier for OpenAI format
            # - additional_kwargs={"role": "tool"}: LangChain ToolMessage has type='tool'
            #   but lacks role attribute. OpenAI requires BOTH type and role.
            synthetic_by_id = {}
            for _, tc_id in problematic_tool_calls:
                logger.info(
                    f"[ORPHANED_TOOL_CALLS_FIX] Creating synthetic ToolMessage for: {tc_id}"
                )
                synthetic_by_id[tc_id] = ToolMessage(
                    content=json.dumps(
                        {
                            "status": "error",
                            "message": "Tool call response missing due to checkpoint restoration. This is a recovery ToolMessage to maintain OpenAI API compliance.",
                            "error_type": "checkpoint_restoration_error",
                            "tool_call_id": tc_id,
                        }
                    ),
                    tool_call_id=tc_id,
                    name="checkpoint_restoration_recovery",
                    additional_kwargs={"role": "tool"},
                )

            # Step 3: Insert synthetic ToolMessages at correct positions
            # Group by AIMessage index and insert immediately after each AIMessage
            # Process in reverse order to preserve indices
            ai_index_to_tool_call_ids = {}
            for ai_idx, tc_id in problematic_tool_calls:
                if ai_idx not in ai_index_to_tool_call_ids:
                    ai_index_to_tool_call_ids[ai_idx] = []
                ai_index_to_tool_call_ids[ai_idx].append(tc_id)

            for ai_idx in sorted(ai_index_to_tool_call_ids.keys(), reverse=True):
                tc_ids = ai_index_to_tool_call_ids[ai_idx]
                insert_pos = ai_idx + 1
                for tc_id in tc_ids:
                    messages.insert(insert_pos, synthetic_by_id[tc_id])
                    logger.info(
                        f"[ORPHANED_TOOL_CALLS_FIX] Inserted synthetic ToolMessage at position {insert_pos} for: {tc_id}"
                    )

        # Dynamically bind tools to LLM for this invocation
        llm_with_tools = self.llm.bind_tools(self.tools) if self.tools else self.llm

        response = await llm_with_tools.ainvoke(messages)

        # PHASE 1 DIAGNOSTIC: Log LLM response
        logger.warning(f"[RECURSION_DEBUG] LLM response received, type: {type(response).__name__}")
        if hasattr(response, "tool_calls"):
            tool_calls = response.tool_calls if response.tool_calls else []
            logger.warning(f"[RECURSION_DEBUG] LLM wants to call {len(tool_calls)} tools")
            if tool_calls:
                tool_names = [tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None) for tc in tool_calls]
                logger.warning(f"[RECURSION_DEBUG] LLM requested tools: {tool_names}")
        if hasattr(response, "content"):
            content_preview = str(response.content)[:200]
            logger.warning(f"[RECURSION_DEBUG] LLM response content preview: {content_preview}")

        # CRITICAL FIX: Return only the response
        # Synthetic messages are already in the messages list that was sent to LLM
        # Returning them separately causes position shifting when LangGraph appends to state
        result = {"messages": [response]}

        # Phase 3A + P3 fix: Preserve fork metadata across call_model() invocations
        if new_session_id:
            # Fork occurred in this invocation — include metadata
            result["forked_session_id"] = new_session_id
            result["fork_metadata"] = state.get("fork_metadata")
        elif already_forked:
            # Fork occurred in an earlier invocation within this graph run —
            # preserve it so subsequent invocations don't clear the fork state
            # and trigger another fork.
            result["forked_session_id"] = already_forked
            result["fork_metadata"] = state.get("fork_metadata")
        else:
            # No fork in this graph run
            result["forked_session_id"] = None
            result["fork_metadata"] = None

        return result

    @staticmethod
    def _analyze_recent_tool_repetitions(messages, window: int = 10) -> dict:
        """
        Analyze recent messages for repeated tool calls.

        Returns a dict with:
        - tool_name: The most-repeated tool name (or None)
        - repeat_count: How many times it appeared
        - all_repeated_tools: Counter of all tool names in the window
        - recent_errors: List of error strings from ToolMessages
        - detection_type: "identical_args" | "same_name_with_errors" | None
        - has_identical_args: Whether any (name, args_hash) pair repeats >= 3 times
        - identical_tool_name: Tool name for the identical-args detection (if any)

        This helper is used by both should_continue() and termination_node()
        to avoid reliance on LangGraph state propagation from routing functions.
        """
        from langchain_core.messages import AIMessage, ToolMessage

        recent = messages[-window:] if len(messages) > window else messages

        # Collect (tool_name, args_hash) tuples and name-only list
        tool_call_tuples = []  # (tool_name, args_hash)
        for msg in recent:
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                    if tool_name:
                        args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                        args_hash = hashlib.md5(
                            json.dumps(args, sort_keys=True, default=str).encode()
                        ).hexdigest()[:8]
                        tool_call_tuples.append((tool_name, args_hash))

        if not tool_call_tuples:
            return {
                "tool_name": None,
                "repeat_count": 0,
                "all_repeated_tools": Counter(),
                "recent_errors": [],
                "detection_type": None,
                "has_identical_args": False,
                "identical_tool_name": None,
            }

        # Count by (name, args_hash) — identical calls
        hash_counts = Counter(tool_call_tuples)
        max_identical = max(hash_counts.values()) if hash_counts else 0

        # Count by name only
        name_counts = Counter(name for name, _ in tool_call_tuples)

        # Extract errors from ToolMessages
        recent_errors = []
        for msg in recent:
            if isinstance(msg, ToolMessage):
                try:
                    content = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                    if isinstance(content, dict):
                        if content.get("status") == "error" or "error" in content:
                            error_info = content.get("error") or content.get("message", "Unknown error")
                            recent_errors.append(str(error_info)[:200])
                except (json.JSONDecodeError, TypeError):
                    if isinstance(msg.content, str) and (
                        "error" in msg.content.lower() or "failed" in msg.content.lower()
                    ):
                        recent_errors.append(msg.content[:200])

        # Determine detection type
        detection_type = None
        detected_tool = None
        detected_count = 0
        has_identical = max_identical >= 3
        identical_tool = None

        if has_identical:
            # True stuck loop: same tool + same args >= 3 times
            most_repeated_tuple = max(hash_counts, key=hash_counts.get)
            identical_tool = most_repeated_tuple[0]
            detected_tool = identical_tool
            detected_count = max_identical
            detection_type = "identical_args"
        else:
            # Check name-only repetition
            max_name_repeated = max(name_counts.values()) if name_counts else 0
            if max_name_repeated >= 3:
                most_repeated_name = max(name_counts, key=name_counts.get)
                # Only flag if there are errors — otherwise it's productive work
                tool_errors = _extract_errors_for_tool(recent, most_repeated_name)
                if tool_errors:
                    detected_tool = most_repeated_name
                    detected_count = max_name_repeated
                    detection_type = "same_name_with_errors"
                    recent_errors = tool_errors  # Use tool-specific errors

        return {
            "tool_name": detected_tool,
            "repeat_count": detected_count or (max(name_counts.values()) if name_counts else 0),
            "all_repeated_tools": name_counts,
            "recent_errors": recent_errors[:3],
            "detection_type": detection_type,
            "has_identical_args": has_identical,
            "identical_tool_name": identical_tool,
        }

    def should_continue(self, state: AgentState) -> str:
        """
        The conditional edge. It checks the last message from the LLM to decide
        whether to continue to the "action" node or "end" the workflow.

        Dual-criteria loop detection (Session 57):
        1. Identical calls (same name + same args) >= 3 times -> terminate (true stuck loop)
        2. Same name, different args >= 3 times -> terminate ONLY if errors present
           (if all succeed, it's productive iterative work -> continue)
        """
        from langchain_core.messages import AIMessage, ToolMessage

        # PHASE 1 DIAGNOSTIC: Log routing decision entry
        logger.warning(f"[RECURSION_DEBUG] should_continue() called with {len(state['messages'])} messages")

        # DEFENSIVE: Detect repeated tool calls (infinite loop prevention)
        if len(state["messages"]) > 10:
            analysis = self._analyze_recent_tool_repetitions(state["messages"])

            if analysis["detection_type"] == "identical_args":
                # True stuck loop: same tool + identical args >= 3 times
                tool_name = analysis["identical_tool_name"]
                repeat_count = analysis["repeat_count"]
                logger.warning(
                    f"[RECURSION_TERMINATION] Identical tool calls detected: "
                    f"{tool_name} called {repeat_count}x with same args. "
                    f"All repeated tools: {dict(analysis['all_repeated_tools'])}. "
                    f"Terminating to prevent infinite loop."
                )

                # Store termination context (may not persist via LangGraph routing,
                # but termination_node() will re-analyze if needed — see Bug 2 fix)
                state["termination_reason"] = {
                    "tool_name": tool_name,
                    "repeat_count": repeat_count,
                    "all_repeated_tools": analysis["all_repeated_tools"],
                    "recent_errors": analysis["recent_errors"],
                    "detection_type": "identical_args",
                }

                logger.info(
                    f"[RECURSION_TERMINATION] Set termination_reason in state: "
                    f"tool_name={tool_name}, repeat_count={repeat_count}, "
                    f"all_repeated_tools={dict(analysis['all_repeated_tools'])}, "
                    f"recent_errors_count={len(analysis['recent_errors'])}"
                )

                return "terminate"

            elif analysis["detection_type"] == "same_name_with_errors":
                # Same tool name repeated but with different args AND errors present
                tool_name = analysis["tool_name"]
                repeat_count = analysis["repeat_count"]
                logger.warning(
                    f"[RECURSION_TERMINATION] Repeated tool with errors: "
                    f"{tool_name} called {repeat_count}x with different args but errors detected. "
                    f"All repeated tools: {dict(analysis['all_repeated_tools'])}. "
                    f"Terminating due to unresolvable errors."
                )

                state["termination_reason"] = {
                    "tool_name": tool_name,
                    "repeat_count": repeat_count,
                    "all_repeated_tools": analysis["all_repeated_tools"],
                    "recent_errors": analysis["recent_errors"],
                    "detection_type": "same_name_with_errors",
                }

                logger.info(
                    f"[RECURSION_TERMINATION] Set termination_reason in state: "
                    f"tool_name={tool_name}, repeat_count={repeat_count}, "
                    f"all_repeated_tools={dict(analysis['all_repeated_tools'])}, "
                    f"recent_errors_count={len(analysis['recent_errors'])}"
                )

                return "terminate"

            else:
                # No detection triggered — may be same name with different args and no errors
                # (productive iterative work like ExecuteCode with different code, all succeeding)
                max_name = max(analysis["all_repeated_tools"].values()) if analysis["all_repeated_tools"] else 0
                if max_name >= 3:
                    most_repeated_name = max(analysis["all_repeated_tools"], key=analysis["all_repeated_tools"].get)
                    logger.info(
                        f"[RECURSION_DEBUG] {most_repeated_name} called {max_name}x "
                        f"with different args and no errors — allowing continuation"
                    )

        last_message = state["messages"][-1]
        last_msg_type = type(last_message).__name__
        logger.warning(f"[RECURSION_DEBUG] Last message for routing decision: {last_msg_type}")

        # If last message is a ToolMessage (e.g., from checkpoint repair),
        # look for the previous AI message to check for pending tool calls
        if isinstance(last_message, ToolMessage):
            logger.warning(f"[RECURSION_DEBUG] Last message is ToolMessage, checking for pending tool calls")
            # Find the last AI message with tool_calls
            for msg in reversed(state["messages"][:-1]):
                if hasattr(msg, "tool_calls"):
                    # Check if all tool calls have been handled
                    # by comparing with existing ToolMessages
                    pending_calls = self._get_pending_tool_calls(state["messages"])
                    if pending_calls:
                        logger.warning(f"[RECURSION_DEBUG] Found {len(pending_calls)} pending calls, routing to: continue")
                        return "continue"
                    break
            logger.warning(f"[RECURSION_DEBUG] No pending calls, routing to: end")
            return "end"

        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            logger.warning(f"[RECURSION_DEBUG] Last message has no tool_calls, routing to: end")
            return "end"

        # Log tool_calls before continuing
        tool_calls = last_message.tool_calls if last_message.tool_calls else []
        tool_names = [tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None) for tc in tool_calls]
        logger.warning(f"[RECURSION_DEBUG] Last message has {len(tool_calls)} tool_calls {tool_names}, routing to: continue")
        return "continue"

    def _get_pending_tool_calls(self, messages: List[Any]) -> List[str]:
        """
        Check for pending tool calls that haven't been responded to.

        Returns list of tool_call_ids that have not yet received ToolMessage responses.
        """
        from langchain_core.messages import AIMessage, ToolMessage

        # DEBUG: Log all messages being analyzed
        logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] Analyzing {len(messages)} messages for orphaned tool_calls")

        # Find all tool_call_ids that have been requested
        requested_tool_call_ids = set()
        for i, msg in enumerate(messages):
            msg_type = type(msg).__name__

            # DEBUG: Log each message type
            logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] Message[{i}]: {msg_type}")

            if isinstance(msg, AIMessage):
                has_tool_calls = hasattr(msg, "tool_calls")
                logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] AIMessage[{i}] has tool_calls attribute: {has_tool_calls}")

                if has_tool_calls:
                    tool_calls_value = msg.tool_calls
                    logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] AIMessage[{i}] tool_calls value: {tool_calls_value}")
                    logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] AIMessage[{i}] tool_calls type: {type(tool_calls_value)}")

                    for tc in tool_calls_value:
                        tc_type = type(tc).__name__
                        has_id = hasattr(tc, "id") if not isinstance(tc, dict) else "id" in tc
                        logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] tool_call type={tc_type}, has_id={has_id}")

                        if hasattr(tc, "id"):
                            tc_id = tc.id
                            logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] Found tool_call_id via attribute: {tc_id}")
                            requested_tool_call_ids.add(tc_id)
                        elif isinstance(tc, dict) and "id" in tc:
                            tc_id = tc["id"]
                            logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] Found tool_call_id via dict: {tc_id}")
                            requested_tool_call_ids.add(tc_id)
                        else:
                            logger.error(f"[ORPHANED_TOOL_CALLS_DEBUG] tool_call has NO ID: {tc}")

        logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] Total requested tool_call_ids: {requested_tool_call_ids}")

        # Find all tool_call_ids that have been responded to
        responded_tool_call_ids = set()
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                has_tool_call_id = hasattr(msg, "tool_call_id")
                logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] ToolMessage[{i}] has tool_call_id attribute: {has_tool_call_id}")

                if has_tool_call_id:
                    tc_id = msg.tool_call_id
                    logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] ToolMessage[{i}] tool_call_id: {tc_id}")
                    responded_tool_call_ids.add(tc_id)

        logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] Total responded tool_call_ids: {responded_tool_call_ids}")

        # Return pending tool calls (requested but not responded)
        pending = list(requested_tool_call_ids - responded_tool_call_ids)
        logger.warning(f"[ORPHANED_TOOL_CALLS_DEBUG] Pending (orphaned) tool_call_ids: {pending}")

        return pending

    async def _sanitize_tool_output(self, output: Dict[str, Any], tool_name: str = "unknown") -> Dict[str, Any]:
        """
        Sanitizes tool output to prevent large data from filling the LLM's context.

        This method implements a three-tier routing strategy based on output size:
        - SMALL (<5k chars): Include fully in context
        - MEDIUM (5k-50k chars): Truncate but include summary
        - LARGE (>50k chars): Exclude from context, save to ephemeral file

        It also handles plot sanitization to remove base64 data.
        """
        import os

        # Three-tier thresholds (Session 93 fix: lowered from 5MB/20MB which caused 305K token overflow)
        SMALL_THRESHOLD = int(os.getenv("TOOL_OUTPUT_SMALL_THRESHOLD", "5000"))        # ~1,250 tokens — include fully
        MEDIUM_THRESHOLD = int(os.getenv("TOOL_OUTPUT_MEDIUM_THRESHOLD", "200000"))    # ~50,000 tokens — truncate with head+tail
        LARGE_THRESHOLD = int(os.getenv("TOOL_OUTPUT_LARGE_THRESHOLD", "1000000"))     # ~250,000 tokens — redirect to ephemeral file

        # Handle plot sanitization (existing functionality)
        if (
            isinstance(output, dict)
            and "plots" in output
            and isinstance(output["plots"], list)
        ):
            logger.debug(f"[PLOT_SANITIZE] Processing {len(output['plots'])} plots from tool '{tool_name}'")
            sanitized_plots = []
            for plot in output["plots"]:
                # DEBUG: Log what fields are actually present
                plot_keys = list(plot.keys()) if isinstance(plot, dict) else []
                logger.debug(f"[PLOT_SANITIZE] Plot keys present: {plot_keys}")
                logger.debug(f"[PLOT_SANITIZE] Has content_base64: {'content_base64' in plot if isinstance(plot, dict) else False}")

                if isinstance(plot, dict) and "content_base64" in plot:
                    sanitized_plot = plot.copy()
                    base64_data = plot["content_base64"]
                    base64_size = len(base64_data)

                    # PHASE 4 ENHANCEMENT: Save base64 to ephemeral storage
                    plot_file_id = None
                    if base64_size > 1000:  # Only save non-trivial plots
                        try:
                            from ..routers.v1.files import register_ephemeral_tool_output
                            from datetime import datetime

                            # Save base64 data as ephemeral file
                            plot_file_id = await register_ephemeral_tool_output(
                                tool_name=f"{tool_name}_plot",
                                content=base64_data,  # Store base64 as-is
                                session_id=self.agent_instance.mcp_session_id,
                                owner_id=self.user_context.get("user_id") if self.user_context else None,
                            )

                            logger.info(
                                f"[PLOT_EPHEMERAL] Saved {base64_size:,} char plot to {plot_file_id}"
                            )
                        except Exception as e:
                            logger.warning(f"[PLOT_EPHEMERAL] Save failed: {e}")
                            # Continue with sanitization even if save fails

                    # Remove base64 but preserve access information
                    sanitized_plot["content_base64"] = (
                        f"<{plot.get('format', 'image').upper()} data omitted - {base64_size:,} chars>"
                    )

                    # PROVENANCE TRACKING: Add comprehensive metadata
                    if plot_file_id:
                        sanitized_plot["file_id"] = plot_file_id
                        sanitized_plot["provenance"] = {
                            "source": "sandbox_code_execution",
                            "tool_name": tool_name,
                            "session_id": self.agent_instance.mcp_session_id,
                            "owner_id": self.user_context.get("user_id") if self.user_context else None,
                            "storage_tier": "ephemeral",
                            "ttl_days": 7,
                            "generated_at": datetime.now().isoformat(),
                            "original_size_chars": base64_size,
                            "artifact_type": "plot",
                            "original_format": plot.get("format", "png"),
                        }
                        sanitized_plot["access_info"] = (
                            f"Plot saved to: {plot_file_id}\n"
                            f"Use ReadFile('{plot_file_id}') or GeneratePresignedURL('{plot_file_id}') to access"
                        )

                    # Preserve existing metadata
                    if "plot_url" in plot:
                        if "access_info" in sanitized_plot:
                            sanitized_plot["access_info"] += f"\nDirect URL: {plot['plot_url']}"
                        else:
                            sanitized_plot["access_info"] = f"Plot available at: {plot['plot_url']}"
                    if "relative_path" in plot:
                        sanitized_plot["file_location"] = f"Saved to: {plot['relative_path']}"
                    if "filename" in plot:
                        sanitized_plot["display_instruction"] = (
                            f"Use filename '{plot['filename']}' to reference this plot in responses"
                        )

                    sanitized_plots.append(sanitized_plot)
                else:
                    sanitized_plots.append(plot)
            output["plots"] = sanitized_plots

        # Base64 image detection: if a string tool output looks like raw base64
        # image data (e.g. sandbox stdout printing base64-encoded PNG), redirect
        # it to ephemeral storage BEFORE it enters the LLM context.  This prevents
        # the LLM from echoing tens of kilobytes of base64 token-by-token, which
        # can take minutes and waste tokens.  The agent receives a file_id instead
        # and can use GeneratePresignedURL to give the user a download link.
        import re
        BASE64_IMAGE_MIN_LEN = 10_000  # ~7.5 KB decoded — skip tiny strings
        if (
            isinstance(output, str)
            and len(output) >= BASE64_IMAGE_MIN_LEN
            and re.fullmatch(r'[A-Za-z0-9+/\n\r]+=*', output.strip())
        ):
            b64_size = len(output)
            logger.info(
                f"[BASE64_GUARD] Detected {b64_size:,} char base64 blob in "
                f"tool '{tool_name}' output — redirecting to ephemeral file"
            )
            try:
                from ..routers.v1.files import register_ephemeral_tool_output

                file_id = await register_ephemeral_tool_output(
                    tool_name=f"{tool_name}_base64_plot",
                    content=output,
                    session_id=self.agent_instance.mcp_session_id,
                    owner_id=self.user_context.get("user_id") if self.user_context else None,
                )

                return (
                    f"Plot image saved as base64 ({b64_size:,} chars, ~{b64_size * 3 // 4 // 1024} KB decoded).\n"
                    f"File ID: {file_id}\n\n"
                    f"To share with the user, generate a presigned download URL:\n"
                    f"  GeneratePresignedURL(file_id='{file_id}', expiry_seconds=3600, disposition='inline')\n\n"
                    f"IMPORTANT: Do NOT paste the raw base64 data into your response. "
                    f"Use the presigned URL so the user can view or download the image directly."
                )
            except Exception as e:
                logger.warning(f"[BASE64_GUARD] Failed to save base64 to file: {e}")
                # Fall through to normal size-based routing

        # Size-based text routing
        if isinstance(output, str):
            output_size = len(output)

            if output_size > LARGE_THRESHOLD:
                # LARGE: Save to file, exclude from context
                try:
                    from ..routers.v1.files import register_ephemeral_tool_output

                    file_id = await register_ephemeral_tool_output(
                        tool_name=tool_name,
                        content=output,
                        session_id=self.agent_instance.mcp_session_id,
                        owner_id=self.user_context.get("user_id") if self.user_context else None,
                    )

                    return (
                        f"⚠️ Tool output too large ({output_size:,} chars, ~{output_size//4:,} tokens).\n"
                        f"Saved to ephemeral file: {file_id}\n\n"
                        f"To access the full output, use one of these tools:\n"
                        f"  • ReadFile('{file_id}') - Read file contents\n"
                        f"  • GeneratePresignedURL('{file_id}') - Get download link\n\n"
                        f"Note: Ephemeral files auto-delete after 7 days."
                    )
                except Exception as e:
                    logger.error(f"Failed to save large output to ephemeral file: {e}", exc_info=True)
                    # Fallback to truncation
                    return (
                        output[:MEDIUM_THRESHOLD // 2]
                        + f"\n\n... [ERROR: Failed to save full output, truncated {output_size - MEDIUM_THRESHOLD} chars] ...\n\n"
                        + output[-MEDIUM_THRESHOLD // 2:]
                    )

            elif output_size > MEDIUM_THRESHOLD:
                # MEDIUM: Truncate for context
                return (
                    output[:MEDIUM_THRESHOLD // 2]
                    + f"\n\n... [Truncated {output_size - MEDIUM_THRESHOLD} chars to fit context window] ...\n\n"
                    + output[-MEDIUM_THRESHOLD // 2:]
                )

            else:
                # SMALL: Include fully
                return output

        # Handle dictionary outputs — check total serialized size first
        if isinstance(output, dict):
            total_size = sum(len(str(v)) for v in output.values())
            if total_size > LARGE_THRESHOLD:
                # Entire dict is too large — redirect to ephemeral file
                try:
                    from ..routers.v1.files import register_ephemeral_tool_output
                    import json as _json

                    serialized = _json.dumps(output, default=str)
                    file_id = await register_ephemeral_tool_output(
                        tool_name=tool_name,
                        content=serialized,
                        session_id=self.agent_instance.mcp_session_id,
                        owner_id=self.user_context.get("user_id") if self.user_context else None,
                    )
                    logger.info(
                        f"[DICT_SANITIZE] Redirected {total_size:,} char dict output "
                        f"from '{tool_name}' to ephemeral file {file_id}"
                    )
                    return {
                        "output": (
                            f"Tool output too large ({total_size:,} chars, ~{total_size//4:,} tokens).\n"
                            f"Saved to ephemeral file: {file_id}\n\n"
                            f"Use ReadFile('{file_id}') or GeneratePresignedURL('{file_id}') to access."
                        ),
                        "file_id": file_id,
                        "status": "completed",
                    }
                except Exception as e:
                    logger.error(f"[DICT_SANITIZE] Failed to save large dict output: {e}")
                    # Fall through to per-field sanitization

            # Per-field sanitization for medium-large string values
            for key, value in output.items():
                if isinstance(value, str) and len(value) > MEDIUM_THRESHOLD:
                    output[key] = await self._sanitize_tool_output(value, tool_name=f"{tool_name}.{key}")

        # Scrub internal filesystem paths from all string content before returning to LLM
        output = self._scrub_internal_paths(output)

        return output

    _INTERNAL_PATH_PATTERN = re.compile(
        r"(/app/(?:data|src|\.venv|credentials|logs|config)[^\s\"',})\]]*"
        r"|/tmp/sandbox_sessions/[^\s\"',})\]]*"
        r"|/var/(?:lib|run|log)/[^\s\"',})\]]*"
        r"|/run/secrets/[^\s\"',})\]]*"
        r"|/etc/(?:ssl|nginx|keycloak|shadow|passwd)[^\s\"',})\]]*"
        r"|/home/[^\s\"',})\]]*"
        r"|/opt/[^\s\"',})\]]*"
        r"|/usr/local/(?:lib|bin|share)/[^\s\"',})\]]*"
        r"|/workspace/[^\s\"',})\]]*)"
    )

    def _scrub_internal_paths(self, output: Any) -> Any:
        """Remove internal filesystem paths from tool output to prevent information disclosure."""
        if isinstance(output, str):
            return self._INTERNAL_PATH_PATTERN.sub("[internal-path-redacted]", output)
        elif isinstance(output, dict):
            scrubbed = {}
            for key, value in output.items():
                if key in ("file_path", "current_path", "absolute_path", "server_path"):
                    scrubbed[key] = "[redacted]"
                elif isinstance(value, str):
                    scrubbed[key] = self._INTERNAL_PATH_PATTERN.sub("[internal-path-redacted]", value)
                elif isinstance(value, (dict, list)):
                    scrubbed[key] = self._scrub_internal_paths(value)
                else:
                    scrubbed[key] = value
            return scrubbed
        elif isinstance(output, list):
            return [self._scrub_internal_paths(item) for item in output]
        return output

    async def _register_emsl_remote_files(
        self,
        tool_output: Dict[str, Any],
        tool_name: str,
        state: "AgentState",
    ) -> None:
        """
        Auto-register file metadata in Redis for files generated on the EMSL sandbox.

        Parses `generated_files` and `plots` from tool output, converts EMSL paths
        to nginx URLs via EMSL_FILES_BASE_URL, and stores metadata with
        storage_type="remote" so the download endpoint can relay the file.
        """
        from ..redis_client import get_files_redis_client

        emsl_base_url = os.getenv("EMSL_FILES_BASE_URL", "").rstrip("/")
        if not emsl_base_url:
            logger.debug(
                "[EMSL_FILE_REGISTER] EMSL_FILES_BASE_URL not configured, skipping"
            )
            return

        owner_id = state.get("user_id", "unknown")
        session_id = state.get("thread_id") or (
            self.agent_instance.mcp_session_id if self.agent_instance else None
        )
        now = int(time.time())

        # Collect file paths from tool output
        file_entries: List[Dict[str, str]] = []

        # generated_files: list of absolute paths or dicts with "path" key
        for item in tool_output.get("generated_files", []):
            if isinstance(item, str):
                file_entries.append({"path": item, "purpose": "assistant_generated"})
            elif isinstance(item, dict) and item.get("path"):
                file_entries.append({"path": item["path"], "purpose": item.get("purpose", "assistant_generated")})

        # plots: list of dicts with "path" key (saved plot files, not base64)
        for plot in tool_output.get("plots", []):
            if isinstance(plot, dict) and plot.get("path"):
                file_entries.append({"path": plot["path"], "purpose": "plot"})

        if not file_entries:
            return

        redis_pool = await get_files_redis_client()
        registered_count = 0

        for entry in file_entries:
            abs_path = entry["path"]
            filename = os.path.basename(abs_path)

            # Convert absolute EMSL path to nginx URL
            # Example: /app/data/uploaded_files/sessions/sid/outputs/result.csv
            #       -> http://172.17.0.1:9081/files/sessions/sid/outputs/result.csv
            # The EMSL nginx serves /files/ from /app/data/uploaded_files/
            shared_vol_prefix = "/app/data/uploaded_files/"
            tmpfs_prefix = "/tmp/sandbox_sessions/"
            if abs_path.startswith(shared_vol_prefix):
                relative_path = abs_path[len(shared_vol_prefix):]
            elif abs_path.startswith(tmpfs_prefix):
                # Fallback: tmpfs paths from older sandbox versions.
                # Convert /tmp/sandbox_sessions/{sid}/workspace/file.csv
                # to sessions/{sid}/outputs/file.csv (the published location)
                import re
                m = re.match(r"/tmp/sandbox_sessions/([^/]+)/(?:workspace|outputs)/(.+)", abs_path)
                if m:
                    relative_path = f"sessions/{m.group(1)}/outputs/{m.group(2)}"
                else:
                    relative_path = filename
                logger.warning(
                    f"[EMSL_FILE_REGISTER] Got tmpfs path {abs_path}, "
                    f"converted to {relative_path}"
                )
            else:
                # Last resort: use just the filename
                relative_path = filename

            remote_url = f"{emsl_base_url}/{relative_path}"

            # Generate deterministic-ish file ID
            file_id = f"file-emsl-{uuid.uuid4().hex[:12]}-{filename}"

            file_metadata = {
                "id": file_id,
                "object": "file",
                "filename": filename,
                "purpose": entry["purpose"],
                "status": "processed",
                "owner_id": owner_id,
                "session_id": session_id,
                "created_at": now,
                "storage_type": "remote",
                "remote_url": remote_url,
                "remote_source": "emsl_sandbox",
                "original_remote_path": abs_path,
                "generated_by": tool_name,
            }

            await redis_pool.set(
                f"file_metadata:{file_id}",
                json.dumps(file_metadata),
                ex=7 * 24 * 60 * 60,  # 7-day TTL
            )
            registered_count += 1

            logger.info(
                f"[EMSL_FILE_REGISTER] Registered remote file: "
                f"id={file_id}, url={remote_url}, owner={owner_id}"
            )

        if registered_count > 0:
            logger.info(
                f"[EMSL_FILE_REGISTER] Registered {registered_count} EMSL files "
                f"from {tool_name} for session {session_id}"
            )

    async def _custom_tool_node(self, state: AgentState) -> dict:
        """
        The "action" node. It executes tool calls requested by the agent.

        This node is the core of the split-stream strategy. It:
        1.  Invokes the requested tool.
        2.  Stores the full, raw output in the `full_tool_outputs` field of the state.
        3.  Sanitizes the output using `_sanitize_tool_output`.
        4.  Returns the sanitized output in a `ToolMessage` to be passed back to the LLM.
        """
        tool_messages_for_llm = []
        full_tool_outputs_for_state = []
        last_message = state["messages"][-1]

        # Handle case where last message is a ToolMessage from checkpoint repair
        from langchain_core.messages import ToolMessage

        if isinstance(last_message, ToolMessage):
            # Find pending tool calls that need responses
            pending_tool_call_ids = self._get_pending_tool_calls(state["messages"])

            if pending_tool_call_ids:
                # CRITICAL FIX: Insert synthetic ToolMessages at correct position
                logger.warning(
                    f"[ORPHANED_TOOL_CALLS_FIX] Detected {len(pending_tool_call_ids)} orphaned tool_calls in _custom_tool_node"
                )

                messages = list(state["messages"])
                synthetic_messages_inserted = []

                # Build map of tool_call_id -> synthetic ToolMessage
                # CRITICAL FIX (2025-12-25): Synthetic ToolMessages must include:
                # - name: Explicit tool identifier for OpenAI format
                # - additional_kwargs={"role": "tool"}: LangChain ToolMessage has type='tool'
                #   but lacks role attribute. OpenAI requires BOTH type and role.
                #   Without explicit role, OpenAI rejects with "messages.[N].role" error.
                synthetic_by_id = {}
                for tool_call_id in pending_tool_call_ids:
                    logger.warning(
                        f"[ORPHANED_TOOL_CALLS_FIX] Creating synthetic ToolMessage for: {tool_call_id}"
                    )
                    synthetic_by_id[tool_call_id] = ToolMessage(
                        content=json.dumps(
                            {
                                "status": "error",
                                "message": "Tool call response missing due to state restoration. This is a recovery ToolMessage to maintain OpenAI API compliance.",
                                "error_type": "checkpoint_restoration_error",
                                "tool_call_id": tool_call_id,
                            }
                        ),
                        tool_call_id=tool_call_id,
                        name="checkpoint_restoration_recovery",
                        additional_kwargs={"role": "tool"},
                    )

                # Insert synthetic ToolMessages immediately after their AIMessages
                # Iterate backwards to preserve indices
                for i in range(len(messages) - 1, -1, -1):
                    msg = messages[i]
                    if (
                        isinstance(msg, AIMessage)
                        and hasattr(msg, "tool_calls")
                        and msg.tool_calls
                    ):
                        orphaned_in_this_msg = []
                        for tool_call in msg.tool_calls:
                            tc_id = (
                                tool_call.id
                                if hasattr(tool_call, "id")
                                else tool_call.get("id")
                            )
                            if tc_id in synthetic_by_id:
                                orphaned_in_this_msg.append(tc_id)

                        if orphaned_in_this_msg:
                            insert_pos = i + 1
                            for tc_id in orphaned_in_this_msg:
                                messages.insert(insert_pos, synthetic_by_id[tc_id])
                                synthetic_messages_inserted.append(
                                    synthetic_by_id[tc_id]
                                )
                                logger.info(
                                    f"[ORPHANED_TOOL_CALLS_FIX] Inserted synthetic ToolMessage at position {insert_pos} for: {tc_id}"
                                )

                return {"messages": synthetic_messages_inserted}

            # If no pending calls, try to find AI message for normal processing
            for msg in reversed(state["messages"][:-1]):
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    last_message = msg
                    break
            else:
                # No AI message found and no pending calls - this is unexpected
                logger.error(
                    f"No AI message with tool_calls found and no pending calls in state"
                )
                # Return empty as last resort (shouldn't happen)
                return {"messages": []}

        # Defensive check for tool_calls attribute
        if not hasattr(last_message, "tool_calls"):
            logger.warning(
                f"Message doesn't have tool_calls attribute: {type(last_message).__name__}"
            )
            return {"messages": []}

        if not last_message.tool_calls:
            logger.warning("Message has empty tool_calls list")
            return {"messages": []}

        for tool_call in last_message.tool_calls:
            # Wrap entire tool processing in outer try-except to guarantee message creation
            tool_id = None
            tool_name = "unknown"
            try:
                # Handle both object and dictionary access patterns for tool_call
                if hasattr(tool_call, "name"):
                    # Object with attributes (e.g., from LangChain)
                    tool_name = (
                        tool_call.name if hasattr(tool_call, "name") else "unknown"
                    )
                    tool_args = tool_call.args if hasattr(tool_call, "args") else {}
                    tool_id = (
                        tool_call.id if hasattr(tool_call, "id") else str(tool_call)
                    )
                elif isinstance(tool_call, dict):
                    # Dictionary format
                    tool_name = tool_call.get("name", "unknown")
                    tool_args = tool_call.get("args", {})
                    tool_id = tool_call.get("id", str(tool_call))
                else:
                    # Fallback for unexpected format
                    logger.warning(f"Unexpected tool_call format: {type(tool_call)}")
                    tool_name = "unknown"
                    tool_args = {}
                    tool_id = str(tool_call)

                # Log for debugging
                logger.debug(
                    f"Processing tool call: name={tool_name}, id={tool_id}, args_keys={list(tool_args.keys()) if isinstance(tool_args, dict) else 'N/A'}"
                )

                tool_to_call = next(
                    (t for t in self.tools if t.name == tool_name), None
                )
                raw_output_dict = None

                if not tool_to_call:
                    # Create error response for missing tool
                    raw_output_dict = {
                        "output": f"Error: Tool '{tool_name}' not found.",
                        "status": "error",
                    }
                else:
                    # Execute tool via factory pattern (async task management)
                    try:
                        # Create execution context from state
                        # Allow tools to declare their own timeout via
                        # a timeout_seconds parameter in their MCP definition.
                        # The agent can set this based on the user's prompt
                        # (e.g., large batch jobs need longer timeouts).
                        tool_timeout = int(
                            tool_args.get("timeout_seconds", 300)
                            if isinstance(tool_args, dict)
                            else 300
                        )

                        context = ToolExecutionContext(
                            thread_id=state.get("thread_id", "unknown"),
                            mcp_session_id=state.get("mcp_session_id"),
                            multi_agent_session_id=state.get("multi_agent_session_id"),
                            user_id=state.get("user_id", "unknown"),
                            request_id=state.get("request_id", "unknown"),
                            timeout=tool_timeout,
                        )

                        # Initialize streaming executor on first use (with session context)
                        if self.streaming_executor is None:
                            self.streaming_executor = StreamingToolExecutor(
                                tool_factory=self.tool_factory,
                                mcp_session_id=context.mcp_session_id,
                                threshold_chars=int(os.getenv("TOOL_OUTPUT_STREAMING_THRESHOLD", "200000")),
                            )

                        # Execute via streaming executor (auto-detects streaming support)
                        # Falls back to tool_factory for non-streaming tools
                        result = await self.streaming_executor.execute(
                            tool_to_call,
                            tool_name,
                            tool_args,
                            context,
                            owner_id=state.get("user_id"),
                        )

                        if result.success:
                            # Tool execution successful (or queued for async)
                            raw_output = result.result

                            # Handle different return types from successful tool calls
                            if raw_output is None:
                                raw_output_dict = {
                                    "output": "Tool executed but returned no output",
                                    "status": "completed",
                                }
                            elif isinstance(raw_output, dict):
                                # Tool returned a dictionary - use it directly
                                raw_output_dict = raw_output
                            elif isinstance(raw_output, str):
                                # Tool returned a string - handle empty strings and JSON parsing
                                if not raw_output or raw_output.strip() == "":
                                    raw_output_dict = {
                                        "output": "Tool executed but returned no output",
                                        "status": "completed",
                                    }
                                else:
                                    try:
                                        raw_output_dict = json.loads(raw_output)
                                    except json.JSONDecodeError:
                                        # Handle non-JSON responses by wrapping them
                                        raw_output_dict = {
                                            "output": raw_output,
                                            "status": "completed",
                                        }
                            else:
                                # Handle other types by converting to string
                                raw_output_dict = {
                                    "output": str(raw_output),
                                    "status": "completed",
                                }
                        else:
                            # Tool execution failed
                            raw_output_dict = {
                                "output": f"Error executing tool '{tool_name}': {result.error}",
                                "status": "error",
                                "error_type": "execution_error",
                            }

                    except Exception as e:
                        # Handle tool execution errors by creating an error response
                        error_msg = str(e)

                        # Check if this is a timeout error and provide specific guidance
                        if "TIMEOUT ERROR:" in error_msg:
                            # This is a timeout from our MCPToolWrapper
                            raw_output_dict = {
                                "output": error_msg,  # Already contains helpful timeout message
                                "status": "timeout",
                                "error_type": "timeout",
                            }
                        else:
                            # Generic error handling
                            raw_output_dict = {
                                "output": f"Error executing tool '{tool_name}': {error_msg}",
                                "status": "error",
                                "error_type": "execution_error",
                            }

                full_tool_outputs_for_state.append(raw_output_dict)

                # Auto-register EMSL remote file metadata for presigned URL downloads
                if tool_name.startswith("emsl_sandbox_") and isinstance(raw_output_dict, dict):
                    try:
                        await self._register_emsl_remote_files(raw_output_dict, tool_name, state)
                    except Exception as emsl_err:
                        logger.warning(
                            f"[EMSL_FILE_REGISTER] Failed to register EMSL files: {emsl_err}"
                        )

                sanitized_output_dict = await self._sanitize_tool_output(raw_output_dict, tool_name=tool_name)
                sanitized_output_str = json.dumps(sanitized_output_dict)

                tool_messages_for_llm.append(
                    ToolMessage(content=sanitized_output_str, tool_call_id=tool_id)
                )
            except Exception as catastrophic_error:
                # Last resort error handling - ensure a tool message is ALWAYS created
                logger.error(
                    f"Catastrophic error processing tool {tool_name}: {catastrophic_error}"
                )

                # Ensure we have a tool_id (could be None if error happened early)
                if tool_id is None:
                    tool_id = f"error_{tool_name}_{id(tool_call)}"

                # Create emergency error response
                emergency_output = {
                    "output": f"Critical error processing tool '{tool_name}': {str(catastrophic_error)[:200]}",
                    "status": "critical_error",
                    "error_type": "catastrophic",
                }

                full_tool_outputs_for_state.append(emergency_output)
                tool_messages_for_llm.append(
                    ToolMessage(
                        content=json.dumps(emergency_output), tool_call_id=tool_id
                    )
                )
                logger.warning(
                    f"Created emergency tool message for {tool_id} after catastrophic error"
                )

        # POST-TASK FORK CHECK: Check if adding tool outputs would exceed context threshold
        # This check happens AFTER tool execution but BEFORE adding messages to state
        # If fork is needed, context will be bootstrapped and new session ID added to state
        if self.context_manager and tool_messages_for_llm:
            try:
                # Combine all tool message contents for token estimation
                combined_tool_output = "\n".join(
                    msg.content for msg in tool_messages_for_llm if hasattr(msg, "content")
                )

                # Check if fork is needed (updates state if fork occurs)
                new_session_id = await self._check_and_fork_if_needed(
                    state=state,
                    tool_output_content=combined_tool_output,
                )

                if new_session_id:
                    logger.info(
                        f"[POST_TASK_FORK] Context forked after tool execution: "
                        f"new_session={new_session_id}"
                    )
                    # State has been updated with bootstrapped messages and fork metadata
                    # Continue with original tool messages as planned

            except Exception as e:
                logger.error(
                    f"[POST_TASK_FORK] Fork check failed: {e}, continuing without fork",
                    exc_info=True
                )

        return {
            "messages": tool_messages_for_llm,
            "full_tool_outputs": full_tool_outputs_for_state,
        }

    async def _check_and_fork_if_needed(
        self,
        state: Dict[str, Any],
        tool_output_content: str,
    ) -> Optional[str]:
        """
        Check if adding tool output would exceed context threshold and fork if needed.

        This method implements post-task context health monitoring by:
        1. Estimating tokens in tool output using tiktoken
        2. Calculating projected total tokens (current + output + tool schemas)
        3. Comparing against fork threshold (default 80% of max_tokens)
        4. Triggering context fork if threshold would be exceeded

        Args:
            state: Current agent state with messages and thread_id
            tool_output_content: Raw tool output content to estimate

        Returns:
            New session ID if fork was triggered, None otherwise

        Note:
            Fork threshold is configurable via POST_TASK_FORK_THRESHOLD_PERCENT
            environment variable (default 0.8 = 80% = 120k tokens for 150k limit).
        """
        # Check if post-task fork monitoring is enabled
        if not self.context_manager:
            logger.debug("[POST_TASK_FORK] No context manager, skipping fork check")
            return None

        if not self.context_manager.config.post_task_fork_enabled:
            logger.debug("[POST_TASK_FORK] Fork monitoring disabled")
            return None

        try:
            messages = state.get("messages", [])
            if not messages:
                logger.debug("[POST_TASK_FORK] No messages in state, skipping")
                return None

            # Step 1: Estimate current context tokens using tiktoken
            if self.context_manager.config.token_estimator_type == "tiktoken":
                current_tokens = self.context_manager.estimate_tokens_accurate(messages)
            else:
                current_tokens = self.context_manager.estimate_tokens(messages)

            # Step 2: Estimate tool output tokens
            # Create temporary message for estimation
            from langchain_core.messages import ToolMessage
            temp_tool_msg = ToolMessage(content=tool_output_content, tool_call_id="temp")

            if self.context_manager.config.token_estimator_type == "tiktoken":
                output_tokens = self.context_manager.estimate_tokens_accurate([temp_tool_msg])
            else:
                output_tokens = self.context_manager.estimate_tokens([temp_tool_msg])

            # Step 3: Estimate tool schema overhead
            tool_schema_tokens = self.context_manager._estimate_tool_schema_tokens(self.tools)

            # Step 4: Calculate projected total tokens
            projected_tokens = current_tokens + output_tokens + tool_schema_tokens

            # Step 5: Calculate fork threshold
            max_tokens = self.context_manager.config.max_tokens
            fork_threshold_percent = self.context_manager.config.post_task_fork_threshold_percent
            fork_threshold = int(max_tokens * fork_threshold_percent)

            logger.debug(
                f"[POST_TASK_FORK] Context check: "
                f"current={current_tokens}, "
                f"output={output_tokens}, "
                f"tool_schemas={tool_schema_tokens}, "
                f"projected={projected_tokens}, "
                f"threshold={fork_threshold} ({fork_threshold_percent*100}%)"
            )

            # Step 6: Check if fork is needed
            if projected_tokens > fork_threshold:
                logger.warning(
                    f"[POST_TASK_FORK] Fork triggered: "
                    f"projected={projected_tokens} > threshold={fork_threshold} "
                    f"({fork_threshold_percent*100}% of {max_tokens})"
                )

                # Trigger fork via context manager
                thread_id = state.get("thread_id", "unknown")
                messages_truncated, new_session_id, metadata = await self.context_manager.prepare_context(
                    messages=messages,
                    thread_id=thread_id,
                    available_tools=self.tools,
                )

                if new_session_id:
                    logger.info(
                        f"[POST_TASK_FORK] Session forked: "
                        f"old={thread_id} -> new={new_session_id}, "
                        f"tokens_saved={current_tokens - metadata.truncated_token_count}"
                    )

                    # Update state with forked session ID
                    state["forked_session_id"] = new_session_id
                    state["messages"] = messages_truncated  # Use bootstrapped context
                    state["fork_reason"] = "post_task_context_health"
                    state["fork_metadata"] = {
                        "original_tokens": current_tokens,
                        "projected_tokens": projected_tokens,
                        "threshold": fork_threshold,
                        "new_tokens": metadata.truncated_token_count,
                    }

                    return new_session_id
                else:
                    logger.warning(
                        "[POST_TASK_FORK] Fork attempted but no new session created"
                    )
                    return None
            else:
                logger.debug(
                    f"[POST_TASK_FORK] No fork needed: "
                    f"projected={projected_tokens} <= threshold={fork_threshold}"
                )
                return None

        except Exception as e:
            logger.error(
                f"[POST_TASK_FORK] Error in fork check: {e}, "
                f"continuing without fork",
                exc_info=True
            )
            return None

    def termination_node(self, state: AgentState) -> dict:
        """
        Termination node that generates user-facing error message when recursion detected.

        This is a proper node function (not a routing function), so state modifications
        persist properly. Called when should_continue() detects repeated tool calls
        indicating an infinite loop or unresolvable issue.

        **Self-Contained Implementation (Session 57)**: This method re-analyzes messages
        directly instead of relying on state["termination_reason"], because LangGraph
        does NOT persist state mutations from conditional edge (routing) functions.
        The state-based path is tried first as an optimization, but the message
        re-analysis path handles the common case where state propagation is lost.

        Args:
            state: Current agent state (termination_reason may or may not be populated)

        Returns:
            dict: State update with AIMessage containing user-facing error explanation
        """
        from langchain_core.messages import AIMessage

        # Try state-based reason first (works in unit tests, may be empty in LangGraph runtime)
        termination_info = state.get("termination_reason", {})

        # Fallback chain: state tool_name → state all_repeated_tools → message re-analysis → "unknown"
        tool_name = termination_info.get("tool_name", None)

        if tool_name is None:
            # Fallback 1: Try all_repeated_tools from state (e.g., unit tests with partial state)
            all_tools_state = termination_info.get("all_repeated_tools", {})
            if all_tools_state:
                tool_name = max(all_tools_state, key=all_tools_state.get)
                logger.warning(
                    f"[TERMINATION_NODE] Using fallback tool_name from all_repeated_tools: {tool_name}"
                )

        if tool_name is None:
            # Fallback 2: Re-analyze messages directly (Session 57 Bug 2 fix)
            # This is the expected path in production LangGraph runtime where
            # state mutations from routing functions are NOT persisted.
            logger.info(
                f"[TERMINATION_NODE] tool_name not in state (LangGraph routing state loss). "
                f"Re-analyzing messages directly."
            )

            reanalysis = self._analyze_recent_tool_repetitions(state.get("messages", []))

            if reanalysis.get("tool_name"):
                tool_name = reanalysis["tool_name"]
                termination_info = reanalysis
                logger.info(
                    f"[TERMINATION_NODE] Re-analysis found tool: {tool_name} "
                    f"(detection_type={reanalysis.get('detection_type')})"
                )
            else:
                # Try most-repeated tool from re-analysis (even if below threshold)
                all_tools_reanalysis = reanalysis.get("all_repeated_tools", {})
                if all_tools_reanalysis:
                    tool_name = max(all_tools_reanalysis, key=all_tools_reanalysis.get)
                    termination_info = reanalysis
                    logger.warning(
                        f"[TERMINATION_NODE] Using most-repeated tool from re-analysis: {tool_name}"
                    )
                else:
                    # Fallback 3: No data at all
                    tool_name = "unknown"
                    logger.error(
                        "[TERMINATION_NODE] No tool_name in state and no tool calls in messages. "
                        "Using 'unknown' as final fallback."
                    )
        else:
            logger.info(f"[TERMINATION_NODE] Tool name successfully extracted from state: {tool_name}")

        repeat_count = termination_info.get("repeat_count", 3)
        all_tools = termination_info.get("all_repeated_tools", {})
        recent_errors = termination_info.get("recent_errors", [])

        # Generate generic error message (not specific to file/RAG processing)
        error_msg = (
            f"⚠️ **I encountered an issue that I cannot resolve.**\n\n"
            f"The tool **`{tool_name}`** was called {repeat_count} times consecutively without success, "
            f"indicating an unresolvable problem in the current approach.\n\n"
        )

        # Include captured error context if available
        if recent_errors:
            error_msg += f"**Recent error details:**\n"
            for idx, error in enumerate(recent_errors, 1):
                # Clean up error message for display
                error_clean = error.replace("\\n", " ").strip()
                error_msg += f"{idx}. {error_clean}\n"
            error_msg += "\n"

        # Generic guidance (applies to all scenarios)
        error_msg += (
            f"**Common reasons for repeated tool failures:**\n"
            f"- Input format or data type not supported by the tool\n"
            f"- Required dependencies or services unavailable\n"
            f"- Invalid parameters or missing prerequisites\n"
            f"- Resource constraints or permissions issues\n\n"
        )

        # Summary of all repeated tools
        if len(all_tools) > 1:
            error_msg += f"**All repeated tool calls:** {dict(all_tools)}\n\n"

        error_msg += (
            f"**Suggested next steps:**\n"
            f"- Try a different approach or tool for this task\n"
            f"- Check that all prerequisites are met\n"
            f"- Verify input data format and parameters\n"
            f"- Review error details above for specific issues"
        )

        termination_msg = AIMessage(content=error_msg)
        logger.info(
            f"[TERMINATION_NODE] Generated generic error message for repeated tool: {tool_name}, "
            f"captured {len(recent_errors)} error context messages"
        )

        return {"messages": [termination_msg]}

    def build(self) -> StateGraph:
        """Constructs and returns the compiled LangGraph StateGraph."""
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", self.call_model)
        workflow.add_node("action", self._custom_tool_node)
        workflow.add_node("terminate", self.termination_node)
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges(
            "agent", self.should_continue, {"continue": "action", "terminate": "terminate", "end": END}
        )
        workflow.add_edge("action", "agent")
        workflow.add_edge("terminate", END)
        return workflow
