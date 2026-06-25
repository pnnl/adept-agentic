"""
Abstract base classes for tool execution strategies.

This module defines the factory pattern for routing tool execution to appropriate
strategies (sync vs async). This enables proper handling of long-running tools
without violating OpenAI Response API's conversational turn expectations.

Architecture:
- ToolExecutionContext: Execution context with session identifiers
- ToolExecutionResult: Standardized result wrapper
- ToolExecutionStrategy: Abstract base for execution strategies
- ToolExecutionFactory: Strategy router and orchestrator
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ToolExecutionContext:
    """
    Execution context for tool invocation.

    Contains multi-tier session identifiers for proper state isolation
    and tracking across the three-tier architecture.

    Attributes:
        thread_id: LangGraph thread ID for conversation state
        mcp_session_id: MCP tool execution session (stateful operations)
        multi_agent_session_id: Multi-agent coordination session
        user_id: User identifier for ACL and logging
        request_id: Unique request identifier for tracing
        timeout: Maximum execution time in seconds (default: 300s)
    """

    thread_id: str
    mcp_session_id: Optional[str]
    multi_agent_session_id: Optional[str]
    user_id: str
    request_id: str
    timeout: int = 300


@dataclass
class ToolExecutionResult:
    """
    Result of tool execution.

    Standardized wrapper for both sync and async tool execution results.
    For async tools, the result contains a task_id for polling.

    Attributes:
        success: Whether the tool execution succeeded
        result: Tool execution result (immediate for sync, task_id dict for async)
        error: Error message if execution failed
        execution_time: Time taken for execution in seconds
        is_async: Whether this was an async task execution
        task_id: Task UUID for async executions (for polling)
    """

    success: bool
    result: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    is_async: bool = False
    task_id: Optional[str] = None


class ToolExecutionStrategy(ABC):
    """
    Abstract base class for tool execution strategies.

    Implementations:
    - SyncToolExecutor: Immediate execution for fast tools (<5s expected)
    - AsyncTaskManagerExecutor: Background execution for long tools (≥5s expected)

    The factory pattern allows easy addition of new strategies (e.g., Celery,
    distributed execution, streaming results) without changing graph_builder.py.
    """

    @abstractmethod
    async def can_execute(self, tool_name: str) -> bool:
        """
        Check if this strategy can execute the given tool.

        Args:
            tool_name: Name of the tool to execute

        Returns:
            True if this strategy can handle the tool, False otherwise
        """
        pass

    @abstractmethod
    async def execute(
        self,
        tool: Any,
        args: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        """
        Execute the tool with given arguments and context.

        Args:
            tool: Tool instance (MCPToolWrapper or similar)
            args: Tool arguments from AIMessage tool_call
            context: Execution context with session identifiers

        Returns:
            ToolExecutionResult with success status and result/error
        """
        pass


class ToolExecutionFactory:
    """
    Factory for routing tool execution to appropriate strategy.

    The factory tries each registered strategy in order until one accepts
    the tool (via can_execute()). If no strategy accepts, falls back to
    the default strategy.

    Usage:
        factory = ToolExecutionFactory()
        factory.register_strategy(SyncToolExecutor(), is_default=True)
        factory.register_strategy(AsyncTaskManagerExecutor())

        result = await factory.execute(tool, "ExecuteApprovedPlan", args, context)
    """

    def __init__(self):
        """Initialize factory with empty strategy list."""
        self.strategies: List[ToolExecutionStrategy] = []
        self.default_strategy: Optional[ToolExecutionStrategy] = None

    def register_strategy(
        self,
        strategy: ToolExecutionStrategy,
        is_default: bool = False,
    ):
        """
        Register a tool execution strategy.

        Args:
            strategy: Strategy implementation to register
            is_default: Whether this is the default fallback strategy
        """
        self.strategies.append(strategy)
        if is_default:
            self.default_strategy = strategy

    async def execute(
        self,
        tool: Any,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        """
        Route tool execution to appropriate strategy.

        Tries each registered strategy until one accepts (via can_execute()).
        If no strategy accepts (e.g., planning tools exempt from async wrapping),
        executes tool directly and synchronously.

        Args:
            tool: Tool instance to execute
            tool_name: Name of the tool (for strategy selection)
            args: Tool arguments from AIMessage tool_call
            context: Execution context with session identifiers

        Returns:
            ToolExecutionResult from the selected strategy

        Raises:
            ValueError: If no strategy found and no default set
        """
        import time

        from ...logger_config import get_logger

        logger = get_logger(__name__)

        # Try each strategy until one accepts
        for strategy in self.strategies:
            if await strategy.can_execute(tool_name):
                return await strategy.execute(tool, args, context)

        # No strategy accepted - execute directly and synchronously
        # This is the fallback for planning tools exempt from async wrapping
        logger.info(
            f"[TOOL_EXECUTION_FALLBACK] No strategy accepted {tool_name}, "
            f"executing synchronously via direct invocation"
        )

        start_time = time.time()
        try:
            result = await tool.ainvoke(args)
            execution_time = time.time() - start_time

            logger.info(
                f"[TOOL_EXECUTION_FALLBACK] {tool_name} completed synchronously "
                f"in {execution_time:.2f}s"
            )

            return ToolExecutionResult(
                success=True,
                result=result,
                execution_time=execution_time,
                is_async=False,
            )
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)

            logger.error(
                f"[TOOL_EXECUTION_FALLBACK] {tool_name} failed after {execution_time:.2f}s: {error_msg}",
                exc_info=True,
            )

            return ToolExecutionResult(
                success=False,
                result=None,
                error=error_msg,
                execution_time=execution_time,
                is_async=False,
            )
