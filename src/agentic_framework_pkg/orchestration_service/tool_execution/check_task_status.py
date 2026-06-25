"""
CheckTaskStatus tool for polling async task execution results.

This tool allows agents to check the status of background tasks created by
the AsyncTaskManagerExecutor. It enables conversational polling for long-running
tool executions without blocking the Response API's conversational turns.

Usage:
    CheckTaskStatus(task_id="550e8400-e29b-41d4-a716-446655440000")

Returns:
    {
        "success": true,
        "task_id": "550e8400-e29b-41d4-a716-446655440000",
        "tool_name": "ExecuteApprovedPlan",
        "status": "completed",
        "progress": 100,
        "result": {...},
        "created_at": "2025-12-20T10:30:00",
        "started_at": "2025-12-20T10:30:05",
        "completed_at": "2025-12-20T10:35:12"
    }
"""

import json
from typing import Any, Dict

import psycopg

from ...logger_config import get_logger
from ..persistence_v2 import get_or_create_connection_pool

logger = get_logger(__name__)

# Global counter for tracking repeated task status checks (recursion detection)
_task_check_counts: Dict[str, int] = {}


async def check_task_status(
    task_id: str,
    db_connection_string: str,
) -> Dict[str, Any]:
    """
    Check status of async task.

    Queries the tasks table for the given task_id and returns comprehensive
    status information including progress, result, and timing data.

    Args:
        task_id: UUID of the task to check
        db_connection_string: PostgreSQL connection string

    Returns:
        Dictionary with task status information:
        - success: Whether the query succeeded
        - task_id: Task UUID
        - tool_name: Name of the tool being executed
        - status: 'pending', 'running', 'completed', or 'failed'
        - progress: Percentage complete (0-100)
        - result: Tool execution result (if completed)
        - error: Error message (if failed)
        - created_at, started_at, completed_at: Timestamps
    """
    # Convert SQLAlchemy-style URL to psycopg3 format (same as async_executor.py)
    # Handles postgresql+asyncpg:// and postgresql+psycopg2:// notation
    if "+asyncpg://" in db_connection_string:
        db_connection_string = db_connection_string.replace("+asyncpg://", "://")
    elif "+psycopg2://" in db_connection_string:
        db_connection_string = db_connection_string.replace("+psycopg2://", "://")

    # Track how many times this task has been checked (recursion detection)
    global _task_check_counts
    _task_check_counts[task_id] = _task_check_counts.get(task_id, 0) + 1

    check_count = _task_check_counts[task_id]
    if check_count > 5:
        logger.warning(
            f"[POTENTIAL_RECURSION] Task {task_id} checked {check_count} times - "
            f"possible recursion loop! Previous checks may indicate agent is stuck."
        )
    elif check_count > 1:
        logger.info(
            f"[CHECK_COUNT] Task {task_id} checked {check_count} times"
        )

    try:
        # Use shared connection pool for better performance (avoids connection overhead)
        pool = await get_or_create_connection_pool()

        async with pool.connection() as conn:
            cursor = await conn.execute(
                """
                SELECT
                    task_id,
                    tool_name,
                    status,
                    progress,
                    result,
                    error,
                    created_at,
                    started_at,
                    completed_at
                FROM tasks
                WHERE task_id = %s
                """,
                (task_id,),
            )

            row = await cursor.fetchone()

            if not row:
                logger.warning(f"Task {task_id} not found")
                return {
                    "success": False,
                    "error": f"Task {task_id} not found. It may have been deleted due to retention policy.",
                }

            # Parse result from JSONB if present
            result = None
            if row[4]:  # result column
                # Log raw DB result for debugging
                logger.debug(
                    f"[PARSE_RESULT] Task {task_id}: "
                    f"Raw DB result type: {type(row[4]).__name__}, "
                    f"Raw value preview: {str(row[4])[:200]}, "
                    f"Attempting JSON parse"
                )

                try:
                    result = json.loads(row[4]) if isinstance(row[4], str) else row[4]
                    logger.debug(f"[PARSE_RESULT] Task {task_id}: JSON parsing successful")
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"[PARSE_RESULT] Task {task_id}: JSON parsing failed - {str(e)} - "
                        f"returning raw result: {str(row[4])[:200]}"
                    )
                    result = row[4]  # Use raw value if JSON parsing fails

            response = {
                "success": True,
                "task_id": str(row[0]),
                "tool_name": row[1],
                "status": row[2],
                "progress": row[3] or 0,
                "result": result,
                "error": row[5],
                "created_at": row[6].isoformat() if row[6] else None,
                "started_at": row[7].isoformat() if row[7] else None,
                "completed_at": row[8].isoformat() if row[8] else None,
            }

            # Add user-friendly message based on status
            if response["status"] == "pending":
                response["message"] = (
                    f"Task {task_id} is queued and waiting to start execution."
                )
            elif response["status"] == "running":
                response["message"] = (
                    f"Task {task_id} is currently executing (progress: {response['progress']}%)."
                )
            elif response["status"] == "completed":
                response["message"] = (
                    f"Task {task_id} completed successfully. Result is available."
                )
            elif response["status"] == "failed":
                response["message"] = (
                    f"Task {task_id} failed: {response['error']}"
                )

            # Log comprehensive status retrieval for debugging recursion
            logger.info(
                f"[CHECK_STATUS] Task {task_id}: "
                f"status={response['status']}, "
                f"progress={response['progress']}, "
                f"result_type={type(result).__name__ if result else 'None'}, "
                f"result_length={len(str(result)) if result else 0} chars, "
                f"result_preview={str(result)[:200] if result else 'None'}"
            )

            return response

    except Exception as e:
        logger.error(f"Failed to check task status: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Failed to check task status: {str(e)}",
        }


from langchain_core.tools import Tool
from pydantic import BaseModel, Field


class CheckTaskStatusInput(BaseModel):
    """Input schema for CheckTaskStatus tool."""

    task_id: str = Field(
        description="UUID of the task to check (returned from a previous async tool call)"
    )


def get_check_task_status_tool(db_connection_string: str) -> Tool:
    """
    Factory function to create the CheckTaskStatus tool.

    This follows the factory pattern used by other orchestration service tools
    (e.g., DelegateTaskToGatewayTool). The factory function captures the database
    connection string in a closure and returns a LangChain Tool with async coroutine.

    Args:
        db_connection_string: PostgreSQL connection string for tasks table

    Returns:
        LangChain Tool configured for async task status checking
    """
    logger.info("[TOOL] Creating CheckTaskStatus tool via factory function")

    async def _check_status(task_id: str):
        """Check async task status."""
        logger.info(f"[TOOL] CheckTaskStatus called for task_id={task_id}")

        try:
            result = await check_task_status(task_id, db_connection_string)
            logger.info(
                f"[TOOL] CheckTaskStatus result: status={result.get('status')}"
            )
            return result
        except Exception as e:
            logger.error(f"[TOOL] CheckTaskStatus error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    return Tool(
        name="CheckTaskStatus",
        description=(
            "Check the status of an asynchronous task. "
            "Use this tool to poll for task completion and retrieve results. "
            "Input should be a task_id (UUID string) returned from a previous tool call. "
            "Returns task status ('pending', 'running', 'completed', 'failed'), "
            "progress percentage, and result/error information."
        ),
        func=None,  # No sync version
        coroutine=_check_status,
        args_schema=CheckTaskStatusInput,
    )
