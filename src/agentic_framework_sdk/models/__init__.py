"""
Models package for Agentic Framework SDK.

This package contains all the request and response models used by the SDK,
providing type-safe interfaces for API interactions.
"""

from .requests import (
    ChatCompletionRequest,
    CompletionRequest,
    AssistantCreateRequest,
    ThreadCreateRequest,
    MessageCreateRequest,
    RunCreateRequest,
    AgentInvokeRequest,
    ToolRegistrationRequest,
    SessionCreateRequest,
    ToolACLUpdateRequest,
)

from .responses import (
    ChatCompletionResponse,
    CompletionResponse,
    ModelResponse,
    FileResponse,
    AssistantResponse,
    ThreadResponse,
    MessageResponse,
    RunResponse,
    AgentInvokeResponse,
    ToolRegistrationResponse,
    SessionResponse,
    ErrorResponse,
    Choice,
    Usage,
)

__all__ = [
    # Request models
    "ChatCompletionRequest",
    "CompletionRequest", 
    "AssistantCreateRequest",
    "ThreadCreateRequest",
    "MessageCreateRequest",
    "RunCreateRequest",
    "AgentInvokeRequest",
    "ToolRegistrationRequest",
    "SessionCreateRequest",
    "ToolACLUpdateRequest",
    
    # Response models
    "ChatCompletionResponse",
    "CompletionResponse",
    "ModelResponse",
    "FileResponse",
    "AssistantResponse",
    "ThreadResponse",
    "MessageResponse",
    "RunResponse",
    "AgentInvokeResponse",
    "ToolRegistrationResponse",
    "SessionResponse",
    "ErrorResponse",
    "Choice",
    "Usage",
]