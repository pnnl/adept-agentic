"""
Tool execution factory module.

Provides factory pattern for routing tool execution to appropriate strategies.
Per user's architectural decision: ALL tools are async by default.

Usage:
    from ..tool_execution import (
        ToolExecutionFactory,
        ToolExecutionContext,
        ToolExecutionResult,
        AsyncTaskManagerExecutor,
    )

    factory = ToolExecutionFactory()
    factory.register_strategy(
        AsyncTaskManagerExecutor(db_conn_str, retention_days=30),
        is_default=True
    )

    context = ToolExecutionContext(
        thread_id=thread_id,
        mcp_session_id=mcp_session_id,
        multi_agent_session_id=multi_agent_session_id,
        user_id=user_id,
        request_id=request_id,
    )

    result = await factory.execute(tool, tool_name, args, context)
"""

from .async_executor import AsyncTaskManagerExecutor
from .base import (
    ToolExecutionContext,
    ToolExecutionFactory,
    ToolExecutionResult,
    ToolExecutionStrategy,
)
from .check_task_status import get_check_task_status_tool

__all__ = [
    "AsyncTaskManagerExecutor",
    "ToolExecutionContext",
    "ToolExecutionFactory",
    "ToolExecutionResult",
    "ToolExecutionStrategy",
    "get_check_task_status_tool",
]
