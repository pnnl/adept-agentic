import json  # Using json.dumps for args for better readability
import logging
import os
import sys


def get_ephemeral_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Create an ephemeral logger with proper formatting for internal framework messages.

    This is used for logging framework-level messages (imports, fallbacks, etc.)
    without interfering with the user's logger configuration.

    Args:
        name: Logger name
        level: Logging level (default: INFO)

    Returns:
        Configured logger with standard format
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s:%(funcName)s:%(lineno)d - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(level)
    return logger


# Try to import SmartLogger for observability if available
try:
    from agentic_framework_pkg.core.observability import get_smart_logger

    OBSERVABILITY_AVAILABLE = True
except ImportError as e:
    OBSERVABILITY_AVAILABLE = False
    get_smart_logger = None
    # Use utility function for import warning
    import_logger = get_ephemeral_logger(__name__, logging.WARNING)
    import_logger.warning(
        f"Could not import SmartLogger for observability: {e}. "
        f"This is expected if langfuse is not installed. "
        f"To enable observability, install langfuse: pip install langfuse"
    )

# Attempt to import Langchain message types. If not available, the formatter will still work but won't pretty-print them.
try:
    from langchain_core.messages import (
        AIMessage,
        BaseMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )

    LANGCHAIN_MESSAGES_AVAILABLE = True
except ImportError:
    LANGCHAIN_MESSAGES_AVAILABLE = False

    # Define dummy classes if langchain_core is not available, so the formatter doesn't break
    class BaseMessage:
        pass

    class AIMessage(BaseMessage):
        pass

    class HumanMessage(BaseMessage):
        pass

    class SystemMessage(BaseMessage):
        pass

    class ToolMessage(BaseMessage):
        pass


DEFAULT_LOG_LEVEL_STR = "INFO"  # Changed to string for os.environ.get
LOG_LEVEL_STR = os.environ.get("LOGGING_LEVEL", DEFAULT_LOG_LEVEL_STR).upper()
LOG_LEVEL = getattr(
    logging, LOG_LEVEL_STR, logging.INFO
)  # Convert string to logging level

DEFAULT_LOG_FORMAT = (
    "%(asctime)s - %(name)s:%(funcName)s:%(lineno)d - %(levelname)s - %(message)s"
)


class ReadableLangchainMessageFormatter(logging.Formatter):
    """
    A custom logging.Formatter to produce more readable output for Langchain messages.
    """

    def _format_message(self, message: BaseMessage) -> str:
        if not LANGCHAIN_MESSAGES_AVAILABLE:
            return str(message)

        if isinstance(message, AIMessage):
            tool_calls_summary = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    args_str = json.dumps(tc.get("args", {}))
                    tool_calls_summary.append(
                        f"ToolCall(name='{tc.get('name')}', args={args_str}, id='{tc.get('id')}')"
                    )
            usage_summary_parts = []
            if message.usage_metadata:
                if message.usage_metadata.get("input_tokens") is not None:
                    usage_summary_parts.append(
                        f"in:{message.usage_metadata['input_tokens']}"
                    )
                if message.usage_metadata.get("output_tokens") is not None:
                    usage_summary_parts.append(
                        f"out:{message.usage_metadata['output_tokens']}"
                    )
                if message.usage_metadata.get("total_tokens") is not None:
                    usage_summary_parts.append(
                        f"total:{message.usage_metadata['total_tokens']}"
                    )
            usage_summary = (
                f", Usage({', '.join(usage_summary_parts)})"
                if usage_summary_parts
                else ""
            )
            content_display = (
                message.content[:100] + "..."
                if len(message.content) > 100
                else message.content
            )
            finish_reason = (
                message.response_metadata.get("finish_reason", "N/A")
                if message.response_metadata
                else "N/A"
            )
            return (
                f"AIMessage(id='{message.id}', content='{content_display}', "
                f"finish_reason='{finish_reason}', "
                f"tool_calls=[{'; '.join(tool_calls_summary)}]{usage_summary})"
            )
        elif isinstance(
            message, (HumanMessage, SystemMessage, ToolMessage)
        ):  # Simplified for brevity
            content_display = (
                message.content[:100] + "..."
                if len(message.content) > 100
                else message.content
            )
            return f"{type(message).__name__}(id='{message.id}', content='{content_display}')"
        return str(message)

    def format(self, record: logging.LogRecord) -> str:
        if LANGCHAIN_MESSAGES_AVAILABLE:
            if isinstance(record.msg, BaseMessage):
                record.msg = self._format_message(record.msg)
            if record.args and isinstance(record.args, tuple):
                new_args = [
                    self._format_message(arg) if isinstance(arg, BaseMessage) else arg
                    for arg in record.args
                ]
                record.args = tuple(new_args)
        return super().format(record)


def get_logger(logger_name: str, level: int = LOG_LEVEL) -> logging.Logger:
    """
    Creates and configures a logger instance.

    If observability is enabled and SmartLogger is available, returns a SmartLogger
    instance for automatic tracing. Otherwise, returns a standard Python logger.

    Args:
        logger_name: The name for the logger (typically __name__).
        level: The logging level.

    Returns:
        A configured logging.Logger instance (or SmartLogger if observability enabled).
    """
    # Check if we should use SmartLogger for observability
    observability_backend = os.environ.get("OBSERVABILITY_BACKEND", "none")
    use_smart_logger = (
        OBSERVABILITY_AVAILABLE
        and get_smart_logger is not None
        and observability_backend == "langfuse"
    )

    if use_smart_logger:
        # Return SmartLogger for observability
        # SmartLogger handles its own formatting and handlers
        return get_smart_logger(logger_name)

    # Log why we're not using SmartLogger (only once per process)
    if not hasattr(get_logger, "_logged_fallback_reason"):
        get_logger._logged_fallback_reason = True
        # Use utility function for fallback messages
        fallback_logger = get_ephemeral_logger(__name__, logging.INFO)

        if observability_backend == "langfuse" and not OBSERVABILITY_AVAILABLE:
            fallback_logger.info(
                f"Falling back to standard Python logger for {logger_name}. "
                f"Reason: SmartLogger not available (langfuse not installed). "
                f"OBSERVABILITY_BACKEND: {observability_backend}"
            )
        elif observability_backend != "langfuse" and observability_backend != "none":
            fallback_logger.info(
                f"Unknown OBSERVABILITY_BACKEND: {observability_backend}"
            )

    # Fall back to standard Python logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    # Add console handler if no handlers are configured
    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        # Use the custom formatter
        formatter = ReadableLangchainMessageFormatter(DEFAULT_LOG_FORMAT)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger
