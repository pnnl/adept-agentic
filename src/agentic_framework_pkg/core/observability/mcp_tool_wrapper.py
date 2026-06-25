"""
MCP Tool Instrumentation Wrapper

This module provides automatic observability instrumentation for MCP tools
created through the static factory pattern in mcp_langchain_tools.py.

It wraps tool execution with:
- Automatic tracing via Langfuse
- Performance metrics collection
- Error tracking and recovery
- Session context propagation
- Token usage monitoring
"""

import time
import json
import asyncio
from typing import Any, Dict, Optional, Callable, Union
from functools import wraps

from langchain_core.tools import BaseTool

try:
    from langfuse import Langfuse, get_client

    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    get_client = None

from .smart_logger import SmartLogger, trace_context, observe


class MCPToolInstrumentor:
    """
    Instrumentor for MCP tools to add observability.

    This class wraps MCP tool execution with comprehensive observability,
    including tracing, metrics, and error handling.
    """

    def __init__(self, enable_tracing: bool = True):
        """
        Initialize the tool instrumentor.

        Args:
            enable_tracing: Whether to enable Langfuse tracing
        """
        self.logger = SmartLogger(__name__)
        self.enable_tracing = enable_tracing and LANGFUSE_AVAILABLE

    def instrument_tool(self, tool: BaseTool) -> BaseTool:
        """
        Instrument a LangChain tool with observability.

        Args:
            tool: The tool to instrument

        Returns:
            Instrumented tool
        """
        # Store original methods
        original_run = tool._run
        original_arun = tool._arun if hasattr(tool, "_arun") else None

        # Create instrumented versions
        tool._run = self._create_instrumented_run(tool, original_run, is_async=False)
        if original_arun:
            tool._arun = self._create_instrumented_run(
                tool, original_arun, is_async=True
            )

        # Mark as instrumented
        tool._instrumented = True

        return tool

    def _create_instrumented_run(
        self, tool: BaseTool, original_method: Callable, is_async: bool
    ) -> Callable:
        """
        Create an instrumented version of a tool's run method.

        Args:
            tool: The tool being instrumented
            original_method: The original run method
            is_async: Whether this is an async method

        Returns:
            Instrumented method
        """
        if is_async:

            @wraps(original_method)
            @observe(name=f"tool_{tool.name}")
            async def instrumented_run(*args, **kwargs) -> Any:
                return await self._execute_with_observability_async(
                    tool, original_method, args, kwargs
                )

            return instrumented_run
        else:

            @wraps(original_method)
            @observe(name=f"tool_{tool.name}")
            def instrumented_run(*args, **kwargs) -> Any:
                return self._execute_with_observability_sync(
                    tool, original_method, args, kwargs
                )

            return instrumented_run

    def _execute_with_observability_sync(
        self, tool: BaseTool, original_method: Callable, args: tuple, kwargs: dict
    ) -> Any:
        """
        Execute tool synchronously with full observability.

        Args:
            tool: The tool being executed
            original_method: The original method to call
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Tool execution result
        """
        start_time = time.time()
        result = None
        error = None
        success = False
        duration_ms = 0

        # Extract session context
        ctx = trace_context.get()
        session_info = {
            "session_id": kwargs.get("session_id", ctx.get("session_id")),
            "mcp_session_id": kwargs.get("mcp_session_id", ctx.get("mcp_session_id")),
            "multi_agent_session_id": kwargs.get(
                "multi_agent_session_id", ctx.get("multi_agent_session_id")
            ),
        }

        try:
            # Log tool start
            self.logger.info(
                f"Starting tool execution: {tool.name}",
                trace=True,
                tool_name=tool.name,
                **session_info,
            )

            # Update Langfuse context if available
            if LANGFUSE_AVAILABLE and self.enable_tracing:
                try:
                    client = get_client()
                    if client:
                        client.update_current_span(
                            name=f"tool_{tool.name}",
                            input={
                                "args": str(args)[:1000],  # Truncate large inputs
                                "kwargs": str(kwargs)[:1000],
                                **session_info,
                            },
                            metadata={
                                "tool_name": tool.name,
                                "tool_description": (
                                    tool.description[:200] if tool.description else None
                                ),
                                **session_info,
                            },
                        )
                except Exception as e:
                    self.logger.debug(f"Failed to update Langfuse span: {e}")

            # Execute the tool
            result = original_method(*args, **kwargs)

            success = True

            # Log success
            duration_ms = (time.time() - start_time) * 1000
            self.logger.log_tool_execution(
                tool_name=tool.name,
                input_data=args,
                output_data=result,
                duration_ms=duration_ms,
                success=True,
            )

            # Update Langfuse with output
            if LANGFUSE_AVAILABLE and self.enable_tracing:
                try:
                    client = get_client()
                    if client:
                        client.update_current_span(
                            output=self._serialize_output(result),
                            level="DEFAULT",
                            status_message="Success",
                        )
                except Exception as e:
                    self.logger.debug(f"Failed to update Langfuse span: {e}")

            return result

        except Exception as e:
            error = str(e)
            duration_ms = (time.time() - start_time) * 1000

            # Log error
            self.logger.log_tool_execution(
                tool_name=tool.name,
                input_data=args,
                output_data=None,
                duration_ms=duration_ms,
                success=False,
                error=error,
            )

            # Update Langfuse with error
            if LANGFUSE_AVAILABLE and self.enable_tracing:
                try:
                    client = get_client()
                    if client:
                        client.update_current_span(level="ERROR", status_message=error)
                except Exception as e:
                    self.logger.debug(f"Failed to update Langfuse span: {e}")

            # Re-raise the exception
            raise

        finally:
            # Collect metrics
            self._collect_metrics(tool.name, duration_ms, success, error)

    async def _execute_with_observability_async(
        self, tool: BaseTool, original_method: Callable, args: tuple, kwargs: dict
    ) -> Any:
        """
        Execute tool asynchronously with full observability.

        Args:
            tool: The tool being executed
            original_method: The original method to call
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Tool execution result
        """
        start_time = time.time()
        result = None
        error = None
        success = False
        duration_ms = 0

        # Extract session context
        ctx = trace_context.get()
        session_info = {
            "session_id": kwargs.get("session_id", ctx.get("session_id")),
            "mcp_session_id": kwargs.get("mcp_session_id", ctx.get("mcp_session_id")),
            "multi_agent_session_id": kwargs.get(
                "multi_agent_session_id", ctx.get("multi_agent_session_id")
            ),
        }

        try:
            # Log tool start
            self.logger.info(
                f"Starting tool execution: {tool.name}",
                trace=True,
                tool_name=tool.name,
                **session_info,
            )

            # Update Langfuse context if available
            if LANGFUSE_AVAILABLE and self.enable_tracing:
                try:
                    client = get_client()
                    if client:
                        client.update_current_span(
                            name=f"tool_{tool.name}",
                            input={
                                "args": str(args)[:1000],  # Truncate large inputs
                                "kwargs": str(kwargs)[:1000],
                                **session_info,
                            },
                            metadata={
                                "tool_name": tool.name,
                                "tool_description": (
                                    tool.description[:200] if tool.description else None
                                ),
                                **session_info,
                            },
                        )
                except Exception as e:
                    self.logger.debug(f"Failed to update Langfuse span: {e}")

            # Execute the tool
            result = await original_method(*args, **kwargs)

            success = True

            # Log success
            duration_ms = (time.time() - start_time) * 1000
            self.logger.log_tool_execution(
                tool_name=tool.name,
                input_data=args,
                output_data=result,
                duration_ms=duration_ms,
                success=True,
            )

            # Update Langfuse with output
            if LANGFUSE_AVAILABLE and self.enable_tracing:
                try:
                    client = get_client()
                    if client:
                        client.update_current_span(
                            output=self._serialize_output(result),
                            level="DEFAULT",
                            status_message="Success",
                        )
                except Exception as e:
                    self.logger.debug(f"Failed to update Langfuse span: {e}")

            return result

        except Exception as e:
            error = str(e)
            duration_ms = (time.time() - start_time) * 1000

            # Log error
            self.logger.log_tool_execution(
                tool_name=tool.name,
                input_data=args,
                output_data=None,
                duration_ms=duration_ms,
                success=False,
                error=error,
            )

            # Update Langfuse with error
            if LANGFUSE_AVAILABLE and self.enable_tracing:
                try:
                    client = get_client()
                    if client:
                        client.update_current_span(level="ERROR", status_message=error)
                except Exception as e:
                    self.logger.debug(f"Failed to update Langfuse span: {e}")

            # Re-raise the exception
            raise

        finally:
            # Collect metrics
            self._collect_metrics(tool.name, duration_ms, success, error)

    def _serialize_output(self, output: Any) -> Union[str, dict]:
        """
        Serialize tool output for tracing.

        Args:
            output: Tool output to serialize

        Returns:
            Serialized output
        """
        if output is None:
            return None

        # Handle different output types
        if isinstance(output, (str, int, float, bool)):
            return output
        elif isinstance(output, dict):
            # Truncate large outputs
            return {k: str(v)[:500] for k, v in output.items()}
        elif isinstance(output, (list, tuple)):
            # Limit array size
            return [str(item)[:100] for item in output[:10]]
        else:
            # Convert to string with size limit
            return str(output)[:1000]

    def _collect_metrics(
        self, tool_name: str, duration_ms: float, success: bool, error: Optional[str]
    ) -> None:
        """
        Collect metrics for tool execution.

        Args:
            tool_name: Name of the tool
            duration_ms: Execution duration
            success: Whether execution succeeded
            error: Error message if failed
        """
        # This is where you'd send metrics to Prometheus, DataDog, etc.
        # For now, just log them
        self.logger.debug(
            f"Tool metrics - {tool_name}: duration={duration_ms:.2f}ms, success={success}",
            trace=False,  # Don't trace metrics themselves
        )


def create_observable_tool_factory(factory_func: Callable) -> Callable:
    """
    Decorator to make tool factories automatically instrument their tools.

    This decorator wraps tool factory functions (like those in mcp_langchain_tools.py)
    to automatically instrument the tools they create.

    Args:
        factory_func: The tool factory function to wrap

    Returns:
        Wrapped factory function that produces instrumented tools
    """
    instrumentor = MCPToolInstrumentor()

    @wraps(factory_func)
    def wrapped_factory(*args, **kwargs) -> BaseTool:
        # Create the tool using the original factory
        tool = factory_func(*args, **kwargs)

        # Instrument it
        instrumented_tool = instrumentor.instrument_tool(tool)

        return instrumented_tool

    return wrapped_factory


# Convenience decorator for new tool factories
def observable_tool(name: Optional[str] = None):
    """
    Decorator to make a tool factory observable.

    Usage:
        @observable_tool()
        def get_my_tool():
            return MyTool()

    Args:
        name: Optional name for the tool

    Returns:
        Decorator function
    """

    def decorator(factory_func: Callable) -> Callable:
        return create_observable_tool_factory(factory_func)

    return decorator


class ObservableAgentExecutor:
    """
    Wrapper for agent executors to add observability.

    This class instruments agent execution with tracing and metrics.
    """

    def __init__(self, agent_executor):
        """
        Initialize the observable agent executor.

        Args:
            agent_executor: The agent executor to wrap
        """
        self.agent_executor = agent_executor
        self.logger = SmartLogger(__name__)

    @observe(name="agent_execution")
    async def ainvoke(self, *args, **kwargs):
        """
        Invoke the agent with observability.

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Agent execution result
        """
        start_time = time.time()

        try:
            # Log agent start
            self.logger.log_agent_execution(
                agent_name=self.agent_executor.__class__.__name__,
                action="invoke",
                metadata=kwargs,
            )

            # Execute agent
            result = await self.agent_executor.ainvoke(*args, **kwargs)

            # Log success
            duration_ms = (time.time() - start_time) * 1000
            self.logger.log_agent_execution(
                agent_name=self.agent_executor.__class__.__name__,
                action="completed",
                duration_ms=duration_ms,
            )

            return result

        except Exception as e:
            # Log error
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(
                f"Agent execution failed: {e}",
                trace=True,
                agent_name=self.agent_executor.__class__.__name__,
                error_type="agent_execution_error",
                duration_ms=duration_ms,
            )
            raise


# Helper function to instrument all tools in a list
def instrument_tool_list(tools: list) -> list:
    """
    Instrument a list of tools.

    Args:
        tools: List of tools to instrument

    Returns:
        List of instrumented tools
    """
    instrumentor = MCPToolInstrumentor()
    return [instrumentor.instrument_tool(tool) for tool in tools]


# Decorator for MCP tool instrumentation
def mcp_tool_instrumentor(
    tool_name: Optional[str] = None, extract_session_id: bool = False
):
    """
    Decorator to instrument MCP tool functions.

    This decorator wraps MCP tool functions with observability instrumentation,
    providing automatic tracing, metrics collection, and error handling.

    Args:
        tool_name: Optional name for the tool (defaults to function name)
        extract_session_id: Whether to extract session_id from kwargs

    Returns:
        Decorated function with observability

    Usage:
        @mcp_tool_instrumentor(tool_name="my_tool")
        async def my_tool_func(data: str, mcp_session_id: str = None):
            return {"result": data}
    """

    def decorator(func: Callable) -> Callable:
        actual_tool_name = tool_name or func.__name__

        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            @observe(name=f"mcp_tool_{actual_tool_name}")
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                logger = SmartLogger(__name__)

                # Extract session context if requested
                session_info = {}
                if extract_session_id:
                    session_info = {
                        "mcp_session_id": kwargs.get("mcp_session_id"),
                        "session_id": kwargs.get("session_id"),
                    }

                try:
                    # Log tool start
                    logger.info(
                        f"Starting MCP tool: {actual_tool_name}",
                        trace=True,
                        tool_name=actual_tool_name,
                        **session_info,
                    )

                    # Execute the tool
                    result = await func(*args, **kwargs)

                    # Log success
                    duration_ms = (time.time() - start_time) * 1000
                    logger.log_tool_execution(
                        tool_name=actual_tool_name,
                        input_data=kwargs,
                        output_data=result,
                        duration_ms=duration_ms,
                        success=True,
                    )

                    return result

                except Exception as e:
                    # Log error
                    duration_ms = (time.time() - start_time) * 1000
                    logger.log_tool_execution(
                        tool_name=actual_tool_name,
                        input_data=kwargs,
                        output_data=None,
                        duration_ms=duration_ms,
                        success=False,
                        error=str(e),
                    )
                    raise

        else:

            @wraps(func)
            @observe(name=f"mcp_tool_{actual_tool_name}")
            def wrapper(*args, **kwargs):
                start_time = time.time()
                logger = SmartLogger(__name__)

                # Extract session context if requested
                session_info = {}
                if extract_session_id:
                    session_info = {
                        "mcp_session_id": kwargs.get("mcp_session_id"),
                        "session_id": kwargs.get("session_id"),
                    }

                try:
                    # Log tool start
                    logger.info(
                        f"Starting MCP tool: {actual_tool_name}",
                        trace=True,
                        tool_name=actual_tool_name,
                        **session_info,
                    )

                    # Execute the tool
                    result = func(*args, **kwargs)

                    # Log success
                    duration_ms = (time.time() - start_time) * 1000
                    logger.log_tool_execution(
                        tool_name=actual_tool_name,
                        input_data=kwargs,
                        output_data=result,
                        duration_ms=duration_ms,
                        success=True,
                    )

                    return result

                except Exception as e:
                    # Log error
                    duration_ms = (time.time() - start_time) * 1000
                    logger.log_tool_execution(
                        tool_name=actual_tool_name,
                        input_data=kwargs,
                        output_data=None,
                        duration_ms=duration_ms,
                        success=False,
                        error=str(e),
                    )
                    raise

        return wrapper

    return decorator
