"""
Streaming Tool Executor - Optional enhancement for tools that support streaming output.

This module provides an execution wrapper that uses StreamingOutputBuffer for tools
that can yield output incrementally. For tools that return complete results (current
majority), the executor falls back to standard synchronous execution.

Architecture:
- **Streaming Tools** (future enhancement): Tools that yield chunks during execution
  - Use StreamingOutputBuffer to monitor size and redirect to file if needed
  - Provide real-time feedback via SSE notifications
  - Memory-efficient handling of large outputs

- **Synchronous Tools** (current state): Tools that return complete results
  - Use existing tool_factory.execute() pattern
  - Apply _sanitize_tool_output() post-execution
  - Compatible with all existing MCP tools

mcp_session_id Injection:
  This executor injects mcp_session_id into tool_args when the tool's args_schema
  declares it. For external StructuredTools, mcp_session_id MUST be present in the
  registered args_schema (via _FRAMEWORK_INJECTED_FIELDS in external_tool_manager.py),
  otherwise LangChain's _parse_input() silently strips it during Pydantic validation
  (create_model defaults to extra="ignore"). For built-in MCPToolWrapper tools,
  args_schema is None so LangChain skips validation entirely.

Integration:
This module is imported by graph_builder.py to enable streaming when available,
without breaking existing tool execution patterns.
"""

import asyncio
from typing import Any, Dict, Optional, AsyncGenerator
from ...logger_config import get_logger
from .streaming_output_buffer import StreamingOutputBuffer
from ..tool_execution import ToolExecutionContext, ToolExecutionResult
from .sse_notifications import emit_notification, format_file_redirect_notification

logger = get_logger(__name__)


class StreamingToolExecutor:
    """
    Executor that supports both streaming and synchronous tool execution.

    Automatically detects whether a tool supports streaming and uses the
    appropriate execution strategy.
    """

    def __init__(
        self,
        tool_factory,
        mcp_session_id: Optional[str] = None,
        threshold_chars: int = 50000,
    ):
        """
        Initialize streaming tool executor.

        Args:
            tool_factory: ToolExecutionFactory instance for synchronous execution
            mcp_session_id: Session ID for ephemeral file isolation
            threshold_chars: Size threshold for file redirection (default: 50k)
        """
        self.tool_factory = tool_factory
        self.mcp_session_id = mcp_session_id
        self.threshold_chars = threshold_chars

    def is_streaming_tool(self, tool: Any) -> bool:
        """
        Check if a tool supports streaming output.

        A tool is considered streaming if it has a `stream()` or `astream()` method
        that yields chunks during execution.

        Args:
            tool: Tool instance to check

        Returns:
            True if tool supports streaming, False otherwise
        """
        return hasattr(tool, "astream") or hasattr(tool, "stream")

    async def execute(
        self,
        tool: Any,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: ToolExecutionContext,
        owner_id: Optional[str] = None,
    ) -> ToolExecutionResult:
        """
        Execute tool with optional streaming support.

        This method automatically detects whether the tool supports streaming:
        - If yes: Uses StreamingOutputBuffer for chunk-by-chunk monitoring
        - If no: Falls back to synchronous execution via tool_factory

        Args:
            tool: Tool instance to execute
            tool_name: Name of the tool (for logging and file naming)
            tool_args: Arguments to pass to the tool
            context: Execution context with session identifiers
            owner_id: User ID for file ownership

        Returns:
            ToolExecutionResult with output (may be file reference if redirected)
        """
        # Inject mcp_session_id for tools whose LangChain args_schema declares it.
        # For built-in MCPToolWrapper tools (args_schema=None), LangChain skips
        # validation and passes all fields through — MCPToolWrapper._arun() then
        # injects mcp_session_id from self.mcp_session_id (line 622).
        # For external StructuredTools, mcp_session_id must be in the registered
        # args_schema (via _FRAMEWORK_INJECTED_FIELDS in external_tool_manager.py)
        # or LangChain's _parse_input() will silently strip it during validation.
        if (
            self.mcp_session_id
            and "mcp_session_id" not in tool_args
            and (
                not hasattr(tool, "args_schema")
                or tool.args_schema is None
                or "mcp_session_id" in getattr(tool.args_schema, "model_fields", {})
            )
        ):
            tool_args = {**tool_args, "mcp_session_id": self.mcp_session_id}

        if self.is_streaming_tool(tool):
            logger.info(
                f"[STREAMING_EXECUTOR] Tool '{tool_name}' supports streaming, "
                f"using StreamingOutputBuffer"
            )
            return await self._execute_streaming(
                tool, tool_name, tool_args, context, owner_id
            )
        else:
            logger.debug(
                f"[STREAMING_EXECUTOR] Tool '{tool_name}' does not support streaming, "
                f"using synchronous execution"
            )
            return await self.tool_factory.execute(tool, tool_name, tool_args, context)

    async def _execute_streaming(
        self,
        tool: Any,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: ToolExecutionContext,
        owner_id: Optional[str] = None,
    ) -> ToolExecutionResult:
        """
        Execute a streaming tool with output monitoring.

        This method:
        1. Creates StreamingOutputBuffer with configured threshold
        2. Iterates over tool output chunks
        3. Appends each chunk to buffer (auto-redirects to file if threshold exceeded)
        4. Returns final result (either buffered content or file reference)

        Args:
            tool: Streaming tool instance
            tool_name: Name of the tool
            tool_args: Arguments to pass to the tool
            context: Execution context
            owner_id: User ID for file ownership

        Returns:
            ToolExecutionResult with output (may be file reference)
        """
        import time

        start_time = time.time()

        # Event handler for file redirect notifications
        async def handle_redirect_event(event_type: str, data: Dict[str, Any]) -> None:
            """Emit SSE notification when file redirect occurs."""
            if event_type == "redirect_started":
                logger.info(
                    f"[STREAMING_SSE] File redirect started for {tool_name}, "
                    f"emitting SSE notification"
                )
                await emit_notification(
                    "file_redirect_started",
                    format_file_redirect_notification(
                        tool_name=data["tool_name"],
                        file_id="pending",  # File ID not yet generated
                        total_chars=data["total_chars"],
                        threshold_chars=data["threshold_chars"],
                    )
                )
            elif event_type == "redirect_completed":
                logger.info(
                    f"[STREAMING_SSE] File redirect completed for {tool_name}, "
                    f"file_id={data['file_id']}"
                )
                await emit_notification(
                    "file_redirect_completed",
                    format_file_redirect_notification(
                        tool_name=data["tool_name"],
                        file_id=data["file_id"],
                        total_chars=data["total_chars"],
                        threshold_chars=data.get("threshold_chars", 50000),
                    )
                )

        # Create streaming output buffer with event callback
        buffer = StreamingOutputBuffer(
            tool_name=tool_name,
            session_id=context.mcp_session_id or "unknown",
            owner_id=owner_id,
            threshold_chars=self.threshold_chars,
            event_callback=handle_redirect_event,
        )

        try:
            # Execute tool and iterate over chunks
            if hasattr(tool, "astream"):
                # Async streaming
                async for chunk in tool.astream(tool_args):
                    chunk_str = self._chunk_to_string(chunk)
                    await buffer.append(chunk_str)
            elif hasattr(tool, "stream"):
                # Sync streaming (wrap in async)
                for chunk in tool.stream(tool_args):
                    chunk_str = self._chunk_to_string(chunk)
                    await buffer.append(chunk_str)
            else:
                # Should never reach here due to is_streaming_tool() check
                raise RuntimeError(f"Tool '{tool_name}' marked as streaming but has no stream method")

            # Finalize buffer (closes file if redirected)
            content, file_id = await buffer.finalize()
            execution_time = time.time() - start_time

            if file_id:
                # Output was redirected to file
                # content might be dict (new format with metadata) or string (legacy format)
                if isinstance(content, dict):
                    # Structured response with metadata (new format)
                    logger.info(
                        f"[STREAMING_EXECUTOR] Tool '{tool_name}' output redirected to file: {file_id} "
                        f"({buffer.total_chars:,} chars, {execution_time:.2f}s), "
                        f"metadata_fields={list(content.keys())}"
                    )
                    return ToolExecutionResult(
                        success=True,
                        result={
                            **content,  # Merge all fields including metadata
                            "file_id": file_id,  # Ensure file_id present
                            "redirected": True,
                            "total_chars": buffer.total_chars,
                        },
                        execution_time=execution_time,
                        is_async=False,
                    )
                else:
                    # Plain warning text (legacy format)
                    logger.info(
                        f"[STREAMING_EXECUTOR] Tool '{tool_name}' output redirected to file: {file_id} "
                        f"({buffer.total_chars:,} chars, {execution_time:.2f}s) [legacy format]"
                    )
                    return ToolExecutionResult(
                        success=True,
                        result={
                            "output": content,  # Plain text warning
                            "status": "completed",
                            "file_id": file_id,
                            "redirected": True,
                            "total_chars": buffer.total_chars,
                        },
                        execution_time=execution_time,
                        is_async=False,
                    )
            else:
                # Output stayed in buffer
                logger.info(
                    f"[STREAMING_EXECUTOR] Tool '{tool_name}' completed "
                    f"({buffer.total_chars:,} chars, {execution_time:.2f}s)"
                )
                return ToolExecutionResult(
                    success=True,
                    result={
                        "output": content,
                        "status": "completed",
                        "total_chars": buffer.total_chars,
                    },
                    execution_time=execution_time,
                    is_async=False,
                )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                f"[STREAMING_EXECUTOR] Tool '{tool_name}' failed: {e}",
                exc_info=True,
            )
            return ToolExecutionResult(
                success=False,
                result=None,
                error=str(e),
                execution_time=execution_time,
                is_async=False,
            )

    def _chunk_to_string(self, chunk: Any) -> str:
        """
        Convert a chunk of any type to string.

        Handles various chunk formats:
        - String: Pass through
        - Dict: Extract 'content' or 'output' field, or serialize to JSON
        - Bytes: Decode to UTF-8
        - Other: Convert to string

        Args:
            chunk: Chunk of output from streaming tool

        Returns:
            String representation of the chunk
        """
        if isinstance(chunk, str):
            return chunk
        elif isinstance(chunk, bytes):
            return chunk.decode("utf-8", errors="ignore")
        elif isinstance(chunk, dict):
            # Try to extract content from common field names
            if "content" in chunk:
                return str(chunk["content"])
            elif "output" in chunk:
                return str(chunk["output"])
            elif "text" in chunk:
                return str(chunk["text"])
            else:
                # Serialize entire dict
                import json
                return json.dumps(chunk)
        else:
            return str(chunk)


async def create_streaming_executor(
    tool_factory,
    mcp_session_id: Optional[str] = None,
    threshold_chars: Optional[int] = None,
) -> StreamingToolExecutor:
    """
    Factory function to create StreamingToolExecutor with configuration.

    Args:
        tool_factory: ToolExecutionFactory instance
        mcp_session_id: Session ID for ephemeral file isolation
        threshold_chars: Optional threshold override (default from env)

    Returns:
        Configured StreamingToolExecutor instance
    """
    import os

    # Get threshold from environment or use default
    if threshold_chars is None:
        threshold_chars = int(
            os.getenv("TOOL_OUTPUT_STREAMING_THRESHOLD", "200000")
        )

    return StreamingToolExecutor(
        tool_factory=tool_factory,
        mcp_session_id=mcp_session_id,
        threshold_chars=threshold_chars,
    )
