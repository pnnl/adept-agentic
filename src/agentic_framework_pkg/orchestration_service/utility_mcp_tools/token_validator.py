"""
Token validation utilities for session introspection tools.

Provides token counting with tiktoken and response size validation
to prevent context window overflow and recommend auto-export strategies.
"""

import json
from typing import Any, Dict, Optional

try:
    import tiktoken
except ImportError:
    tiktoken = None

from ...logger_config import get_logger

logger = get_logger(__name__)


def count_response_tokens(data: Any, model: str = "gpt-4") -> int:
    """
    Count tokens in JSON response data using tiktoken.

    Args:
        data: Any JSON-serializable data structure
        model: Model identifier for tiktoken encoding (default: gpt-4)

    Returns:
        Token count (int)

    Raises:
        ImportError: If tiktoken is not installed
    """
    if tiktoken is None:
        raise ImportError(
            "tiktoken is required for token counting. Install with: pip install tiktoken"
        )

    # Serialize data to JSON string
    try:
        json_str = json.dumps(data, indent=2)
    except (TypeError, ValueError) as e:
        logger.warning(f"Failed to serialize data to JSON: {e}")
        return 0

    # Get encoding for model
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        # Fallback to cl100k_base for unknown models (GPT-4, GPT-3.5-turbo)
        logger.warning(
            f"Model '{model}' not found in tiktoken, using cl100k_base encoding"
        )
        encoding = tiktoken.get_encoding("cl100k_base")

    # Count tokens
    tokens = encoding.encode(json_str)
    return len(tokens)


def validate_response_size(
    data: Any,
    max_tokens: int = 100000,
    model: str = "gpt-4",
    warn_threshold: float = 0.5,
) -> Dict[str, Any]:
    """
    Validate response size and return recommendations.

    Thresholds:
    - Small (<50% of max_tokens): Return data as-is
    - Medium (50-100% of max_tokens): Return data with warning
    - Large (>100% of max_tokens): Recommend auto-export

    Args:
        data: Response data to validate
        max_tokens: Maximum token threshold (default: 100,000)
        model: Model identifier for tiktoken encoding (default: gpt-4)
        warn_threshold: Threshold ratio for warnings (default: 0.5 = 50%)

    Returns:
        Dict with validation results:
        {
            "token_count": int,
            "max_tokens": int,
            "size_category": str,  # "small", "medium", "large"
            "should_export": bool,
            "should_warn": bool,
            "warning_message": Optional[str],
            "recommendation": str,
        }
    """
    # Count tokens
    try:
        token_count = count_response_tokens(data, model=model)
    except ImportError as e:
        logger.error(f"tiktoken not available: {e}")
        return {
            "token_count": 0,
            "max_tokens": max_tokens,
            "size_category": "unknown",
            "should_export": False,
            "should_warn": False,
            "warning_message": "Token counting unavailable (tiktoken not installed)",
            "recommendation": "Install tiktoken for response size validation",
        }

    # Calculate thresholds
    warn_token_threshold = int(max_tokens * warn_threshold)

    # Determine size category
    if token_count > max_tokens:
        size_category = "large"
        should_export = True
        should_warn = True
        warning_message = (
            f"Response size ({token_count:,} tokens) exceeds context window limit "
            f"({max_tokens:,} tokens). Auto-export recommended."
        )
        recommendation = (
            "Response size exceeds context window. Consider exporting to file "
            "or using more specific query filters (date range, limit, etc.)."
        )
    elif token_count > warn_token_threshold:
        size_category = "medium"
        should_export = False
        should_warn = True
        percentage = int((token_count / max_tokens) * 100)
        warning_message = (
            f"Response size ({token_count:,} tokens) is {percentage}% of context window "
            f"limit ({max_tokens:,} tokens). Consider using filters to reduce size."
        )
        recommendation = (
            "Response size is large but within limits. Consider narrowing query "
            "filters if you plan to ask follow-up questions."
        )
    else:
        size_category = "small"
        should_export = False
        should_warn = False
        warning_message = None
        recommendation = "Response size is optimal for context window."

    return {
        "token_count": token_count,
        "max_tokens": max_tokens,
        "size_category": size_category,
        "should_export": should_export,
        "should_warn": should_warn,
        "warning_message": warning_message,
        "recommendation": recommendation,
    }


def get_model_context_limit(model: str) -> int:
    """
    Get the context window limit for a given model.

    Args:
        model: Model identifier

    Returns:
        Context window size in tokens (default: 100,000 for unknown models)
    """
    # Common model context limits (as of 2025)
    model_limits = {
        "gpt-4": 8192,
        "gpt-4-32k": 32768,
        "gpt-4-turbo": 128000,
        "gpt-4-turbo-preview": 128000,
        "gpt-3.5-turbo": 16385,
        "gpt-3.5-turbo-16k": 16385,
        "claude-2": 100000,
        "claude-2.1": 200000,
        "claude-3-opus": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-haiku": 200000,
    }

    # Normalize model name (remove version suffixes)
    model_normalized = model.lower().split(":")[0]

    return model_limits.get(model_normalized, 100000)
