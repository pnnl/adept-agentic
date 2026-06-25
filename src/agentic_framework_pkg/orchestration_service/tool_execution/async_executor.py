"""
Asynchronous task manager executor for tool execution.

This executor handles ALL tools as async by default, queuing them for background
execution via asyncio.create_task. This solves the "orphaned tool_calls" error
by ensuring all tools return immediately with a task_id, maintaining OpenAI
Response API's conversational turn expectations.

Architecture:
- Returns task_id immediately in ToolMessage (completes conversation turn)
- Executes tool in background worker (asyncio.create_task)
- Stores task status/progress/result in PostgreSQL
- Provides CheckTaskStatus tool for conversational polling
- Easy migration path to Celery/RQ via factory pattern
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import psycopg

from ...logger_config import get_logger
from .base import ToolExecutionContext, ToolExecutionResult, ToolExecutionStrategy

logger = get_logger(__name__)


def unwrap_calltoolresult_if_needed(result: Any) -> Any:
    """
    Unwrap FastMCP CallToolResult objects to extract actual data.

    FastMCP tools return CallToolResult(content=[TextContent(...)]) objects.
    This function extracts the .text attribute from the first content item,
    which contains the actual JSON-serialized tool output.

    For non-CallToolResult objects (e.g., StructuredTool outputs), returns as-is.

    Background:
    - FastMCP is part of the Model Context Protocol (MCP) standard
    - CallToolResult wraps tool outputs in a standardized format
    - When stored with json.dumps(), it becomes an unparseable string like:
      "CallToolResult(content=[TextContent(type='text', text='{...}')\n])"
    - This causes agents to fail parsing CheckTaskStatus results, leading to
      infinite retry loops in plot generation and other workflows

    Args:
        result: Raw tool execution result

    Returns:
        Unwrapped result (string or dict/list) ready for JSON serialization

    See: docs/implementation-plans/SESSION_36_PHASE11_PLOT_GENERATION_RECURSION_ROOT_CAUSE.md
    """
    if hasattr(result, "__class__") and result.__class__.__name__ == "CallToolResult":
        # This is a FastMCP CallToolResult - extract the actual data
        if hasattr(result, "content") and isinstance(result.content, list):
            if len(result.content) > 0:
                first_content = result.content[0]
                if hasattr(first_content, "text"):
                    # Extract .text attribute (contains actual JSON data)
                    return first_content.text
                else:
                    # Unexpected format - convert to string as fallback
                    return str(result.content)
            else:
                # Empty content list
                return ""
        else:
            # Unexpected format - convert to string
            return str(result)
    else:
        # Not a CallToolResult (e.g., StructuredTool dict/list) - return as-is
        return result


# Tools that MUST execute synchronously (cannot be overridden)
# These tools require immediate results for workflow progression or user experience
SYNCHRONOUS_TOOLS = {
    # Multi-agent planning tools (workflow coordination)
    "CreateMultiAgentSession",       # Returns session_id for next step
    "GeneratePlanForMultiAgentTask",  # Returns plan for execution
    # ExecuteApprovedPlan removed — runs async via task queue (Session 58)
    # Plan execution (5-10 min) is non-blocking; agent gets task_id and polls via CheckTaskStatus
    "TerminateMultiAgentSession",     # Returns termination confirmation

    # RAG and Knowledge Base tools (immediate indexing and query results required)
    "process_uploaded_file",         # Index files into ChromaDB (2-30 sec)
    "ProcessFileAdvanced",           # Robust file processing with auto-detection (2-30 sec)
    # ProcessFilesBatch removed — runs async via task queue (Session 58)
    # Batch processing (30-120 sec) is non-blocking; agent polls via CheckTaskStatus
    "CreateRAGIndex",                # Create vector store from file_ids (5-30 sec)
    # CreateRAGIndexFromFolder removed — runs async via task queue (Session 58)
    # Folder→RAG workflow (60-180 sec) is non-blocking; agent polls via CheckTaskStatus
    "query_file_content",            # Vector search + LLM synthesis (1-3 sec)

    # Task management tools (quick metadata operations)
    "CheckTaskStatus",  # Query task status from database (<100ms)
    "CancelTask",       # Cancel pending/running task (<100ms)

    # Utility introspection tools (conversational flow - agent needs results immediately)
    "query_user_sessions",    # Agent needs results for next question
    "get_session_history",    # Used immediately in response
    "query_checkpoints",      # Debugging context (immediate)
    # Note: query_langfuse_telemetry and export_session_data are ASYNC (not in whitelist)
    # - Large result sets and file generation can run in background
}


class AsyncTaskManagerExecutor(ToolExecutionStrategy):
    """
    Hybrid task manager executor supporting both synchronous and asynchronous execution.

    **Default Mode (wait_for_completion=True)**: Synchronous Execution
    - Executes tools and waits for actual results
    - Returns complete results in ToolMessages (OpenAI Response API compatible)
    - Respects timeout parameter (default: 5 minutes)
    - Stores execution history in tasks table for observability

    **Optional Mode (wait_for_completion=False)**: Asynchronous Execution
    - Returns task_id immediately (non-blocking)
    - Executes tool in background worker via asyncio.create_task
    - User polls via CheckTaskStatus tool for results
    - Enables long-running operations without blocking conversation turns

    **Architecture**:
    1. Creates task record in PostgreSQL with 'pending' status
    2. Branches on wait_for_completion flag:
       - If True: Executes synchronously, returns actual result
       - If False: Launches background worker, returns task_id
    3. Updates task status: pending → running → completed/failed
    4. Stores full execution history for debugging and observability

    **OpenAI Response API Compliance**:
    Default synchronous mode ensures ToolMessages contain actual results,
    preventing "orphaned tool_calls" errors when checkpoints are saved with
    incomplete ToolMessages.

    **Future Extensibility**: Factory pattern allows easy swap to Celery/RQ.
    """

    def __init__(
        self,
        db_connection_string: str,
        retention_days: int = 30,
        wait_for_completion: bool = False,
        user_overrides: Optional[set] = None
    ):
        """
        Initialize async task manager executor.

        Args:
            db_connection_string: PostgreSQL connection string for task storage
            retention_days: Days to retain completed tasks (default: 30, user decision)
            wait_for_completion: If True, execute all tools synchronously (global override).
                               If False (default), use tool classification to determine execution mode.
            user_overrides: Set of tool names to force synchronous execution.
                          Example: {"video_processing_tool", "gitxray_tool"}
                          These tools will execute synchronously even if not in SYNCHRONOUS_TOOLS whitelist.
        """
        # Convert SQLAlchemy-style URL to psycopg3 format
        # Handles postgresql+asyncpg:// and postgresql+psycopg2:// notation
        if "+asyncpg://" in db_connection_string:
            db_connection_string = db_connection_string.replace("+asyncpg://", "://")
        elif "+psycopg2://" in db_connection_string:
            db_connection_string = db_connection_string.replace("+psycopg2://", "://")

        self.db_conn_str = db_connection_string
        self.retention_days = retention_days
        self.wait_for_completion = wait_for_completion
        self.user_overrides = user_overrides or set()
        self._background_tasks: Dict[str, asyncio.Task] = {}

    def _get_tool_name(self, tool: Any) -> str:
        """
        Extract actual tool name from tool instance.

        For MCPToolWrapper instances, use actual_tool_name attribute.
        For other tools, use class name.

        Args:
            tool: Tool instance (MCPToolWrapper or other BaseTool)

        Returns:
            Actual tool name for observability
        """
        # Check for MCPToolWrapper's actual_tool_name attribute
        # Also verify it's not None or empty string (falsy values fall back to class name)
        if hasattr(tool, "actual_tool_name") and tool.actual_tool_name:
            tool_name = tool.actual_tool_name
            logger.debug(
                f"[OBSERVABILITY] Using actual_tool_name: {tool_name} "
                f"(class: {tool.__class__.__name__})"
            )
            return tool_name

        # Fallback to class name for non-MCP tools or when actual_tool_name is None/empty
        tool_name = tool.__class__.__name__
        logger.debug(f"[OBSERVABILITY] Using class name: {tool_name}")
        return tool_name

    async def can_execute(self, tool_name: str) -> bool:
        """
        Check if this strategy can execute the given tool.

        Synchronous tools (planning + RAG) are ALWAYS exempt from async wrapping.
        User can also force specific tools to be synchronous via user_overrides.

        Args:
            tool_name: Name of the tool to execute

        Returns:
            True if tool can be async (NOT in synchronous set or user overrides)
            False if tool must be sync (in synchronous set or user overrides)
        """
        # Tier 1: Check static whitelist (ALWAYS synchronous)
        if tool_name in SYNCHRONOUS_TOOLS:
            logger.info(
                f"[TOOL_CLASSIFICATION] {tool_name} is in SYNCHRONOUS_TOOLS whitelist - "
                f"will execute synchronously (NOT wrapped by AsyncTaskManagerExecutor)"
            )
            return False

        # Tier 2: Check user overrides (dynamically configured)
        if tool_name in self.user_overrides:
            logger.info(
                f"[TOOL_CLASSIFICATION] {tool_name} has user override - "
                f"forcing synchronous execution (user preference)"
            )
            return False

        # All other tools can be async
        logger.debug(f"[TOOL_CLASSIFICATION] {tool_name} can execute asynchronously")
        return True

    async def _execute_and_wait(
        self,
        task_id: str,
        tool: Any,
        args: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> Any:
        """
        Execute tool synchronously and return actual result.

        This method executes the tool and waits for completion, returning the actual
        result instead of a task_id. This ensures OpenAI Response API compatibility
        by providing complete ToolMessages in checkpoints.

        Args:
            task_id: UUID for task tracking
            tool: Tool instance to execute
            args: Tool arguments
            context: Execution context with session identifiers

        Returns:
            The actual tool execution result

        Raises:
            Exception: If tool execution fails or times out
        """
        conn = None
        start_time = time.time()

        try:
            # Connect to database for status updates
            conn = await psycopg.AsyncConnection.connect(self.db_conn_str)

            # Update status to 'running'
            await conn.execute(
                """
                UPDATE tasks
                SET status = 'running', started_at = %s
                WHERE task_id = %s
                """,
                (datetime.utcnow(), task_id),
            )
            await conn.commit()

            logger.info(f"Task {task_id} started synchronous execution")

            # Execute tool with timeout (respects existing timeout parameter)
            raw_result = await asyncio.wait_for(
                tool.ainvoke(args),
                timeout=context.timeout,
            )

            execution_time = time.time() - start_time

            # Unwrap FastMCP CallToolResult if present
            # This extracts the actual JSON data from CallToolResult(content=[TextContent(...)])
            # Without this, json.dumps(CallToolResult) produces unparseable strings like:
            # "CallToolResult(content=[TextContent(type='text', text='{...}')\n])"
            # which causes agents to fail parsing CheckTaskStatus results
            result_to_store = unwrap_calltoolresult_if_needed(raw_result)

            # Log unwrapping operation for debugging recursion issues
            if hasattr(raw_result, "__class__") and raw_result.__class__.__name__ == "CallToolResult":
                logger.info(
                    f"[UNWRAP] Task {task_id}: Unwrapped CallToolResult - "
                    f"Original type: {type(raw_result).__name__}, "
                    f"Unwrapped type: {type(result_to_store).__name__}, "
                    f"Result preview: {str(result_to_store)[:200]}"
                )
            else:
                logger.debug(
                    f"[UNWRAP] Task {task_id}: No unwrapping needed - "
                    f"Type: {type(result_to_store).__name__}"
                )

            # Save successful result to tasks table
            await conn.execute(
                """
                UPDATE tasks
                SET status = 'completed',
                    result = %s,
                    completed_at = %s,
                    progress = 100
                WHERE task_id = %s
                """,
                (json.dumps(result_to_store), datetime.utcnow(), task_id),
            )
            await conn.commit()

            logger.info(
                f"[STORAGE] Task {task_id}: Stored result in database - "
                f"Status: completed, "
                f"Result type: {type(result_to_store).__name__}, "
                f"Result length: {len(str(result_to_store))} chars, "
                f"Serialized preview: {json.dumps(result_to_store)[:150]}..."
            )

            logger.info(
                f"Task {task_id} completed synchronously in {execution_time:.2f}s"
            )

            # Return unwrapped result for ToolMessage
            # This ensures ToolMessage.content gets parseable JSON, not CallToolResult string
            return result_to_store

        except asyncio.TimeoutError:
            error_msg = f"Tool execution timed out after {context.timeout}s"
            if conn:
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        error = %s,
                        completed_at = %s
                    WHERE task_id = %s
                    """,
                    (error_msg, datetime.utcnow(), task_id),
                )
                await conn.commit()
            logger.error(f"Task {task_id} timed out after {context.timeout}s")
            raise

        except Exception as e:
            error_msg = str(e)
            if conn:
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        error = %s,
                        completed_at = %s
                    WHERE task_id = %s
                    """,
                    (error_msg, datetime.utcnow(), task_id),
                )
                await conn.commit()
            logger.error(
                f"Task {task_id} failed during synchronous execution: {error_msg}",
                exc_info=True,
            )
            raise

        finally:
            # Cleanup connection
            if conn:
                await conn.close()

    async def execute(
        self,
        tool: Any,
        args: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        """
        Execute tool either synchronously or asynchronously based on configuration.

        If wait_for_completion is True (default):
            - Executes tool synchronously and returns actual result
            - Ensures OpenAI Response API compatibility with complete ToolMessages
            - Respects existing timeout parameter (default: 5 minutes)

        If wait_for_completion is False:
            - Creates task record, launches background worker, returns task_id immediately
            - Enables non-blocking execution for direct LangGraph usage
            - User polls via CheckTaskStatus tool for results

        Args:
            tool: Tool instance (MCPToolWrapper or similar)
            args: Tool arguments from AIMessage tool_call
            context: Execution context with session identifiers

        Returns:
            ToolExecutionResult with actual result (sync) or task_id (async)
        """
        # Generate task ID
        task_id = str(uuid.uuid4())

        # Get tool name early for logging
        tool_name = self._get_tool_name(tool)

        # Log tool invocation for recursion tracking
        logger.info(
            f"[TOOL_INVOKE] {tool_name} invoked - "
            f"task_id={task_id}, "
            f"thread_id={context.thread_id}, "
            f"mcp_session_id={context.mcp_session_id}, "
            f"args={json.dumps(args)[:200]}"
        )

        try:
            # Create task record in database
            await self._create_task(task_id, tool_name, args, context)

            # Branch on wait_for_completion
            if self.wait_for_completion:
                # Log execution mode decision
                logger.info(
                    f"[EXEC_MODE] Task {task_id} ({tool_name}): SYNCHRONOUS execution - "
                    f"wait_for_completion=True, timeout={context.timeout}s"
                )
                # Synchronous mode: Wait for actual result
                result = await self._execute_and_wait(task_id, tool, args, context)
                return ToolExecutionResult(
                    success=True,
                    result=result,  # Actual tool result
                    is_async=False,
                )
            else:
                # Log execution mode decision
                logger.info(
                    f"[EXEC_MODE] Task {task_id} ({tool_name}): ASYNCHRONOUS execution - "
                    f"Background task created, CheckTaskStatus required for results"
                )

                # Asynchronous mode: Return task_id immediately with complete ToolMessage
                # Launch background worker (fire-and-forget)
                task = asyncio.create_task(
                    self._execute_background(task_id, tool, args, context)
                )

                # Track task for cleanup (not for waiting)
                self._background_tasks[task_id] = task

                # Get tool name for human-readable message
                tool_name = self._get_tool_name(tool)

                # Return structured response with complete ToolMessage format
                # This ensures OpenAI compliance while maintaining async execution
                return ToolExecutionResult(
                    success=True,
                    result={
                        # Human-readable content for LLM
                        "content": (
                            f"The {tool_name} task has been started in the background. "
                            f"Task ID: {task_id}. "
                            f"Use CheckTaskStatus(task_id='{task_id}') to check progress and retrieve results when complete."
                        ),
                        # Structured data for task management
                        "task_id": task_id,
                        "status": "started",
                        "tool_name": tool_name,
                        "execution_mode": "async",
                        # Session context for proper isolation
                        "parent_session": context.thread_id,
                        "mcp_session_id": context.mcp_session_id,
                        "multi_agent_session_id": context.multi_agent_session_id,
                        # Instructions for status checking
                        "instructions": f"Call CheckTaskStatus(task_id='{task_id}') to monitor progress",
                    },
                    is_async=True,
                    task_id=task_id,
                )

        except Exception as e:
            logger.error(
                f"Failed to execute tool {tool.__class__.__name__}: {e}",
                exc_info=True,
            )
            return ToolExecutionResult(
                success=False,
                result=None,
                error=f"Failed to execute tool: {str(e)}",
                is_async=False,
            )

    async def _create_task(
        self,
        task_id: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolExecutionContext,
    ):
        """
        Create task record in database with 'pending' status.

        Args:
            task_id: UUID for task tracking
            tool_name: Name of the tool being executed
            args: Tool arguments
            context: Execution context with session identifiers
        """
        conn = await psycopg.AsyncConnection.connect(self.db_conn_str)

        try:
            await conn.execute(
                """
                INSERT INTO tasks (
                    task_id, tool_name, args, context, status, thread_id,
                    mcp_session_id, multi_agent_session_id, user_id, request_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    task_id,
                    tool_name,
                    json.dumps(args),
                    json.dumps(
                        {
                            "thread_id": context.thread_id,
                            "mcp_session_id": context.mcp_session_id,
                            "multi_agent_session_id": context.multi_agent_session_id,
                            "timeout": context.timeout,
                        }
                    ),
                    "pending",
                    context.thread_id,
                    context.mcp_session_id,
                    context.multi_agent_session_id,
                    context.user_id,
                    context.request_id,
                ),
            )

            await conn.commit()

            logger.info(
                f"[TASK_CREATE] Task {task_id} created: "
                f"tool={tool_name}, "
                f"thread_id={context.thread_id}, "
                f"mcp_session_id={context.mcp_session_id}, "
                f"multi_agent_session_id={context.multi_agent_session_id}, "
                f"args_preview={str(args)[:100]}"
            )

        except Exception as e:
            logger.error(f"Failed to create task record: {e}", exc_info=True)
            raise

        finally:
            await conn.close()

    async def _execute_background(
        self,
        task_id: str,
        tool: Any,
        args: Dict[str, Any],
        context: ToolExecutionContext,
    ):
        """
        Execute tool in background worker.

        Updates task status to 'running', executes tool, saves result.
        Handles errors gracefully and ensures task status is always updated.

        Args:
            task_id: UUID for task tracking
            tool: Tool instance to execute
            args: Tool arguments
            context: Execution context with session identifiers
        """
        conn = None
        start_time = time.time()

        try:
            # Connect to database for status updates
            conn = await psycopg.AsyncConnection.connect(self.db_conn_str)

            # Update status to 'running'
            await conn.execute(
                """
                UPDATE tasks
                SET status = 'running', started_at = %s
                WHERE task_id = %s
                """,
                (datetime.utcnow(), task_id),
            )
            await conn.commit()

            logger.info(f"Task {task_id} started execution")

            # Execute tool (with timeout)
            try:
                raw_result = await asyncio.wait_for(
                    tool.ainvoke(args),
                    timeout=context.timeout,
                )

                execution_time = time.time() - start_time

                # Unwrap FastMCP CallToolResult if present (same as synchronous path)
                result_to_store = unwrap_calltoolresult_if_needed(raw_result)

                # Log unwrapping operation for debugging recursion issues
                if hasattr(raw_result, "__class__") and raw_result.__class__.__name__ == "CallToolResult":
                    logger.info(
                        f"[UNWRAP] Task {task_id}: Unwrapped CallToolResult - "
                        f"Original type: {type(raw_result).__name__}, "
                        f"Unwrapped type: {type(result_to_store).__name__}, "
                        f"Result preview: {str(result_to_store)[:200]}"
                    )
                else:
                    logger.debug(
                        f"[UNWRAP] Task {task_id}: No unwrapping needed - "
                        f"Type: {type(result_to_store).__name__}"
                    )

                # Save successful result
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'completed',
                        result = %s,
                        completed_at = %s,
                        progress = 100
                    WHERE task_id = %s
                    """,
                    (json.dumps(result_to_store), datetime.utcnow(), task_id),
                )
                await conn.commit()

                logger.info(
                    f"[STORAGE] Task {task_id}: Stored result in database - "
                    f"Status: completed, "
                    f"Result type: {type(result_to_store).__name__}, "
                    f"Result length: {len(str(result_to_store))} chars, "
                    f"Serialized preview: {json.dumps(result_to_store)[:150]}..."
                )

                logger.info(
                    f"Task {task_id} completed successfully in {execution_time:.2f}s"
                )

            except asyncio.TimeoutError:
                # Tool execution timed out
                error_msg = f"Tool execution timed out after {context.timeout}s"
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        error = %s,
                        completed_at = %s
                    WHERE task_id = %s
                    """,
                    (error_msg, datetime.utcnow(), task_id),
                )
                await conn.commit()

                logger.warning(f"Task {task_id} timed out after {context.timeout}s")

            except Exception as tool_error:
                # Tool execution failed
                error_msg = str(tool_error)
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        error = %s,
                        completed_at = %s
                    WHERE task_id = %s
                    """,
                    (error_msg, datetime.utcnow(), task_id),
                )
                await conn.commit()

                logger.error(
                    f"Task {task_id} failed: {error_msg}",
                    exc_info=True,
                )

        except Exception as e:
            # Database or unexpected error
            logger.error(
                f"Fatal error in background worker for task {task_id}: {e}",
                exc_info=True,
            )

            # Attempt to mark task as failed (best effort)
            if conn:
                try:
                    await conn.execute(
                        """
                        UPDATE tasks
                        SET status = 'failed',
                            error = %s,
                            completed_at = %s
                        WHERE task_id = %s
                        """,
                        (f"Background worker error: {str(e)}", datetime.utcnow(), task_id),
                    )
                    await conn.commit()
                except:
                    pass  # Give up if we can't even update status

        finally:
            # Cleanup
            if conn:
                await conn.close()

            # Remove from tracking
            self._background_tasks.pop(task_id, None)

    async def cleanup_old_tasks(self):
        """
        Clean up completed/failed tasks older than retention period.

        Per user's decision: 30 days default retention (configurable parameter).
        This should be called periodically (e.g., daily cron job).
        """
        conn = None
        try:
            conn = await psycopg.AsyncConnection.connect(self.db_conn_str)

            result = await conn.execute(
                """
                DELETE FROM tasks
                WHERE status IN ('completed', 'failed')
                  AND completed_at < NOW() - INTERVAL '%s days'
                RETURNING task_id
                """,
                (self.retention_days,),
            )

            deleted_count = len(await result.fetchall())

            if deleted_count > 0:
                logger.info(
                    f"Cleaned up {deleted_count} tasks older than {self.retention_days} days"
                )

            await conn.commit()

        except Exception as e:
            logger.error(f"Failed to cleanup old tasks: {e}", exc_info=True)

        finally:
            if conn is not None:
                await conn.close()
