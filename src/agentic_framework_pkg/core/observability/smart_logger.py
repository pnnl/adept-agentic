"""
Smart Logger: Intelligent Bridge Between Logging and Observability

This module provides a smart logging wrapper that preserves the familiar Python logging
interface while automatically extracting structured data and delegating to Langfuse
for distributed tracing.

Key Features:
- Drop-in replacement for standard Python logger
- Automatic structured data extraction from log context
- Seamless Langfuse integration for tracing
- Thread-safe trace context propagation
- Minimal overhead when tracing is disabled
"""

import inspect
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from .tracing import TraceContext

try:
    from langfuse import Langfuse
    from langfuse import get_client as get_langfuse_client

    # Note: In langfuse v3, observe is imported directly from langfuse
    LANGFUSE_AVAILABLE = True
except ImportError as e:
    LANGFUSE_AVAILABLE = False
    # Only show detailed error if observability is explicitly enabled
    if os.environ.get("OBSERVABILITY_BACKEND") == "langfuse":
        # Create a temporary logger with proper formatting for import errors
        import_logger = logging.getLogger(__name__)
        if not import_logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s:%(funcName)s:%(lineno)d - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            import_logger.addHandler(handler)
            import_logger.setLevel(logging.ERROR)

        import_logger.error(
            f"Langfuse import failed but OBSERVABILITY_BACKEND=langfuse. "
            f"Import error: {e}. "
            f"Please ensure langfuse is installed: pip install langfuse. "
            f"Or rebuild the container with langfuse dependency."
        )

# Thread-local trace context for correlation
trace_context: ContextVar[Dict[str, Any]] = ContextVar("trace_context", default={})


class SmartLogger:
    """
    Intelligent logger that bridges standard logging with observability tracing.

    This logger maintains backward compatibility with Python's logging module
    while automatically extracting structured data for observability platforms.
    """

    def __init__(self, name: str, enable_tracing: bool = True):
        """
        Initialize the smart logger.

        Args:
            name: Logger name (typically __name__)
            enable_tracing: Whether to enable Langfuse tracing
        """
        self.logger = logging.getLogger(name)
        self.name = name
        self.enable_tracing = enable_tracing and LANGFUSE_AVAILABLE

        # Configure the internal logger with the standard format
        # This ensures consistent formatting even when SmartLogger is used
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            # Use the standard format with function name and line number
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s:%(funcName)s:%(lineno)d - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            # Set default log level from environment
            log_level_str = os.environ.get("LOGGING_LEVEL", "INFO").upper()
            log_level = getattr(logging, log_level_str, logging.INFO)
            self.logger.setLevel(log_level)

        if self.enable_tracing:
            try:
                # Explicit initialization for self-hosted Langfuse
                # Using constructor parameters ensures correct credential passing to OTLP exporter
                self.langfuse = Langfuse(
                    public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
                    secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
                    host=os.environ.get("LANGFUSE_HOST", "http://langfuse-web:3000"),
                    debug=os.environ.get("LANGFUSE_DEBUG", "false").lower() == "true",
                )
                self.logger.info(
                    f"✅ Langfuse client initialized with host: {os.environ.get('LANGFUSE_HOST')}"
                )
            except Exception as e:
                self.logger.warning(f"Failed to initialize Langfuse client: {e}")
                self.logger.warning(
                    f"  LANGFUSE_HOST: {os.environ.get('LANGFUSE_HOST', 'not set')}"
                )
                self.logger.warning(
                    f"  LANGFUSE_BASE_URL: {os.environ.get('LANGFUSE_BASE_URL', 'not set')}"
                )
                self.logger.warning(
                    f"  LANGFUSE_PUBLIC_KEY: {'set' if os.environ.get('LANGFUSE_PUBLIC_KEY') else 'not set'}"
                )
                self.logger.warning(
                    f"  LANGFUSE_SECRET_KEY: {'set' if os.environ.get('LANGFUSE_SECRET_KEY') else 'not set'}"
                )
                self.enable_tracing = False
                self.langfuse = None
        else:
            if not LANGFUSE_AVAILABLE:
                if os.environ.get("OBSERVABILITY_BACKEND") == "langfuse":
                    self.logger.error(
                        "Langfuse module not available but OBSERVABILITY_BACKEND=langfuse"
                    )
                    self.logger.error("  Please install: pip install langfuse")
                    self.logger.error("  Or rebuild container with langfuse dependency")
                else:
                    self.logger.debug("Langfuse not available or tracing disabled.")
            else:
                self.logger.debug("Langfuse tracing disabled by configuration.")
            self.langfuse = None

    def _extract_trace_data(
        self, level: str, msg: str, kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract structured data from log context.

        Args:
            level: Log level (info, warning, error, etc.)
            msg: Log message
            kwargs: Additional keyword arguments

        Returns:
            Dictionary of structured trace data
        """
        # Get caller context
        frame = inspect.currentframe()
        if frame and frame.f_back and frame.f_back.f_back:
            caller_frame = frame.f_back.f_back
            caller_info = {
                "function": caller_frame.f_code.co_name,
                "file": caller_frame.f_code.co_filename,
                "line": caller_frame.f_lineno,
            }
        else:
            caller_info = {}

        # Get current trace context
        ctx = trace_context.get()

        # Extract useful context
        trace_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": msg,
            "logger": self.name,
            **caller_info,
            "trace_id": ctx.get("trace_id"),
            "span_id": ctx.get("span_id"),
            "session_id": kwargs.pop("session_id", ctx.get("session_id")),
            "mcp_session_id": kwargs.pop("mcp_session_id", ctx.get("mcp_session_id")),
            "multi_agent_session_id": kwargs.pop(
                "multi_agent_session_id", ctx.get("multi_agent_session_id")
            ),
            "tool_name": kwargs.pop("tool_name", None),
            "agent_name": kwargs.pop("agent_name", None),
            "model": kwargs.pop("model", None),
            "tokens_used": kwargs.pop("tokens_used", None),
            "duration_ms": kwargs.pop("duration_ms", None),
            "error_type": kwargs.pop("error_type", None),
            "metadata": kwargs,  # Remaining kwargs become metadata
        }

        # Remove None values
        return {k: v for k, v in trace_data.items() if v is not None}

    def _should_trace(self, kwargs: Dict[str, Any]) -> bool:
        """
        Determine if this log should be traced to observability backend.

        Args:
            kwargs: Log keyword arguments

        Returns:
            True if log should be traced
        """
        if not self.enable_tracing:
            return False

        # Explicit trace flag
        if kwargs.get("trace", False):
            return True

        # Auto-trace certain types of logs
        auto_trace_keys = {
            "tool_name",
            "agent_name",
            "session_id",
            "error_type",
            "tokens_used",
            "model",
        }

        return bool(auto_trace_keys.intersection(kwargs.keys()))

    def _send_to_langfuse(self, trace_data: Dict[str, Any]) -> None:
        """
        Send structured data to Langfuse for tracing.

        Args:
            trace_data: Structured trace data
        """
        if not self.langfuse:
            # TODO: Need to have a better fallback or warning here
            return

        try:
            # Determine event type based on content
            if trace_data.get("tool_name"):
                event_name = f"tool_{trace_data['tool_name']}"
                event_type = "span"
            elif trace_data.get("agent_name"):
                event_name = f"agent_{trace_data['agent_name']}"
                event_type = "span"
            elif trace_data.get("error_type"):
                event_name = f"error_{trace_data['error_type']}"
                event_type = "event"
            else:
                event_name = trace_data.get("function", "log")
                event_type = "event"

            # Create appropriate Langfuse object using v3 API
            if event_type == "span":
                # Use start_span for span-like events
                # In v3, start_span uses trace_context parameter
                trace_context = None
                if trace_data.get("trace_id"):
                    trace_context = {
                        "trace_id": trace_data.get("trace_id"),
                    }
                    if trace_data.get("span_id"):
                        trace_context["parent_span_id"] = trace_data.get("span_id")

                span = self.langfuse.start_span(
                    name=event_name,
                    trace_context=trace_context,
                    input=trace_data.get("metadata", {}),
                    metadata=trace_data,
                    level=trace_data["level"].upper(),
                )
                # End the span immediately since this is a log event
                span.end()
            else:
                # Use create_event for event-like logs
                # In v3, create_event uses trace_context parameter
                trace_context = None
                if trace_data.get("trace_id"):
                    trace_context = {
                        "trace_id": trace_data.get("trace_id"),
                    }
                    if trace_data.get("span_id"):
                        trace_context["parent_span_id"] = trace_data.get("span_id")

                self.langfuse.create_event(
                    name=event_name,
                    trace_context=trace_context,
                    metadata=trace_data,
                    level=trace_data["level"].upper(),
                )

            # Flush in background (v3 uses flush() not flush_async())
            self.langfuse.flush()

        except Exception as e:
            # Don't let tracing errors break the application
            self.logger.debug(f"Failed to send to Langfuse: {e}")

    def _log(self, level: str, msg: str, *args, **kwargs) -> None:
        """
        Internal logging method.

        Args:
            level: Log level
            msg: Log message
            args: Positional arguments for message formatting
            kwargs: Keyword arguments
        """
        # Extract trace flag before passing to logger
        should_trace = self._should_trace(kwargs)
        kwargs.pop("trace", None)  # Remove trace flag

        # Log normally
        log_method = getattr(self.logger, level)

        # Separate extra fields for standard logger
        extra = kwargs.pop("extra", {})
        for key in list(kwargs.keys()):
            if key not in ["exc_info", "stack_info", "stacklevel"]:
                extra[key] = kwargs.pop(key)

        if extra:
            kwargs["extra"] = extra

        log_method(msg, *args, **kwargs)

        # Optionally trace
        if should_trace:
            trace_data = self._extract_trace_data(level, msg, extra)
            self._send_to_langfuse(trace_data)

    # Standard logging methods
    def debug(self, msg: str, *args, **kwargs) -> None:
        """Log a debug message."""
        self._log("debug", msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        """Log an info message."""
        self._log("info", msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        """Log a warning message."""
        self._log("warning", msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        """Log an error message."""
        # Auto-trace errors
        kwargs["trace"] = kwargs.get("trace", True)
        if "exc_info" not in kwargs and kwargs.get("trace"):
            kwargs["exc_info"] = True
        self._log("error", msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs) -> None:
        """Log a critical message."""
        # Auto-trace critical events
        kwargs["trace"] = kwargs.get("trace", True)
        self._log("critical", msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        """Log an exception with traceback."""
        kwargs["exc_info"] = True
        kwargs["trace"] = True
        kwargs["error_type"] = "exception"
        self.error(msg, *args, **kwargs)

    # Context management
    @staticmethod
    def set_trace_context(**context) -> None:
        """
        Set trace context for correlation.

        Args:
            **context: Context key-value pairs
        """
        ctx = trace_context.get()
        ctx.update(context)
        trace_context.set(ctx)

    @staticmethod
    def clear_trace_context() -> None:
        """Clear the trace context."""
        trace_context.set({})

    # Tool-specific logging
    def log_tool_execution(
        self,
        tool_name: str,
        input_data: Any,
        output_data: Any = None,
        duration_ms: float = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """
        Log tool execution with structured data.

        Args:
            tool_name: Name of the tool
            input_data: Tool input
            output_data: Tool output
            duration_ms: Execution duration in milliseconds
            success: Whether execution succeeded
            error: Error message if failed
        """
        level = "info" if success else "error"
        msg = f"Tool '{tool_name}' {'completed' if success else 'failed'}"

        self._log(
            level,
            msg,
            trace=True,
            tool_name=tool_name,
            input_size=len(str(input_data)) if input_data else 0,
            output_size=len(str(output_data)) if output_data else 0,
            duration_ms=duration_ms,
            success=success,
            error=error,
        )

    # Agent-specific logging
    def log_agent_execution(
        self,
        agent_name: str,
        action: str,
        metadata: Optional[Dict[str, Any]] = None,
        duration_ms: float = None,
    ) -> None:
        """
        Log agent execution with structured data.

        Args:
            agent_name: Name of the agent
            action: Action being performed
            metadata: Additional metadata
            duration_ms: Execution duration in milliseconds
        """
        self.info(
            f"Agent '{agent_name}' executing '{action}'",
            trace=True,
            agent_name=agent_name,
            action=action,
            duration_ms=duration_ms,
            **(metadata or {}),
        )

    def trace(
        self,
        name: str,
        *,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "TraceContext":
        """Create a structured trace with parent-child span support.

        Returns no-op TraceContext when tracing is disabled.
        """
        from .tracing import TraceContext

        client = self.langfuse if self.enable_tracing else None
        return TraceContext(
            langfuse_client=client,
            name=name,
            session_id=session_id,
            metadata=metadata,
        )


# Convenience function for backward compatibility
def get_smart_logger(name: str, enable_tracing: bool = True) -> SmartLogger:
    """
    Get a smart logger instance.

    Args:
        name: Logger name (typically __name__)
        enable_tracing: Whether to enable tracing

    Returns:
        SmartLogger instance
    """
    return SmartLogger(name, enable_tracing)


# Drop-in replacement for logging.getLogger
def getLogger(name: str = None) -> SmartLogger:
    """
    Drop-in replacement for logging.getLogger that returns a SmartLogger.

    Args:
        name: Logger name

    Returns:
        SmartLogger instance
    """
    return SmartLogger(name or __name__)


def create_trace(logger_instance, name, *, session_id=None, metadata=None):
    """Create a trace from any logger. Returns no-op TraceContext for non-SmartLogger."""
    if hasattr(logger_instance, "trace"):
        return logger_instance.trace(name, session_id=session_id, metadata=metadata)
    from .tracing import TraceContext

    return TraceContext(
        langfuse_client=None, name=name, session_id=session_id, metadata=metadata
    )


# Decorator for observing function execution using Langfuse
def observe(name: str = None, capture_input: bool = True, capture_output: bool = True):
    """
    Decorator to observe function execution with Langfuse tracing.

    This is a wrapper around Langfuse's observe decorator that provides
    a consistent interface even when Langfuse is not available.

    Args:
        name: Custom name for the observation (defaults to function name)
        capture_input: Whether to capture function inputs
        capture_output: Whether to capture function outputs

    Returns:
        Decorated function with observability
    """
    try:
        from langfuse import observe as langfuse_observe

        # Use Langfuse's native decorator when available (v3 API)
        return langfuse_observe(
            name=name, capture_input=capture_input, capture_output=capture_output
        )
    except ImportError:
        # Fallback: No-op decorator when Langfuse is not available
        def decorator(func):
            return func

        return decorator
