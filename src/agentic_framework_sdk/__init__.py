"""
Agentic Framework SDK

OpenAI-compatible Python SDK for the Agentic Framework with UCS extensions.
Provides drop-in replacement for openai library with specialized scientific capabilities.
"""

from .client import OpenAI, AsyncOpenAI
from .exceptions import (
    APIError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    RateLimitError,
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    ConflictError,
    InternalServerError,
    UnprocessableEntityError,
    ValidationError,
)
from .models import (
    ChatCompletionRequest,
    CompletionRequest,
    ChatCompletionResponse,
    CompletionResponse,
    Choice,
    Usage,
)

# Expose submodules for unit tests and CLI functionality
from . import cli
from . import bin

# Version info
__version__ = "1.0.20260622"
__author__ = "ADEPT Agentic Framework Team"
__email__ = "paul.rigor@pnnl.gov"

# Default exports for drop-in compatibility
__all__ = [
    "OpenAI",
    "AsyncOpenAI",
    "APIError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "BadRequestError",
    "ConflictError",
    "InternalServerError",
    "UnprocessableEntityError",
    "ValidationError",
    "ChatCompletionRequest",
    "CompletionRequest",
    "ChatCompletionResponse",
    "CompletionResponse",
    "Choice",
    "Usage",
    "cli",
    "bin",
]
