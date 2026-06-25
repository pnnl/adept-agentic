"""
Observability Module for ADEPT Framework

This module provides comprehensive observability capabilities including:
- Smart logging with automatic tracing
- MCP tool instrumentation
- Agent execution monitoring
- Session context propagation
- Langfuse integration
"""

from .smart_logger import (
    SmartLogger,
    get_smart_logger,
    getLogger,
    trace_context,
    observe,  # Add observe decorator export
    create_trace,
)

from .tracing import TraceContext, SpanContext

from .mcp_tool_wrapper import (
    MCPToolInstrumentor,
    create_observable_tool_factory,
    observable_tool,
    ObservableAgentExecutor,
    instrument_tool_list,
    mcp_tool_instrumentor  # Add mcp_tool_instrumentor decorator export
)

__all__ = [
    # Smart Logger
    'SmartLogger',
    'get_smart_logger',
    'getLogger',
    'trace_context',
    'observe',  # Export observe decorator
    'create_trace',

    # Tracing
    'TraceContext',
    'SpanContext',

    # MCP Tool Wrapper
    'MCPToolInstrumentor',
    'create_observable_tool_factory',
    'observable_tool',
    'ObservableAgentExecutor',
    'instrument_tool_list',
    'mcp_tool_instrumentor',  # Export mcp_tool_instrumentor decorator
]

# Version
__version__ = '0.1.0'