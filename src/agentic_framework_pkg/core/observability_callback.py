"""
LangChain Observability Callback Handler

This module provides a LangChain AsyncCallbackHandler that integrates with the
observability factory to track token usage for LangChain-based agents.

Phase 5: Session Context Propagation
- Extracts session context from LangChain config
- Captures token usage from LLM responses
- Propagates all 4 ADEPT session tiers to Langfuse
"""
import asyncio
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks.base import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from ..logger_config import get_logger
from .observability_factory import ObservabilityFactory

logger = get_logger(__name__)


class ObservabilityCallbackHandler(AsyncCallbackHandler):
    """
    LangChain callback handler for observability tracking.

    This handler captures LLM calls made through LangChain and tracks them
    in the observability backend (Langfuse, LangSmith, or NoOp).

    Key Features:
    - Captures token usage from LLM responses
    - Extracts session context from LangChain config
    - Propagates all 4 ADEPT session tiers to observability backend
    - Non-blocking error handling (doesn't disrupt agent execution)

    Usage:
        callback = ObservabilityCallbackHandler()
        config = {
            "callbacks": [callback],
            "configurable": {
                "thread_id": "session-123",
                "session_context": {
                    "session_id": "session-123",
                    "mcp_session_id": "session-123::mcp-abc",
                    "multi_agent_session_id": "multi-agent-456",
                    "gateway_session_id": "gateway-789",
                    "user_id": "user-001",
                    "username": "testuser",
                    "interaction_type": "direct_user"
                }
            }
        }
        await agent.runnable.ainvoke(input, config=config)
    """

    def __init__(self):
        """Initialize the observability callback handler."""
        super().__init__()
        self.obs_factory = ObservabilityFactory()

        # Track ongoing LLM calls by run_id
        self._llm_calls: Dict[UUID, Dict[str, Any]] = {}

    async def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Called when LLM starts running.

        Stores metadata for correlation with on_llm_end.
        """
        try:
            # Extract model name from serialized info
            model = "unknown"
            if serialized and "id" in serialized:
                # Format: ["langchain", "chat_models", "openai", "ChatOpenAI"]
                model_id = serialized.get("id", [])
                if isinstance(model_id, list) and len(model_id) > 0:
                    model = model_id[-1]  # Get the last part (e.g., "ChatOpenAI")

            # Extract session context from metadata if available
            session_context = None
            if metadata and "session_context" in metadata:
                session_context = metadata["session_context"]
            elif kwargs and "session_context" in kwargs:
                session_context = kwargs["session_context"]

            # Store for correlation with on_llm_end
            self._llm_calls[run_id] = {
                "model": model,
                "prompts": prompts,
                "metadata": metadata or {},
                "session_context": session_context,
                "parent_run_id": parent_run_id,
                "tags": tags or []
            }

            logger.debug(f"[OBSERVABILITY_CALLBACK] LLM started - run_id={run_id}, model={model}")

        except Exception as e:
            # Non-blocking: log error but don't disrupt LLM call
            logger.error(f"[OBSERVABILITY_CALLBACK] Error in on_llm_start: {e}", exc_info=True)

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """
        Called when LLM finishes running.

        Extracts token usage and tracks it in observability backend.
        """
        try:
            # Retrieve stored metadata from on_llm_start
            llm_call_info = self._llm_calls.pop(run_id, {})
            if not llm_call_info:
                logger.warning(f"[OBSERVABILITY_CALLBACK] No metadata found for run_id={run_id}")
                return

            # Extract token usage from response
            if not response.llm_output or "token_usage" not in response.llm_output:
                logger.debug(f"[OBSERVABILITY_CALLBACK] No token usage in response for run_id={run_id}")
                return

            token_usage = response.llm_output["token_usage"]
            prompt_tokens = token_usage.get("prompt_tokens", 0)
            completion_tokens = token_usage.get("completion_tokens", 0)
            total_tokens = token_usage.get("total_tokens", prompt_tokens + completion_tokens)

            # Extract model name and session context
            model = llm_call_info.get("model", "unknown")
            metadata = llm_call_info.get("metadata", {})
            session_context = llm_call_info.get("session_context")

            # Get thread_id from metadata or session_context
            thread_id = None
            if session_context and "session_id" in session_context:
                thread_id = session_context["session_id"]
            elif metadata and "thread_id" in metadata:
                thread_id = metadata["thread_id"]
            else:
                # Fallback: use run_id as thread_id
                thread_id = str(run_id)

            logger.info(
                f"[OBSERVABILITY_CALLBACK] Tracking token usage - "
                f"thread_id={thread_id}, model={model}, "
                f"prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
            )

            # Build observability metadata
            obs_metadata = {
                "source": "langchain_agent",
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "tags": llm_call_info.get("tags", []),
            }

            # Merge user metadata
            if metadata:
                obs_metadata.update(metadata)

            # Track token usage with session context
            await self.obs_factory.track_token_usage(
                thread_id=thread_id,
                model=model,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                total_tokens=total_tokens,
                metadata=obs_metadata,
                session_context=session_context  # Phase 5: Pass session context
            )

            logger.debug(f"[OBSERVABILITY_CALLBACK] Token usage tracked successfully for run_id={run_id}")

        except Exception as e:
            # Non-blocking: log error but don't disrupt agent execution
            logger.error(f"[OBSERVABILITY_CALLBACK] Error in on_llm_end: {e}", exc_info=True)

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """
        Called when LLM encounters an error.

        Cleans up tracking state.
        """
        try:
            # Clean up tracking state
            self._llm_calls.pop(run_id, None)
            logger.debug(f"[OBSERVABILITY_CALLBACK] LLM error - run_id={run_id}, error={error}")
        except Exception as e:
            logger.error(f"[OBSERVABILITY_CALLBACK] Error in on_llm_error: {e}", exc_info=True)
