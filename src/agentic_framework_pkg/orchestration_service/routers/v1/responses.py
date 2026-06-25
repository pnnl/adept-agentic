"""
OpenAI Response API Implementation - Orchestration Service

This module implements the Response API endpoints in the orchestration service,
providing a simpler alternative to the Assistant API for basic conversational
interactions and function calling.

Key Features:
- Single-shot completions with conversation context
- Streaming response support
- Function calling integration with MCP tools
- OpenAI-compatible response format
- Simpler workflow than Assistant API

Architecture:
- Receives requests from Agent Gateway
- Uses ScientificWorkflowAgent for processing
- Integrates with existing MCP tool ecosystem
- Provides both streaming and non-streaming responses
"""

import time
import uuid
import asyncio
import json
import html
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Union
from sqlalchemy import select, func

from ....core.auth import AuthCredentials
from ...auth import get_forwarded_user
from ....logger_config import get_logger
from ...scientific_workflow.langchain_agent import ScientificWorkflowAgent
from ...openai_error_handler import OpenAIErrorFormatter
from ...persistence_v2 import AsyncPostgresSaver
from ...hybrid_orchestration import hybrid_service
from ...persistence import get_async_session
from ...models.session_models import SessionMessage
from ...request_context import RequestContext

router = APIRouter()
logger = get_logger(__name__)

_CONTENT_FILTER_EXCEPTION_NAMES = frozenset({
    "ContentFilterFinishReasonError",
    "BadRequestError",
    "ContentPolicyViolationError",
})

_CONTENT_FILTER_SUBSTRINGS = ("content_filter", "content management policy", "ResponsibleAIPolicyViolation")


def _is_content_filter_error(exc: Exception) -> bool:
    """Detect content filter errors from LLM providers (Azure, Bedrock, OpenAI).

    Checks exception class name first (stable), then falls back to substring
    matching on the error message for providers that use generic exception types.
    """
    if type(exc).__name__ in _CONTENT_FILTER_EXCEPTION_NAMES:
        return True
    error_code = getattr(exc, "code", None)
    if error_code == "content_filter":
        return True
    error_str = str(exc)
    return any(s in error_str for s in _CONTENT_FILTER_SUBSTRINGS)


# ============================================================================
# Helper Functions for Session Persistence (Phase 2)
# ============================================================================


async def _get_next_message_index(session_id: str) -> int:
    """
    Get the next available message index for a session.

    Args:
        session_id: Session identifier

    Returns:
        Next message index (0 for new sessions)

    Note:
        Uses max(message_index) + 1 to ensure sequential ordering
        even if messages are added concurrently.
    """
    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(func.max(SessionMessage.message_index)).where(
                    SessionMessage.session_id == session_id
                )
            )
            max_index = result.scalar()
            next_index = (max_index or -1) + 1
            logger.debug(f"Next message index for session {session_id}: {next_index}")
            return next_index
    except Exception as e:
        logger.error(f"Failed to get next message index for session {session_id}: {e}")
        # Fallback to 0 if query fails
        return 0


def _calculate_cost(tokens: int, model: str) -> float:
    """
    Calculate estimated cost for token usage.

    Args:
        tokens: Total token count (prompt + completion)
        model: Model identifier (e.g., "gpt-4o", "gpt-4o-mini")

    Returns:
        Estimated cost in USD

    Note:
        Uses simplified cost model. Actual costs may vary based on:
        - Specific model versions (e.g., gpt-4o-2024-05-13)
        - Regional pricing
        - Cached tokens (reduced cost)
        - Batch API usage
    """
    # Cost per 1000 tokens (USD) - as of 2024
    # Source: https://openai.com/api/pricing/
    cost_per_1k_tokens = {
        "gpt-4o": 0.01,  # GPT-4 Omni (May 2024)
        "gpt-4o-mini": 0.0015,  # GPT-4 Omni Mini
        "gpt-4-turbo": 0.01,  # GPT-4 Turbo
        "gpt-4": 0.03,  # GPT-4 (8k context)
        "gpt-3.5-turbo": 0.0015,  # GPT-3.5 Turbo
        "claude-3-opus": 0.015,  # Claude 3 Opus
        "claude-3-sonnet": 0.003,  # Claude 3 Sonnet
        "claude-3-haiku": 0.00025,  # Claude 3 Haiku
    }

    # Extract base model name (remove version suffix if present)
    base_model = model.split("-2024")[0] if "-2024" in model else model
    base_model = base_model.split("-20")[0] if "-20" in base_model else base_model

    # Get rate or use default
    rate = cost_per_1k_tokens.get(base_model, 0.005)  # Default to 0.5 cents/1k

    # Calculate cost
    cost = (tokens / 1000) * rate
    logger.debug(f"Cost estimation: {tokens} tokens × ${rate}/1k = ${cost:.6f}")

    return cost


_DEFAULT_MODEL = "agentic-framework:scientific-agent-v1"


def resolve_model(requested_model: str) -> str:
    """Resolve a client-provided model name to an ADEPT agent configuration key.

    ADEPT uses a two-layer model abstraction (see TWO_LAYER_MODEL_RESOLUTION_ARCHITECTURE.md):
    - Layer 1 (this function): request.model selects an agent personality
    - Layer 2 (inside agent): backend LLM resolved via llm_purpose + env vars

    Clients (VS Code Copilot, OpenWebUI, MCP) may send arbitrary model names
    like "gpt-4" or "azure/gpt-4o" which have no ADEPT agent mapping. These
    fall through to the default scientific agent. The model name has zero
    influence on which backend LLM actually processes the request.

    Resolution:
      1. adept/ prefix alias -> agentic-framework: namespace
      2. Exact match in AGENT_CONFIGURATIONS -> use as-is
      3. Anything else (bare names, provider-prefixed, unknown) -> default agent
    """
    from ...config import AGENT_CONFIGURATIONS

    resolved = requested_model
    if requested_model.startswith("adept/"):
        resolved = requested_model.replace("adept/", "agentic-framework:")
        logger.debug(f"Resolved model alias: {requested_model} -> {resolved}")

    if resolved not in AGENT_CONFIGURATIONS:
        logger.info(
            f"Model '{html.escape(requested_model)}' not in AGENT_CONFIGURATIONS, "
            f"falling through to default: {_DEFAULT_MODEL}"
        )
        resolved = _DEFAULT_MODEL

    return resolved


# Response API Models
class ResponseMessage(BaseModel):
    role: str
    content: str
    function_call: Optional[Dict[str, Any]] = None
    tool_outputs: Optional[List[Dict[str, Any]]] = (
        None  # Tool output metadata (plots, files, etc.) - renamed from tool_calls to avoid collision with OpenAI's tool invocation field
    )

    class Config:
        # Exclude None values from JSON response to maintain compatibility
        exclude_none = True


class ResponseChoice(BaseModel):
    index: int
    message: ResponseMessage
    finish_reason: Optional[str] = None


class ResponseUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class SessionForkMetadata(BaseModel):
    """
    Metadata about session fork event (Phase 3B).

    Returned when context truncation triggers sub-session forking.
    Clients should switch to forked_session_id for subsequent requests.
    """

    forked_session_id: str
    parent_session_id: str
    generation: int
    fork_reason: str
    bootstrap_message_count: int

    class Config:
        # Exclude None values from JSON response
        exclude_none = True


class ResponseCompletion(BaseModel):
    id: str
    object: str = "response.completion"
    created: int
    model: str
    choices: List[ResponseChoice]
    usage: Optional[ResponseUsage] = None
    session_fork: Optional[SessionForkMetadata] = None  # Phase 3B: Fork metadata


class ResponseRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stream: Optional[bool] = False
    functions: Optional[List[Dict[str, Any]]] = None
    function_call: Optional[Union[str, Dict[str, Any]]] = None
    user_id: Optional[str] = None

    # OpenAI API Parity - Missing Parameters (Phase 3)
    logprobs: Optional[bool] = None  # Token probability logging
    top_logprobs: Optional[int] = None  # Top N token probabilities
    logit_bias: Optional[Dict[str, int]] = None  # Token bias control
    n: Optional[int] = None  # Multiple choice generation
    response_format: Optional[Dict[str, Any]] = None  # JSON mode support
    seed: Optional[int] = None  # Deterministic generation
    stop: Optional[Union[str, List[str]]] = None  # Stop sequences
    frequency_penalty: Optional[float] = None  # Frequency penalty
    presence_penalty: Optional[float] = None  # Presence penalty
    user: Optional[str] = None  # End-user identifier

    # Multi-Tier Session Management (Phase 2)
    session_id: Optional[str] = None  # Main conversation/thread session
    mcp_session_id: Optional[str] = (
        None  # MCP tool state session (fallback to session_id)
    )
    multi_agent_session_id: Optional[str] = None  # Multi-agent team session
    gateway_session_id: Optional[str] = None  # Gateway mesh session (for A2A calls)

    api_type: Optional[str] = "response"


@router.post("/completions", response_model=ResponseCompletion)
async def create_response_completion(
    request: ResponseRequest,
    http_request: Request,
    user: AuthCredentials = Depends(get_forwarded_user)
):
    """
    Create a response completion using the Response API.

    This provides a simpler alternative to the Assistant API workflow
    for basic conversational interactions.
    """
    logger.info(
        f"[ORCHESTRATION_SERVICE] Processing Response API completion for user: {user.username}"
    )

    resolved_model = resolve_model(request.model)

    # Extract request context for presigned URL generation (Option B - Phase 3)
    request_ctx = RequestContext.from_request(http_request)
    logger.debug(
        f"[REQUEST_CONTEXT] Extracted: forwarded_host={request_ctx.forwarded_host}, "
        f"forwarded_proto={request_ctx.forwarded_proto}, forwarded_port={request_ctx.forwarded_port}"
    )

    try:
        # Response API: Direct agent initialization without Assistant objects
        # This is the key difference from Assistant API - no database persistence
        logger.info(
            f"Response API: Direct agent initialization for user: {user.username}"
        )

        # Multi-Tier Session Management (Phase 2)
        # Main conversation session - used for thread persistence
        session_id = request.session_id or f"response_{uuid.uuid4().hex[:16]}"

        # Fork resolution: transparently route to latest sub-session
        # if this session was previously forked by context auto-compaction.
        from ...context_compaction_fork_mapping import resolve_fork

        original_session_id = session_id  # Preserve for file/MCP operations
        resolved_session_id = await resolve_fork(session_id)
        if resolved_session_id != session_id:
            logger.info(
                f"[FORK_RESOLUTION] Resolved {session_id} -> {resolved_session_id}"
            )
            session_id = resolved_session_id

        # MCP tool session — uses ORIGINAL session ID (pre-fork) for file system
        # isolation.  File operations must be fork-agnostic: the directory structure
        # and Redis file metadata should not change when context compaction forks.
        mcp_session = request.mcp_session_id or original_session_id

        # Multi-agent session - for team coordination (if provided)
        multi_agent_session = request.multi_agent_session_id

        # Gateway mesh session - ONLY for A2A communication (explicit only, no fallback)
        # Do NOT default to mcp_session as this triggers A2A delegation mode
        gateway_session = request.gateway_session_id

        logger.info(
            f"Multi-tier sessions - Main: {session_id}, MCP: {mcp_session}, "
            f"MultiAgent: {multi_agent_session}, Gateway: {gateway_session}"
        )

        # Multi-Agent Session Lifecycle Management (Phase 3)
        multi_agent_context = {}
        if multi_agent_session:
            logger.info(
                f"Setting up multi-agent session lifecycle: {multi_agent_session}"
            )
            # Link multi-agent session to Response API session
            multi_agent_context = {
                "multi_agent_session_id": multi_agent_session,
                "linked_response_session": session_id,
                "multi_agent_enabled": True,
                "team_management": True,
            }

        # Get or create agent from pool with session-level singleton checkpointer
        # The hybrid service uses MultiTierSessionManager for agent pooling,
        # ensuring each agent owns its checkpointer for the lifetime of the pooled session
        request_context = {
            "thread_id": session_id,
            "session_id": session_id,
            "mcp_session_id": mcp_session,
            "multi_agent_session_id": multi_agent_session,
            "gateway_session_id": gateway_session,
            "user_credentials": user,
            "interaction_type": "response_api",
            "http_request_context": request_ctx,  # Thread request context for URL generation
        }

        # Get pooled agent with session-level checkpointer (Phase 2 refactor)
        agent = await hybrid_service.invoke_agent_openai_compat(request_context)

        logger.info(
            f"Using pooled agent for session: {session_id} (checkpointer: {id(agent.checkpointer)})"
        )

        # Convert messages to conversation format and extract current input
        chat_history = []
        input_text = "Hello"

        if request.messages and len(request.messages) > 0:
            # Convert all but the last message to chat history
            for i, msg in enumerate(request.messages[:-1]):
                chat_history.append(
                    {"role": msg.get("role", "user"), "content": msg.get("content", "")}
                )

            # Use the last message as the current input
            last_msg = request.messages[-1]
            input_text = last_msg.get("content", "Hello")

            # Session-aware file uploads: Files are now registered at upload time
            # with session_id, so no need to parse prompt text for file references.
            # The agent can access files via the session context automatically.

        # Create session context for handlers (Phase 3 Enhanced)
        session_context = {
            "main_session": session_id,
            "mcp_session": mcp_session,
            "multi_agent_session": multi_agent_session,
            "gateway_session": gateway_session,
            "multi_agent_context": multi_agent_context,  # Phase 3: Multi-agent lifecycle
            "user_id": user.user_id,  # Add user context for file ownership
            "username": user.username,
        }

        if request.stream:
            return await _handle_streaming_completion(
                agent, input_text, session_context, request, chat_history
            )
        else:
            return await _handle_non_streaming_completion(
                agent, input_text, session_context, request, chat_history
            )

    except Exception as e:
        if _is_content_filter_error(e):
            logger.warning(f"Content filter triggered for request: {type(e).__name__}")
            error_response = OpenAIErrorFormatter.format_error(
                message="Your request was filtered by the content safety system. Please rephrase your input.",
                type="invalid_request_error",
                code="content_filter",
            )
            raise HTTPException(status_code=400, detail=error_response)
        logger.error(f"Error processing Response API completion: {e}", exc_info=True)
        error_response = OpenAIErrorFormatter.format_error(
            message="An internal error occurred while processing your request.",
            type="internal_server_error",
            code="completion_error",
        )
        raise HTTPException(status_code=500, detail=error_response)


async def _handle_non_streaming_completion(
    agent: ScientificWorkflowAgent,
    input_text: str,
    session_context: Dict[str, str],
    request: ResponseRequest,
    chat_history: List[Dict[str, str]] = None,
) -> ResponseCompletion:
    """Handle non-streaming response completion."""

    try:
        # Execute the agent with multi-tier session context
        result = await agent.ainvoke(
            input_text=input_text,
            thread_id=session_context["main_session"],
            context={
                "api_type": "response",
                "original_request": request.model_dump(),
                "chat_history": chat_history or [],
                "session_hierarchy": session_context,
            },
        )

        # Format the response in OpenAI Response API format
        completion_id = f"resp_{uuid.uuid4().hex[:24]}"
        created_time = int(time.time())

        # Extract the response content and full graph state
        if isinstance(result, dict) and "output" in result:
            content = result["output"]
            full_graph_state = result.get("full_graph_state") or {}  # Handle None case
        elif isinstance(result, str):
            content = result
            full_graph_state = {}
        else:
            content = str(result)
            full_graph_state = {}

        # Phase 3B: Extract fork metadata from graph state
        forked_session_id = full_graph_state.get("forked_session_id") if full_graph_state else None
        fork_metadata_dict = full_graph_state.get("fork_metadata") if full_graph_state else None

        # Log fork event if detected
        if forked_session_id and fork_metadata_dict:
            logger.info(
                f"[FORK_PROPAGATION] Session forked: {session_context['main_session']} -> {forked_session_id}, "
                f"generation={fork_metadata_dict.get('generation')}, "
                f"reason={fork_metadata_dict.get('fork_reason')}"
            )

        # Extract plots from full_tool_outputs for Response API client consumption
        tool_outputs_with_plots = []
        if full_graph_state and "full_tool_outputs" in full_graph_state:
            full_outputs = full_graph_state["full_tool_outputs"]
            logger.info(
                f"Processing {len(full_outputs)} full tool outputs for plot extraction"
            )

            for idx, output in enumerate(full_outputs):
                if isinstance(output, dict) and "plots" in output and output["plots"]:
                    # Found execute_code output with plots
                    logger.info(
                        f"Found {len(output['plots'])} plots in tool output {idx}"
                    )
                    tool_outputs_with_plots.append(
                        {
                            "id": f"plot_output_{idx}",
                            "type": "function",
                            "function": {
                                "name": "execute_code",
                                "output": json.dumps(
                                    output
                                ),  # Include full output with plots
                            },
                        }
                    )

        # Process tool calls from the full graph state to update chat history
        if full_graph_state and "messages" in full_graph_state:
            messages = full_graph_state["messages"]

            # Extract and save full tool outputs if present
            full_tool_outputs = full_graph_state.get("full_tool_outputs", [])
            if full_tool_outputs:
                # Save full outputs to database for debugging/audit
                try:
                    # Use agent's session-level checkpointer (Phase 2 refactor)
                    # Avoids creating per-request AsyncPostgresSaver and connection leak
                    await agent.checkpointer.save_tool_outputs(
                        thread_id=session_context["main_session"],
                        checkpoint_id=f"resp_{uuid.uuid4().hex[:24]}",
                        full_outputs=full_tool_outputs,
                        config={
                            "configurable": {
                                "session_id": session_context.get("main_session"),
                                "mcp_session_id": session_context.get("mcp_session"),
                                "multi_agent_session_id": session_context.get(
                                    "multi_agent_session"
                                ),
                            }
                        },
                    )
                    logger.info(
                        f"Saved {len(full_tool_outputs)} full tool outputs to database"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to save tool outputs to database: {e}", exc_info=True
                    )
                    # Continue processing even if save fails

            # Format messages for OpenAI compatibility and update chat history
            for msg in messages:
                # Check for AI/assistant messages with tool calls
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    # Add assistant message with tool calls to history
                    tool_calls_formatted = []
                    for tool_call in msg.tool_calls:
                        if hasattr(tool_call, "id") and hasattr(tool_call, "function"):
                            tool_calls_formatted.append(
                                {
                                    "id": (
                                        tool_call.id
                                        if hasattr(tool_call, "id")
                                        else tool_call.get("id")
                                    ),
                                    "type": "function",
                                    "function": {
                                        "name": (
                                            tool_call.function.name
                                            if hasattr(tool_call.function, "name")
                                            else tool_call["function"]["name"]
                                        ),
                                        "arguments": (
                                            tool_call.function.arguments
                                            if hasattr(tool_call.function, "arguments")
                                            else tool_call["function"]["arguments"]
                                        ),
                                    },
                                }
                            )

                    if tool_calls_formatted and chat_history is not None:
                        chat_history.append(
                            {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": tool_calls_formatted,
                            }
                        )

                # Check for tool response messages
                elif hasattr(msg, "type") and msg.type == "tool":
                    # Add tool message to history
                    if chat_history is not None:
                        tool_msg = {
                            "role": "tool",
                            "tool_call_id": (
                                msg.tool_call_id
                                if hasattr(msg, "tool_call_id")
                                else msg.name
                            ),
                            "content": (
                                msg.content if hasattr(msg, "content") else str(msg)
                            ),
                        }
                        # Truncate large tool outputs for context protection
                        if len(tool_msg["content"]) > 5000:
                            tool_msg["content"] = (
                                tool_msg["content"][:2000]
                                + f"\n\n... [Truncated {len(tool_msg['content']) - 4000} chars] ...\n\n"
                                + tool_msg["content"][-2000:]
                            )
                        chat_history.append(tool_msg)

        response_choice = ResponseChoice(
            index=0,
            message=ResponseMessage(
                role="assistant",
                content=content,
                tool_outputs=(
                    tool_outputs_with_plots if tool_outputs_with_plots else None
                ),
            ),
            finish_reason="stop",
        )

        if tool_outputs_with_plots:
            logger.info(
                f"Response includes {len(tool_outputs_with_plots)} tool_outputs with plot data"
            )

        # Estimate token usage (simplified)
        prompt_tokens = len(input_text.split())
        completion_tokens = len(content.split())
        total_tokens = prompt_tokens + completion_tokens

        # Phase 2: Persist messages to database (non-blocking)
        if os.getenv("SESSION_PERSISTENCE_ENABLED", "false").lower() == "true":
            try:
                session_id = session_context["main_session"]

                # Get next message index
                message_index = await _get_next_message_index(session_id)

                # Extract tool call IDs from full graph state
                tool_call_ids = []
                if full_graph_state and "messages" in full_graph_state:
                    for msg in full_graph_state["messages"]:
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            tool_call_ids.extend(
                                [
                                    tc.id if hasattr(tc, "id") else tc.get("id", "")
                                    for tc in msg.tool_calls
                                ]
                            )

                # Save user message
                await hybrid_service.session_manager.persistence.save_message(
                    session_id=session_id,
                    message_role="user",
                    message_content=input_text,
                    message_index=message_index,
                    context_layer="active",
                    message_metadata={"source": "response_api", "api_type": "response"},
                )
                logger.debug(
                    f"Persisted user message to session {session_id} at index {message_index}"
                )

                # Save assistant message
                await hybrid_service.session_manager.persistence.save_message(
                    session_id=session_id,
                    message_role="assistant",
                    message_content=content,
                    message_index=message_index + 1,
                    tool_call_ids=tool_call_ids if tool_call_ids else None,
                    has_tool_outputs=bool(tool_outputs_with_plots),
                    context_layer="active",
                    message_metadata={
                        "source": "response_api",
                        "api_type": "response",
                        "completion_id": completion_id,
                        "model": request.model,
                        "tool_output_count": (
                            len(tool_outputs_with_plots)
                            if tool_outputs_with_plots
                            else 0
                        ),
                    },
                )
                logger.debug(
                    f"Persisted assistant message to session {session_id} at index {message_index + 1}"
                )

                # Update session cost tracking
                estimated_cost = _calculate_cost(total_tokens, request.model)
                await hybrid_service.session_manager.persistence.update_session_cost(
                    session_id=session_id, tokens=total_tokens, cost=estimated_cost
                )
                logger.info(
                    f"Session {session_id}: Persisted 2 messages, "
                    f"tokens={total_tokens}, cost=${estimated_cost:.6f}"
                )

            except Exception as e:
                # Non-blocking: Log error but don't fail the response
                logger.error(
                    f"Failed to persist messages for session {session_context['main_session']}: {e}",
                    exc_info=True,
                )

        # Phase 3B: Build session_fork metadata if fork occurred
        session_fork = None
        if forked_session_id and fork_metadata_dict:
            session_fork = SessionForkMetadata(
                forked_session_id=forked_session_id,
                parent_session_id=fork_metadata_dict.get("parent_session_id", ""),
                generation=fork_metadata_dict.get("generation", 0),
                fork_reason=fork_metadata_dict.get("fork_reason", "unknown"),
                bootstrap_message_count=fork_metadata_dict.get(
                    "bootstrap_message_count", 0
                ),
            )
            logger.info(
                f"[FORK_METADATA_RESPONSE] Including fork metadata in response: "
                f"forked_session={forked_session_id}, generation={session_fork.generation}"
            )

        return ResponseCompletion(
            id=completion_id,
            object="response.completion",
            created=created_time,
            model=request.model,
            choices=[response_choice],
            usage=ResponseUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ),
            session_fork=session_fork,  # Phase 3B: Fork metadata (None if no fork)
        )

    except Exception as e:
        error_str = str(e)
        logger.error(f"Error in non-streaming completion: {e}", exc_info=True)

        # Check for context length errors specifically
        if (
            "context_length_exceeded" in error_str
            or "maximum context length" in error_str
        ):
            # Extract token information if available
            import re

            token_match = re.search(r"(\d+)\s+tokens.*?(\d+)\s+tokens", error_str)

            if token_match:
                limit, actual = token_match.groups()
                error_message = (
                    f"Request too large: The model supports up to {limit} tokens, "
                    f"but your request contains {actual} tokens. "
                    f"Please reduce the document size or conversation length."
                )
            else:
                error_message = (
                    "Request too large: The document or conversation exceeds the model's context limit. "
                    "Please use a smaller document or clear the conversation history."
                )

            # Return 413 (Payload Too Large) instead of 500
            error_response = OpenAIErrorFormatter.format_error(
                message=error_message,
                type="invalid_request_error",
                code="context_length_exceeded",
            )
            raise HTTPException(status_code=413, detail=error_response)

        # For other errors, use the existing error handling
        error_response = OpenAIErrorFormatter.format_error(
            message=f"Completion failed: {str(e)}",
            type="internal_server_error",
            code="completion_failed",
        )
        raise HTTPException(status_code=500, detail=error_response)


async def _handle_streaming_completion(
    agent: ScientificWorkflowAgent,
    input_text: str,
    session_context: Dict[str, str],
    request: ResponseRequest,
    chat_history: List[Dict[str, str]] = None,
) -> StreamingResponse:
    """Handle streaming response completion."""

    async def generate_stream():
        try:
            completion_id = f"resp_{uuid.uuid4().hex[:24]}"
            created_time = int(time.time())

            # Start the agent execution in the background
            result_task = asyncio.create_task(
                agent.ainvoke(
                    input_text=input_text,
                    thread_id=session_context["main_session"],
                    context={
                        "api_type": "response",
                        "original_request": request.model_dump(),
                        "chat_history": chat_history or [],
                        "session_hierarchy": session_context,
                    },
                )
            )

            # Send initial response
            initial_chunk = {
                "id": completion_id,
                "object": "response.completion.chunk",
                "created": created_time,
                "model": request.model,
                "choices": [
                    {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                ],
            }
            initial_json = json.dumps(initial_chunk)
            logger.info(f"🔄 STREAMING DEBUG: Sending initial chunk: {initial_json}")
            yield f"data: {initial_json}\n\n"

            # Poll for SSE notifications while agent executes
            # This enables real-time file redirect notifications
            from ...scientific_workflow.sse_notifications import get_pending_notifications, format_sse_message

            while not result_task.done():
                # Check for pending notifications
                notifications = await get_pending_notifications()
                for notification in notifications:
                    event_type = notification["event"]
                    event_data = notification["data"]

                    # Emit SSE notification
                    sse_message = format_sse_message(event_type, event_data)
                    logger.info(f"[STREAMING_SSE] Emitting notification: {event_type}")
                    yield sse_message

                # Small delay to avoid busy-wait
                await asyncio.sleep(0.1)

            # Wait for completion and stream the result
            # Note: For true streaming, we'd need to modify the agent to support streaming
            # For now, we'll wait for completion and send it in chunks
            result = await result_task

            # Check for any final notifications after completion
            final_notifications = await get_pending_notifications()
            for notification in final_notifications:
                event_type = notification["event"]
                event_data = notification["data"]
                sse_message = format_sse_message(event_type, event_data)
                logger.info(f"[STREAMING_SSE] Emitting final notification: {event_type}")
                yield sse_message

            # Extract content
            if isinstance(result, dict) and "output" in result:
                content = result["output"]
                full_graph_state = result.get("full_graph_state", {})
            elif isinstance(result, str):
                content = result
                full_graph_state = {}
            else:
                content = str(result)
                full_graph_state = {}

            # Phase 3B: Extract fork metadata from graph state (streaming)
            forked_session_id = full_graph_state.get("forked_session_id")
            fork_metadata_dict = full_graph_state.get("fork_metadata")

            # Log fork event if detected
            if forked_session_id and fork_metadata_dict:
                logger.info(
                    f"[FORK_PROPAGATION_STREAMING] Session forked: {session_context['main_session']} -> {forked_session_id}, "
                    f"generation={fork_metadata_dict.get('generation')}, "
                    f"reason={fork_metadata_dict.get('fork_reason')}"
                )

            # Phase 2: Persist messages to database (non-blocking, before streaming)
            # Note: Persist early to ensure data is saved even if client disconnects during streaming
            if os.getenv("SESSION_PERSISTENCE_ENABLED", "false").lower() == "true":
                try:
                    session_id = session_context["main_session"]

                    # Get next message index
                    message_index = await _get_next_message_index(session_id)

                    # Extract tool call IDs from full graph state
                    tool_call_ids = []
                    if full_graph_state and "messages" in full_graph_state:
                        for msg in full_graph_state["messages"]:
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                tool_call_ids.extend(
                                    [
                                        tc.id if hasattr(tc, "id") else tc.get("id", "")
                                        for tc in msg.tool_calls
                                    ]
                                )

                    # Save user message
                    await hybrid_service.session_manager.persistence.save_message(
                        session_id=session_id,
                        message_role="user",
                        message_content=input_text,
                        message_index=message_index,
                        context_layer="active",
                        message_metadata={
                            "source": "response_api",
                            "api_type": "response",
                            "streaming": True,
                        },
                    )
                    logger.debug(
                        f"Persisted user message to session {session_id} at index {message_index} (streaming)"
                    )

                    # Save assistant message
                    await hybrid_service.session_manager.persistence.save_message(
                        session_id=session_id,
                        message_role="assistant",
                        message_content=content,
                        message_index=message_index + 1,
                        tool_call_ids=tool_call_ids if tool_call_ids else None,
                        context_layer="active",
                        message_metadata={
                            "source": "response_api",
                            "api_type": "response",
                            "streaming": True,
                            "completion_id": completion_id,
                            "model": request.model,
                        },
                    )
                    logger.debug(
                        f"Persisted assistant message to session {session_id} at index {message_index + 1} (streaming)"
                    )

                    # Update session cost tracking (simplified token estimate)
                    prompt_tokens = len(input_text.split())
                    completion_tokens = len(content.split())
                    total_tokens = prompt_tokens + completion_tokens
                    estimated_cost = _calculate_cost(total_tokens, request.model)

                    await hybrid_service.session_manager.persistence.update_session_cost(
                        session_id=session_id, tokens=total_tokens, cost=estimated_cost
                    )
                    logger.info(
                        f"Session {session_id}: Persisted 2 messages (streaming), "
                        f"tokens={total_tokens}, cost=${estimated_cost:.6f}"
                    )

                except Exception as e:
                    # Non-blocking: Log error but don't fail the stream
                    logger.error(
                        f"Failed to persist messages for streaming session {session_context['main_session']}: {e}",
                        exc_info=True,
                    )

            # Split content into chunks for streaming effect
            words = content.split()
            chunk_size = max(1, len(words) // 10)  # Send in ~10 chunks

            for i in range(0, len(words), chunk_size):
                chunk_words = words[i : i + chunk_size]
                chunk_content = " ".join(chunk_words)
                if i + chunk_size < len(words):
                    chunk_content += " "

                chunk = {
                    "id": completion_id,
                    "object": "response.completion.chunk",
                    "created": created_time,
                    "model": request.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": chunk_content},
                            "finish_reason": None,
                        }
                    ],
                }
                chunk_json = json.dumps(chunk)
                logger.info(f"🔄 STREAMING DEBUG: Sending content chunk: {chunk_json}")
                yield f"data: {chunk_json}\n\n"
                await asyncio.sleep(0.1)  # Small delay for streaming effect

            # Send final chunk with fork metadata (Phase 3B)
            final_chunk = {
                "id": completion_id,
                "object": "response.completion.chunk",
                "created": created_time,
                "model": request.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }

            # Phase 3B: Add fork metadata to final chunk if fork occurred
            if forked_session_id and fork_metadata_dict:
                final_chunk["session_fork"] = {
                    "forked_session_id": forked_session_id,
                    "parent_session_id": fork_metadata_dict.get(
                        "parent_session_id", ""
                    ),
                    "generation": fork_metadata_dict.get("generation", 0),
                    "fork_reason": fork_metadata_dict.get("fork_reason", "unknown"),
                    "bootstrap_message_count": fork_metadata_dict.get(
                        "bootstrap_message_count", 0
                    ),
                }
                logger.info(
                    f"[FORK_METADATA_STREAMING] Including fork metadata in final chunk: "
                    f"forked_session={forked_session_id}, generation={fork_metadata_dict.get('generation')}"
                )

            final_json = json.dumps(final_chunk)
            logger.info(f"🔄 STREAMING DEBUG: Sending final chunk: {final_json}")
            yield f"data: {final_json}\n\n"
            logger.info(f"🔄 STREAMING DEBUG: Sending [DONE] marker")
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Error in streaming completion: {e}", exc_info=True)

            # Check if it's a client disconnection error - if so, just log and exit gracefully
            error_msg = str(e).lower()
            if "client has been closed" in error_msg or "connection" in error_msg:
                logger.warning(f"Client disconnected during streaming: {e}")
                # Send [DONE] marker even if client disconnected
                try:
                    yield "data: [DONE]\n\n"
                except Exception:
                    # If we can't even send [DONE], client is definitely gone
                    logger.debug("Client fully disconnected, stopping stream")
                return

            # For other errors, send error chunk then [DONE]
            error_chunk = {"error": {"message": str(e), "type": "internal_error"}}
            error_json = json.dumps(error_chunk)
            logger.error(f"🔄 STREAMING DEBUG: Sending error chunk: {error_json}")
            try:
                yield f"data: {error_json}\n\n"
                yield "data: [DONE]\n\n"
            except Exception:
                logger.debug("Failed to send error response to client")

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/models")
async def list_response_models(user: AuthCredentials = Depends(get_forwarded_user)):
    """
    List available models for the Response API.

    Returns the same models as the Assistant API but formatted for Response API usage.
    """
    logger.info(
        f"[ORCHESTRATION_SERVICE] Listing Response API models for user: {user.username}"
    )

    # Return the same models as the main models endpoint but with Response API context
    models_data = {
        "object": "list",
        "data": [
            {
                "id": "agentic-framework:scientific-agent-v1",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "agentic-framework",
                "capabilities": [
                    "chat",
                    "function_calling",
                    "streaming",
                    "bioinformatics_tools",
                    "web_search",
                    "code_execution",
                ],
                "api_support": ["response", "assistant"],
                "description": "Multi-modal scientific research assistant with comprehensive tool access",
            },
            {
                "id": "agentic-framework:general-agent-v1",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "agentic-framework",
                "capabilities": [
                    "chat",
                    "function_calling",
                    "streaming",
                    "general_tools",
                ],
                "api_support": ["response", "assistant"],
                "description": "General-purpose conversational agent with basic tool access",
            },
        ],
    }

    return models_data
