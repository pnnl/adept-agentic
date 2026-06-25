"""
This module defines the shared state object for the LangGraph agent.

It is kept in a separate file to avoid circular imports between the agent,
the graph builder, and other components that might need to reference the
agent's state structure.

The `AgentState` TypedDict defines the schema for the data that is passed
between the nodes of the LangGraph.
"""
from typing import List, Dict, Any, Annotated, Sequence, TypedDict
import operator
from langchain_core.messages import BaseMessage

# This file defines the shared state object for the LangGraph agent.
# It is kept in a separate file to avoid circular imports between the
# agent and the graph builder.

class AgentState(TypedDict, total=False):
    """
    Represents the state of the agent's workflow graph.

    Attributes:
        messages: A sequence of LangChain messages (Human, AI, Tool) that form
            the history of the conversation. The `operator.add` annotation
            tells LangGraph to append new messages to this list.
        chat_history: A simplified list of dictionaries representing the chat
            history, often used for display or simpler logging.
        full_tool_outputs: A list where the complete, raw outputs from tool
            calls are stored. This is part of the "split-stream" strategy,
            ensuring that large outputs (like plot data) are preserved in the
            state without polluting the LLM's context window.
        forked_session_id: Optional session ID if sub-session fork occurred (Phase 3A).
        fork_metadata: Optional metadata about fork event (Phase 3A).
    """
    messages: Annotated[Sequence[BaseMessage], operator.add]
    chat_history: List[Dict[str, str]]
    full_tool_outputs: Annotated[List[Dict[str, Any]], operator.add]
    forked_session_id: str  # Phase 3A: New session ID after fork
    fork_metadata: Dict[str, Any]  # Phase 3A: Fork metadata (parent_session_id, generation, etc.)
    termination_reason: Dict[str, Any]  # Recursion termination context (tool_name, repeat_count, etc.)