"""
LLM Wrapper for Orphaned Tool_Calls Repair

This module provides an LLM wrapper that intercepts ainvoke calls to repair
orphaned tool_calls before messages are sent to OpenAI. This is critical for
React agents created with create_react_agent() that bypass graph_builder.py.

Root Cause:
-----------
Multi-agent router mode and worker agents use LangChain's create_react_agent(),
which has its own internal node structure and doesn't use graph_builder.py's
call_model() method where the orphaned tool_calls fix was initially implemented.

When checkpoints are restored with incomplete tool_calls (AIMessage with tool_calls
but no corresponding ToolMessages), OpenAI rejects the request with:
"An assistant message with 'tool_calls' must be followed by tool messages
responding to each 'tool_call_id'."

Solution:
---------
This wrapper intercepts LLM ainvoke() calls, detects orphaned tool_calls using
the same logic as graph_builder.py, and creates synthetic ToolMessages to repair
the message history before sending to OpenAI.

Usage:
------
Wrap any LLM before passing to create_react_agent():

    llm = get_langchain_chat_model()
    wrapped_llm = OrphanedToolCallsLLMWrapper(llm=llm)
    agent = create_react_agent(model=wrapped_llm, tools=tools, checkpointer=checkpointer)

The wrapper is transparent - it behaves exactly like the underlying LLM but adds
automatic orphaned tool_calls repair.
"""

import json
from typing import Any, List, Dict, Optional, Union
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig, RunnableBinding

from ...logger_config import get_logger

logger = get_logger(__name__)


class OrphanedToolCallsLLMWrapper(BaseChatModel):
    """
    LLM wrapper that repairs orphaned tool_calls before invoking OpenAI.

    This wrapper intercepts ainvoke() calls and:
    1. Extracts messages from the invocation
    2. Detects orphaned tool_calls (AIMessages with tool_calls but no ToolMessages)
    3. Creates synthetic ToolMessages for orphaned tool_calls
    4. Passes the repaired messages to the underlying LLM

    Attributes:
        llm: The underlying LLM to wrap (e.g., ChatOpenAI, ChatAnthropic, or RunnableBinding)
    """

    llm: Union[BaseChatModel, RunnableBinding]
    """The underlying LLM to wrap (accepts BaseChatModel or RunnableBinding from bind_tools)"""

    class Config:
        """Pydantic config"""
        arbitrary_types_allowed = True

    def __init__(self, llm: Union[BaseChatModel, RunnableBinding], **kwargs):
        """Initialize the wrapper with an underlying LLM (BaseChatModel or RunnableBinding)."""
        super().__init__(llm=llm, **kwargs)

    def _get_pending_tool_calls(self, messages: List[BaseMessage]) -> List[str]:
        """
        Detect orphaned tool_calls in message history.

        Checks for AIMessages with tool_calls that have no corresponding ToolMessages.

        Args:
            messages: List of messages to check

        Returns:
            List of tool_call_ids that are orphaned (no ToolMessage responses)
        """
        # Find all tool_call_ids that have been requested
        requested_tool_call_ids = set()
        for msg in messages:
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls"):
                for tool_call in msg.tool_calls:
                    if hasattr(tool_call, "id"):
                        requested_tool_call_ids.add(tool_call.id)
                    elif isinstance(tool_call, dict) and "id" in tool_call:
                        requested_tool_call_ids.add(tool_call["id"])

        # Find all tool_call_ids that have been responded to
        responded_tool_call_ids = set()
        for msg in messages:
            if isinstance(msg, ToolMessage) and hasattr(msg, "tool_call_id"):
                responded_tool_call_ids.add(msg.tool_call_id)

        # Return pending tool calls (requested but not responded)
        pending = list(requested_tool_call_ids - responded_tool_call_ids)
        return pending

    def _repair_orphaned_tool_calls(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        Repair orphaned tool_calls by creating synthetic ToolMessages.

        CRITICAL FIX: Position-aware orphaned tool_calls repair
        This fix addresses position shifting between LLM invocations.
        Problem: Synthetic ToolMessages get separated from AIMessages by intervening messages
        Solution: Detect mispositioned ToolMessages and re-insert at correct positions

        Args:
            messages: Original message list

        Returns:
            Repaired message list with synthetic ToolMessages added at correct positions
        """
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

        # If no problematic tool_calls found, return original messages
        if not problematic_tool_calls:
            return messages

        logger.warning(
            f"[ORPHANED_TOOL_CALLS_FIX_WRAPPER] Detected {len(problematic_tool_calls)} orphaned/mispositioned tool_calls"
        )

        # Step 1: Remove any mispositioned ToolMessages from the list
        # These exist elsewhere but not immediately after their AIMessages
        messages_to_keep = []
        for msg in messages:
            if isinstance(msg, ToolMessage) and msg.tool_call_id in mispositioned_tool_call_ids:
                logger.info(
                    f"[ORPHANED_TOOL_CALLS_FIX_WRAPPER] Removing mispositioned ToolMessage for: {msg.tool_call_id}"
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
                f"[ORPHANED_TOOL_CALLS_FIX_WRAPPER] Creating synthetic ToolMessage for: {tc_id}"
            )
            synthetic_by_id[tc_id] = ToolMessage(
                content=json.dumps({
                    "status": "error",
                    "message": "Tool call response missing due to checkpoint restoration. This is a recovery ToolMessage to maintain OpenAI API compliance.",
                    "error_type": "checkpoint_restoration_error",
                    "tool_call_id": tc_id
                }),
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
                    f"[ORPHANED_TOOL_CALLS_FIX_WRAPPER] Inserted synthetic ToolMessage at position {insert_pos} for: {tc_id}"
                )

        logger.info(
            f"[ORPHANED_TOOL_CALLS_FIX_WRAPPER] Repaired {len(problematic_tool_calls)} orphaned/mispositioned tool_calls"
        )

        return messages

    async def ainvoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
        **kwargs
    ) -> AIMessage:
        """
        Async invoke with orphaned tool_calls repair.

        Intercepts the ainvoke call, repairs orphaned tool_calls if any,
        then passes to the underlying LLM.

        Args:
            input: Input to the LLM (typically List[BaseMessage] or prompt string)
            config: Runnable configuration
            **kwargs: Additional arguments

        Returns:
            AIMessage response from underlying LLM
        """
        # Extract messages from input
        if isinstance(input, list):
            messages = input
        elif hasattr(input, "messages"):
            messages = input.messages
        else:
            # Can't repair non-message inputs, pass through
            return await self.llm.ainvoke(input, config=config, **kwargs)

        # Repair orphaned tool_calls
        repaired_messages = self._repair_orphaned_tool_calls(messages)

        # Pass repaired messages to underlying LLM
        if isinstance(input, list):
            repaired_input = repaired_messages
        else:
            repaired_input = input
            repaired_input.messages = repaired_messages

        return await self.llm.ainvoke(repaired_input, config=config, **kwargs)

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs) -> Any:
        """Required abstract method for BaseChatModel - delegates to underlying LLM"""
        return self.llm._generate(messages, stop=stop, **kwargs)

    async def _agenerate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs) -> Any:
        """Async generate - repair orphaned tool_calls before generating"""
        repaired_messages = self._repair_orphaned_tool_calls(messages)
        return await self.llm._agenerate(repaired_messages, stop=stop, **kwargs)

    def bind_tools(self, tools: Any, **kwargs) -> "OrphanedToolCallsLLMWrapper":
        """Bind tools to underlying LLM and return wrapped version"""
        bound_llm = self.llm.bind_tools(tools, **kwargs)
        return OrphanedToolCallsLLMWrapper(llm=bound_llm)

    @property
    def _llm_type(self) -> str:
        """Return LLM type from underlying LLM"""
        return f"orphaned_tool_calls_wrapper_{self.llm._llm_type}"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """Return identifying params from underlying LLM"""
        return self.llm._identifying_params
