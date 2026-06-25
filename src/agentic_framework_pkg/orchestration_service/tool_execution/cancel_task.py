"""
CancelTask tool for cancelling async task execution.

This tool allows agents to cancel background tasks created by the
AsyncTaskManagerExecutor. It enables graceful cancellation of long-running
tool executions without blocking the Response API's conversational turns.

Usage:
    CancelTask(task_id="550e8400-e29b-41d4-a716-446655440000")

Returns:
    {
        "success": true,
        "task_id": "550e8400-e29b-41d4-a716-446655440000",
        "tool_name": "ExecuteApprovedPlan",
        "status": "cancelled",
        "message": "Task cancelled successfully"
    }
"""

import json
from typing import Any, Dict

import psycopg

from ...logger_config import get_logger

logger = get_logger(__name__)


async def cancel_task(
    task_id: str,
    db_connection_string: str,
) -> Dict[str, Any]:
    """
    Cancel async task.

    Marks the task as cancelled in the tasks table. The task executor should
    check for cancellation status and abort execution gracefully.

    Args:
        task_id: UUID of the task to cancel
        db_connection_string: PostgreSQL connection string

    Returns:
        Dictionary with cancellation status:
        - success: Whether the cancellation succeeded
        - task_id: Task UUID
        - tool_name: Name of the tool being executed
        - status: New status ('cancelled')
        - message: Human-readable status message
    """
    # Convert SQLAlchemy-style URL to psycopg3 format (same as async_executor.py)
    # Handles postgresql+asyncpg:// and postgresql+psycopg2:// notation
    if "+asyncpg://" in db_connection_string:
        db_connection_string = db_connection_string.replace("+asyncpg://", "://")
    elif "+psycopg2://" in db_connection_string:
        db_connection_string = db_connection_string.replace("+psycopg2://", "://")

    conn = None
    try:
        conn = await psycopg.AsyncConnection.connect(db_connection_string)

        # First, check if task exists and get current status
        cursor = await conn.execute(
            """
            SELECT task_id, tool_name, status
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

        current_status = row[2]
        tool_name = row[1]

        # Check if task is already in a terminal state
        if current_status in ("completed", "failed", "cancelled"):
            logger.info(
                f"Task {task_id} is already in terminal state: {current_status}"
            )
            return {
                "success": False,
                "task_id": str(row[0]),
                "tool_name": tool_name,
                "status": current_status,
                "message": f"Task {task_id} cannot be cancelled - already in state: {current_status}",
            }

        # Update task status to 'cancelled'
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'cancelled',
                completed_at = NOW(),
                error = 'Task cancelled by user request'
            WHERE task_id = %s
            """,
            (task_id,),
        )

        await conn.commit()

        logger.info(f"Task {task_id} cancelled successfully")

        return {
            "success": True,
            "task_id": task_id,
            "tool_name": tool_name,
            "status": "cancelled",
            "message": f"Task {task_id} cancelled successfully",
        }

    except Exception as e:
        logger.error(f"Failed to cancel task: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Failed to cancel task: {str(e)}",
        }

    finally:
        if conn is not None:
            await conn.close()


from langchain_core.tools import Tool
from pydantic import BaseModel, Field


class CancelTaskInput(BaseModel):
    """Input schema for CancelTask tool."""

    task_id: str = Field(
        description="UUID of the task to cancel (returned from a previous async tool call)"
    )


def get_cancel_task_tool(db_connection_string: str) -> Tool:
    """
    Factory function to create the CancelTask tool.

    This follows the factory pattern used by other orchestration service tools
    (e.g., CheckTaskStatus, DelegateTaskToGatewayTool). The factory function
    captures the database connection string in a closure and returns a LangChain
    Tool with async coroutine.

    Args:
        db_connection_string: PostgreSQL connection string for tasks table

    Returns:
        LangChain Tool configured for async task cancellation
    """
    logger.info("[TOOL] Creating CancelTask tool via factory function")

    async def _cancel_task(task_id: str):
        """Cancel async task."""
        logger.info(f"[TOOL] CancelTask called for task_id={task_id}")

        try:
            result = await cancel_task(task_id, db_connection_string)
            logger.info(
                f"[TOOL] CancelTask result: success={result.get('success')}"
            )
            return result
        except Exception as e:
            logger.error(f"[TOOL] CancelTask error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    return Tool(
        name="CancelTask",
        description=(
            "Cancel an asynchronous task that is pending or running. "
            "Use this tool to abort long-running operations gracefully. "
            "Input should be a task_id (UUID string) returned from a previous tool call. "
            "Returns cancellation status and confirmation message. "
            "Note: Tasks that have already completed or failed cannot be cancelled."
        ),
        func=None,  # No sync version
        coroutine=_cancel_task,
        args_schema=CancelTaskInput,
    )
