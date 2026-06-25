"""
Observability Factory for Multi-Stream Architecture Monitoring

This module provides a unified interface for integrating various observability
backends (Langfuse, Langsmith, etc.) with the ADEPT framework's multi-stream
architecture. It consolidates checkpoint tracking, tool output monitoring,
and session management into a single abstraction layer.

Session 14 Part 8: Created to support future observability integration
as recommended during the Response API multi-stream fix implementation.
"""

import os
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

# Configurable output truncation for tool observability.
# Controls how much tool output text flows through the observability pipeline
# and into backends like Langfuse/ClickHouse.
#
# OBSERVABILITY_TRUNCATE_OUTPUT: "true" (default) to cap output, "false" for full output
# OBSERVABILITY_FULL_OUTPUT_LIMIT: max chars for the "full" output field (default 2000)
# OBSERVABILITY_TRUNCATED_OUTPUT_LIMIT: max chars for the "truncated" preview field (default 500)
# output_size always stores the real length (integer) for analytics.
OBSERVABILITY_TRUNCATE_OUTPUT = os.getenv(
    "OBSERVABILITY_TRUNCATE_OUTPUT", "true"
).lower() in ("true", "1", "yes")
OBSERVABILITY_FULL_OUTPUT_LIMIT = int(
    os.getenv("OBSERVABILITY_FULL_OUTPUT_LIMIT", "2000")
)
OBSERVABILITY_TRUNCATED_OUTPUT_LIMIT = int(
    os.getenv("OBSERVABILITY_TRUNCATED_OUTPUT_LIMIT", "500")
)


def truncate_for_observability(output: str) -> tuple:
    """Apply configurable truncation to tool output for observability tracking.

    Returns (full_output, truncated_output) tuple. When truncation is disabled,
    both fields contain the complete output.
    """
    if not OBSERVABILITY_TRUNCATE_OUTPUT:
        return output, output
    return (
        output[:OBSERVABILITY_FULL_OUTPUT_LIMIT],
        output[:OBSERVABILITY_TRUNCATED_OUTPUT_LIMIT],
    )


class ObservabilityBackend(Enum):
    """Supported observability backends."""

    LANGFUSE = "langfuse"
    LANGSMITH = "langsmith"
    CUSTOM = "custom"
    NONE = "none"


class ObservabilityProvider(ABC):
    """Abstract base class for observability providers."""

    @abstractmethod
    async def track_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
        checkpoint_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track checkpoint save/load operations."""
        pass

    @abstractmethod
    async def track_tool_output(
        self,
        thread_id: str,
        checkpoint_id: str,
        tool_name: str,
        full_output: Any,
        truncated_output: Any,
        output_size: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track tool output with both full and truncated versions."""
        pass

    @abstractmethod
    async def track_session(
        self,
        session_id: str,
        mcp_session_id: Optional[str] = None,
        multi_agent_session_id: Optional[str] = None,
        gateway_session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track multi-tier session creation and lifecycle."""
        pass

    @abstractmethod
    async def track_token_usage(
        self,
        thread_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        metadata: Optional[Dict[str, Any]] = None,
        session_context: Optional[Dict[str, Optional[str]]] = None,
    ) -> None:
        """Track token usage for cost monitoring.

        Args:
            thread_id: Primary session ID (Tier 1)
            model: Model name
            input_tokens: Input token count
            output_tokens: Output token count
            total_tokens: Total token count
            metadata: Additional metadata
            session_context: Complete session hierarchy (Phase 4)
        """
        pass

    @abstractmethod
    async def track_error(
        self,
        thread_id: str,
        error_type: str,
        error_message: str,
        stack_trace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track errors and exceptions."""
        pass

    @abstractmethod
    async def flush(self) -> None:
        """Flush any pending events to the backend."""
        pass


class LangfuseProvider(ObservabilityProvider):
    """Langfuse observability provider implementation.

    This provider integrates with Langfuse's observability platform, supporting:
    - Distributed tracing with traces, spans, and generations
    - Multi-modal observability (text, images, audio)
    - Token usage and cost tracking
    - Session and user tracking
    - Nested trace hierarchies for complex workflows

    Langfuse concepts mapped to ADEPT:
    - Trace: Complete request/response cycle (thread)
    - Span: Individual operation (tool call, checkpoint save)
    - Generation: LLM call with token tracking
    - Event: Discrete occurrences (errors, milestones)
    - Score: Quality metrics (not yet implemented)
    """

    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None):
        """Initialize Langfuse provider.

        Args:
            api_key: Langfuse public key (defaults to LANGFUSE_PUBLIC_KEY env var)
            api_url: Langfuse API URL (defaults to LANGFUSE_HOST env var)
        """
        # Langfuse uses PUBLIC_KEY and SECRET_KEY, not API_KEY
        self.public_key = api_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        self.secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        self.host = api_url or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        self.client = None
        self.current_trace_id = None

        if self.public_key and self.secret_key:
            try:
                from langfuse import Langfuse

                self.client = Langfuse(
                    public_key=self.public_key,
                    secret_key=self.secret_key,
                    host=self.host,
                )
                logger.info("Langfuse observability provider initialized")
            except ImportError:
                logger.warning(
                    "Langfuse package not installed. Install with: pip install langfuse"
                )
            except Exception as e:
                logger.error(
                    f"Failed to initialize Langfuse client: {e}", exc_info=True
                )

    async def track_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
        checkpoint_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track checkpoint operations in Langfuse.

        Uses update_current_trace() to attach checkpoint metadata to the current
        trace context created by @observe decorator (same pattern as track_session).
        """
        if not self.client:
            return

        try:
            # Build checkpoint metadata and filter out None values
            checkpoint_metadata = {
                "checkpoint_id": checkpoint_id,
                "checkpoint_size": len(json.dumps(checkpoint_data)),
                "has_tool_outputs": "full_tool_outputs" in checkpoint_data,
                "checkpoint_thread_id": thread_id,
                **(metadata or {}),
            }
            # Filter out None values
            filtered_metadata = {
                k: v for k, v in checkpoint_metadata.items() if v is not None
            }

            # Use update_current_trace() to attach metadata to the current trace
            # This requires being inside an @observe decorated function context
            self.client.update_current_trace(metadata=filtered_metadata)
            logger.debug(
                f"[LANGFUSE_TRACK] Successfully tracked checkpoint {checkpoint_id}"
            )
        except Exception as e:
            # Silently log at debug level since checkpoints happen frequently
            # and we don't want to spam logs if there's no @observe context
            logger.debug(
                f"Could not track checkpoint in Langfuse (may not be in @observe context): {e}"
            )

    async def track_tool_output(
        self,
        thread_id: str,
        checkpoint_id: str,
        tool_name: str,
        full_output: Any,
        truncated_output: Any,
        output_size: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track tool outputs with size metrics."""
        if not self.client:
            return

        try:
            # Create an event for the tool output using Langfuse v3 API
            self.client.create_event(
                name=f"tool_output_{tool_name}",
                metadata={
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                    "tool_name": tool_name,
                    "full_output_size": output_size,
                    "truncated_output_size": len(str(truncated_output)),
                    "truncation_ratio": len(str(truncated_output))
                    / max(output_size, 1),
                    **(metadata or {}),
                },
            )
        except Exception as e:
            logger.error(f"Failed to track tool output in Langfuse v3: {e}")

    async def track_session(
        self,
        session_id: str,
        mcp_session_id: Optional[str] = None,
        multi_agent_session_id: Optional[str] = None,
        gateway_session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track multi-tier session hierarchy."""
        logger.debug(
            f"[LANGFUSE_TRACK] track_session() called, client exists: {self.client is not None}"
        )
        if not self.client:
            logger.warning("[LANGFUSE_TRACK] Skipping track_session - client is None")
            return

        try:
            logger.debug(
                f"[LANGFUSE_TRACK] Updating trace with session_id: {session_id}"
            )
            # Use update_current_trace() instead of trace() to attach metadata
            # to the trace created by @observe decorator

            # Build metadata dict and filter out None values
            # CRITICAL: LangFuse filters out None values, so we need to exclude them explicitly
            # to ensure all expected fields appear in traces (Phase 1 E2E fix)
            trace_metadata = {
                "session_id": session_id,
                "mcp_session_id": mcp_session_id,
                "multi_agent_session_id": multi_agent_session_id,
                "gateway_session_id": gateway_session_id,
                **(metadata or {}),
            }
            # Filter out None values to ensure fields with actual values are preserved
            filtered_metadata = {
                k: v for k, v in trace_metadata.items() if v is not None
            }

            self.client.update_current_trace(
                session_id=session_id, metadata=filtered_metadata
            )
            logger.debug("[LANGFUSE_TRACK] Successfully updated current trace")
        except Exception as e:
            logger.error(
                f"[LANGFUSE_TRACK] Failed to track session in Langfuse: {e}",
                exc_info=True,
            )

    async def track_token_usage(
        self,
        thread_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        metadata: Optional[Dict[str, Any]] = None,
        session_context: Optional[Dict[str, Optional[str]]] = None,
    ) -> None:
        """Track token usage for cost analysis using Langfuse v3 API.

        Uses Pattern 3: propagate_attributes + context manager (validated working pattern).
        This correctly sets trace-level sessionId for REST API queryability.

        Args:
            thread_id: Primary session ID (Tier 1)
            model: Model name
            input_tokens: Input token count
            output_tokens: Output token count
            total_tokens: Total token count
            metadata: Additional metadata
            session_context: Complete session hierarchy (Phase 4) with keys:
                - session_id (Tier 1)
                - mcp_session_id (Tier 2)
                - multi_agent_session_id (Tier 3)
                - gateway_session_id (Tier 4)
                - user_id
                - username
                - interaction_type
        """
        if not self.client:
            return

        try:
            from langfuse import propagate_attributes

            # Phase 4: Extract session hierarchy and merge into metadata
            session_ctx = session_context or {}

            # Build enhanced metadata with all session tiers
            enhanced_metadata = metadata.copy() if metadata else {}
            enhanced_metadata.update({
                "adept_session_id": session_ctx.get("session_id") or thread_id,
                "adept_mcp_session_id": session_ctx.get("mcp_session_id"),
                "adept_multi_agent_session_id": session_ctx.get("multi_agent_session_id"),
                "adept_gateway_session_id": session_ctx.get("gateway_session_id"),
                "adept_user_id": session_ctx.get("user_id"),
                "adept_username": session_ctx.get("username"),
                "adept_interaction_type": session_ctx.get("interaction_type", "direct_user"),
            })

            # Remove None values to keep metadata clean
            enhanced_metadata = {k: v for k, v in enhanced_metadata.items() if v is not None}

            # Pattern 3: Use propagate_attributes to set session_id at trace level
            # This makes traces queryable via GET /api/public/traces?sessionId={thread_id}
            with propagate_attributes(session_id=thread_id):
                with self.client.start_as_current_observation(
                    as_type="generation",
                    name="llm_call",
                    model=model,
                ) as generation:
                    generation.update(
                        usage_details={
                            "input": input_tokens,
                            "output": output_tokens,
                            "total": total_tokens,
                        },
                        metadata=enhanced_metadata,  # Enhanced with session hierarchy
                    )

                # Phase 5: Also set metadata at trace level for REST API queryability
                # This makes the adept_* fields available in GET /api/public/traces response
                self.client.update_current_trace(metadata=enhanced_metadata)

            # Context manager auto-flushes on exit
        except Exception as e:
            logger.error(f"Failed to track token usage in Langfuse v3: {e}")

    async def track_error(
        self,
        thread_id: str,
        error_type: str,
        error_message: str,
        stack_trace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track errors and exceptions."""
        if not self.client:
            return

        try:
            self.client.create_event(
                name="error",
                metadata={
                    "thread_id": thread_id,
                    "error_type": error_type,
                    "error_message": error_message,
                    "stack_trace": stack_trace,
                    **(metadata or {}),
                },
                level="ERROR",
            )
        except Exception as e:
            logger.error(f"Failed to track error in Langfuse: {e}")

    async def flush(self) -> None:
        """Flush pending events to Langfuse."""
        logger.debug(
            f"[LANGFUSE_FLUSH] flush() called, client exists: {self.client is not None}"
        )
        if self.client:
            try:
                logger.debug("[LANGFUSE_FLUSH] Flushing LangFuse traces to backend...")
                self.client.flush()
                logger.info(
                    "[LANGFUSE_FLUSH] Successfully flushed LangFuse traces to backend"
                )
            except Exception as e:
                logger.error(f"[LANGFUSE_FLUSH] Failed to flush Langfuse events: {e}")
        else:
            logger.warning("[LANGFUSE_FLUSH] Skipping flush - client is None")

    async def shutdown(self) -> None:
        """Shutdown LangFuse client and flush pending traces."""
        if self.client:
            try:
                logger.debug("[LANGFUSE_SHUTDOWN] Shutting down LangFuse client...")
                self.client.shutdown()
                logger.info("[LANGFUSE_SHUTDOWN] LangFuse client shutdown complete")
            except Exception as e:
                logger.error(
                    f"[LANGFUSE_SHUTDOWN] Failed to shutdown LangFuse client: {e}"
                )


class LangsmithProvider(ObservabilityProvider):
    """Langsmith observability provider implementation."""

    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None):
        """Initialize Langsmith provider.

        Args:
            api_key: Langsmith API key (defaults to LANGSMITH_API_KEY env var)
            api_url: Langsmith API URL (defaults to LANGSMITH_API_URL env var)
        """
        self.api_key = api_key or os.getenv("LANGSMITH_API_KEY")
        self.api_url = api_url or os.getenv(
            "LANGSMITH_API_URL", "https://api.smith.langchain.com"
        )
        self.client = None

        if self.api_key:
            try:
                from langsmith import Client

                self.client = Client(api_key=self.api_key, api_url=self.api_url)
                logger.info("Langsmith observability provider initialized")
            except ImportError:
                logger.warning(
                    "Langsmith package not installed. Install with: pip install langsmith"
                )
            except Exception as e:
                logger.error(f"Failed to initialize Langsmith client: {e}")

    async def track_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
        checkpoint_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track checkpoint operations in Langsmith."""
        if not self.client:
            return

        try:
            # Create a run for the checkpoint operation
            run = self.client.create_run(
                name=f"checkpoint_{checkpoint_id}",
                run_type="checkpoint",
                inputs={"thread_id": thread_id},
                outputs={"checkpoint_id": checkpoint_id},
                extra={
                    "checkpoint_size": len(json.dumps(checkpoint_data)),
                    **(metadata or {}),
                },
            )
            self.client.update_run(run.id, end_time=datetime.utcnow())
        except Exception as e:
            logger.error(f"Failed to track checkpoint in Langsmith: {e}")

    async def track_tool_output(
        self,
        thread_id: str,
        checkpoint_id: str,
        tool_name: str,
        full_output: Any,
        truncated_output: Any,
        output_size: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track tool outputs in Langsmith."""
        if not self.client:
            return

        try:
            run = self.client.create_run(
                name=f"tool_{tool_name}",
                run_type="tool",
                inputs={
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                    "tool_name": tool_name,
                },
                outputs={
                    "output_size": output_size,
                    "truncated_size": len(str(truncated_output)),
                },
                extra=metadata,
            )
            self.client.update_run(run.id, end_time=datetime.utcnow())
        except Exception as e:
            logger.error(f"Failed to track tool output in Langsmith: {e}")

    async def track_session(
        self,
        session_id: str,
        mcp_session_id: Optional[str] = None,
        multi_agent_session_id: Optional[str] = None,
        gateway_session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track session hierarchy in Langsmith."""
        if not self.client:
            return

        try:
            self.client.create_project(
                project_name=f"session_{session_id}",
                metadata={
                    "mcp_session_id": mcp_session_id,
                    "multi_agent_session_id": multi_agent_session_id,
                    "gateway_session_id": gateway_session_id,
                    **(metadata or {}),
                },
            )
        except Exception as e:
            logger.error(f"Failed to track session in Langsmith: {e}")

    async def track_token_usage(
        self,
        thread_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        metadata: Optional[Dict[str, Any]] = None,
        session_context: Optional[Dict[str, Optional[str]]] = None,
    ) -> None:
        """Track token usage in Langsmith.

        Args:
            thread_id: Primary session ID (Tier 1)
            model: Model name
            input_tokens: Input token count
            output_tokens: Output token count
            total_tokens: Total token count
            metadata: Additional metadata
            session_context: Complete session hierarchy (Phase 4) - not used by Langsmith
        """
        if not self.client:
            return

        try:
            run = self.client.create_run(
                name=f"llm_{model}",
                run_type="llm",
                inputs={"thread_id": thread_id},
                outputs={
                    "token_usage": {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": total_tokens,
                    }
                },
                extra=metadata,
            )
            self.client.update_run(run.id, end_time=datetime.utcnow())
        except Exception as e:
            logger.error(f"Failed to track token usage in Langsmith: {e}")

    async def track_error(
        self,
        thread_id: str,
        error_type: str,
        error_message: str,
        stack_trace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track errors in Langsmith."""
        if not self.client:
            return

        try:
            run = self.client.create_run(
                name="error",
                run_type="error",
                error=f"{error_type}: {error_message}",
                inputs={"thread_id": thread_id},
                extra={"stack_trace": stack_trace, **(metadata or {})},
            )
            self.client.update_run(run.id, end_time=datetime.utcnow())
        except Exception as e:
            logger.error(f"Failed to track error in Langsmith: {e}")

    async def flush(self) -> None:
        """Flush pending events to Langsmith."""
        # Langsmith client auto-flushes
        pass


class NoOpProvider(ObservabilityProvider):
    """No-op provider for when observability is disabled."""

    async def track_checkpoint(self, *args, **kwargs) -> None:
        pass

    async def track_tool_output(self, *args, **kwargs) -> None:
        pass

    async def track_session(self, *args, **kwargs) -> None:
        pass

    async def track_token_usage(self, *args, **kwargs) -> None:
        pass

    async def track_error(self, *args, **kwargs) -> None:
        pass

    async def flush(self) -> None:
        pass


class ObservabilityFactory:
    """Factory for creating observability providers."""

    _instance: Optional["ObservabilityFactory"] = None
    _provider: Optional[ObservabilityProvider] = None

    def __new__(cls):
        """Singleton pattern to ensure single instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the factory with configured provider."""
        if self._provider is None:
            backend = os.getenv("OBSERVABILITY_BACKEND", "none").lower()
            self._provider = self._create_provider(backend)

    def _create_provider(self, backend: str) -> ObservabilityProvider:
        """Create the appropriate provider based on backend type.

        Args:
            backend: Backend type (langfuse, langsmith, none)

        Returns:
            ObservabilityProvider instance
        """
        if backend == ObservabilityBackend.LANGFUSE.value:
            return LangfuseProvider()
        elif backend == ObservabilityBackend.LANGSMITH.value:
            return LangsmithProvider()
        else:
            return NoOpProvider()

    @classmethod
    def get_provider(cls) -> ObservabilityProvider:
        """Get the singleton observability provider.

        Returns:
            The configured observability provider
        """
        factory = cls()
        return factory._provider

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance and provider.

        This is primarily used in testing to allow provider switching
        when OBSERVABILITY_BACKEND environment variable changes.
        """
        cls._instance = None
        cls._provider = None

    @classmethod
    async def track_multi_stream_operation(
        cls,
        thread_id: str,
        checkpoint_id: str,
        full_outputs: List[Dict[str, Any]],
        truncated_outputs: List[Dict[str, Any]],
        session_context: Dict[str, str],
    ) -> None:
        """Convenience method to track multi-stream operations.

        This method encapsulates the three-stream architecture tracking:
        1. Storage stream (full outputs to database)
        2. Context stream (truncated outputs to LLM)
        3. Display stream (simplified for client)

        Args:
            thread_id: Thread identifier
            checkpoint_id: Checkpoint identifier
            full_outputs: Full tool outputs for storage
            truncated_outputs: Truncated outputs for context
            session_context: Multi-tier session context
        """
        provider = cls.get_provider()

        # Track checkpoint
        await provider.track_checkpoint(
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            checkpoint_data={"full_outputs_count": len(full_outputs)},
            metadata={"session_context": session_context},
        )

        # Track each tool output
        for full, truncated in zip(full_outputs, truncated_outputs):
            tool_name = full.get("tool", "unknown")
            full_size = len(json.dumps(full))

            await provider.track_tool_output(
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                tool_name=tool_name,
                full_output=full,
                truncated_output=truncated,
                output_size=full_size,
                metadata={
                    "mcp_session_id": session_context.get("mcp_session"),
                    "multi_agent_session_id": session_context.get(
                        "multi_agent_session"
                    ),
                },
            )

        # Track session hierarchy
        await provider.track_session(
            session_id=session_context.get("main_session"),
            mcp_session_id=session_context.get("mcp_session"),
            multi_agent_session_id=session_context.get("multi_agent_session"),
            gateway_session_id=session_context.get("gateway_session"),
        )

        # Flush events
        await provider.flush()

    # Instance delegation methods for convenience (Phase 1 Instrumentation Support)
    async def track_checkpoint(self, *args, **kwargs):
        """Track a checkpoint operation (delegates to provider)."""
        await self._provider.track_checkpoint(*args, **kwargs)

    async def track_tool_output(self, *args, **kwargs):
        """Track a tool output (delegates to provider)."""
        await self._provider.track_tool_output(*args, **kwargs)

    async def track_session(self, *args, **kwargs):
        """Track a session (delegates to provider)."""
        logger.debug(
            f"[FACTORY_TRACK] ObservabilityFactory.track_session() called, delegating to provider: {type(self._provider).__name__}"
        )
        await self._provider.track_session(*args, **kwargs)
        logger.debug("[FACTORY_TRACK] Provider track_session() completed")

    async def track_token_usage(self, *args, **kwargs):
        """Track token usage (delegates to provider)."""
        await self._provider.track_token_usage(*args, **kwargs)

    async def track_error(self, *args, **kwargs):
        """Track an error (delegates to provider)."""
        await self._provider.track_error(*args, **kwargs)

    async def flush(self):
        """Flush pending events (delegates to provider)."""
        logger.debug(
            f"[FACTORY_FLUSH] ObservabilityFactory.flush() called, delegating to provider: {type(self._provider).__name__}"
        )
        await self._provider.flush()
        logger.debug("[FACTORY_FLUSH] Provider flush() completed")

    async def shutdown(self):
        """Shutdown observability provider (delegates to provider)."""
        await self._provider.shutdown()


# Convenience function for direct access
async def track_checkpoint(*args, **kwargs):
    """Track a checkpoint operation."""
    provider = ObservabilityFactory.get_provider()
    await provider.track_checkpoint(*args, **kwargs)


async def track_tool_output(*args, **kwargs):
    """Track a tool output."""
    provider = ObservabilityFactory.get_provider()
    await provider.track_tool_output(*args, **kwargs)


async def track_session(*args, **kwargs):
    """Track a session."""
    provider = ObservabilityFactory.get_provider()
    await provider.track_session(*args, **kwargs)


async def track_token_usage(*args, **kwargs):
    """Track token usage."""
    provider = ObservabilityFactory.get_provider()
    await provider.track_token_usage(*args, **kwargs)


async def track_error(*args, **kwargs):
    """Track an error."""
    provider = ObservabilityFactory.get_provider()
    await provider.track_error(*args, **kwargs)
