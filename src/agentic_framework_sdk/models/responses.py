"""
Response model classes for the Agentic Framework SDK.

These models provide structured representations of API responses
compatible with OpenAI's API format while supporting UCS extensions.
"""

from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Choice:
    """Represents a choice in a completion response."""
    index: int
    message: Optional[Dict[str, Any]] = None
    text: Optional[str] = None
    finish_reason: Optional[str] = None
    logprobs: Optional[Dict[str, Any]] = None


@dataclass
class Usage:
    """Token usage information."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatCompletionResponse:
    """OpenAI-compatible chat completion response."""
    id: str
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: List[Choice] = None
    usage: Optional[Usage] = None
    system_fingerprint: Optional[str] = None
    # Phase 3B: session fork metadata (context auto-compaction)
    session_fork: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.choices is None:
            self.choices = []
        if self.created == 0:
            self.created = int(datetime.now().timestamp())


@dataclass
class CompletionResponse:
    """OpenAI-compatible completion response."""
    id: str
    object: str = "text_completion"
    created: int = 0
    model: str = ""
    choices: List[Choice] = None
    usage: Optional[Usage] = None
    
    def __post_init__(self):
        if self.choices is None:
            self.choices = []
        if self.created == 0:
            self.created = int(datetime.now().timestamp())


@dataclass
class ModelResponse:
    """Model information response."""
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "agentic-framework"
    capabilities: Optional[List[str]] = None
    
    def __post_init__(self):
        if self.created == 0:
            self.created = int(datetime.now().timestamp())
        if self.capabilities is None:
            self.capabilities = []


@dataclass
class FileResponse:
    """File upload/info response."""
    id: str
    object: str = "file"
    bytes: int = 0
    created_at: int = 0
    filename: str = ""
    purpose: str = "assistants"
    
    def __post_init__(self):
        if self.created_at == 0:
            self.created_at = int(datetime.now().timestamp())


@dataclass
class ResponseCompletionChoice:
    """Represents a choice in a Response API completion."""
    index: int
    message: Dict[str, Any]
    finish_reason: Optional[str] = None
    logprobs: Optional[Dict[str, Any]] = None

    def __getitem__(self, key):
        """Support dict-like access for backward compatibility."""
        return getattr(self, key, None)

    def get(self, key, default=None):
        """Support dict get method."""
        return getattr(self, key, default)


@dataclass
class ResponseCompletionResponse:
    """Response API completion response model."""
    id: str
    object: str = "response.completion"
    created: int = 0
    model: str = ""
    choices: List[ResponseCompletionChoice] = None
    usage: Optional[Usage] = None
    # Multi-tier session management
    session_id: Optional[str] = None
    mcp_session_id: Optional[str] = None
    multi_agent_session_id: Optional[str] = None
    gateway_session_id: Optional[str] = None
    # Additional metadata
    system_fingerprint: Optional[str] = None
    # Phase 3B: session fork metadata (context auto-compaction)
    session_fork: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.choices is None:
            self.choices = []
        if self.created == 0:
            self.created = int(datetime.now().timestamp())

    def __getitem__(self, key):
        """Support dict-like access for backward compatibility."""
        return getattr(self, key, None)

    def get(self, key, default=None):
        """Support dict get method."""
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        """Convert response to dictionary format."""
        result = {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "model": self.model,
            "choices": [
                {
                    "index": c.index,
                    "message": c.message,
                    "finish_reason": c.finish_reason,
                    "logprobs": c.logprobs
                } for c in self.choices
            ]
        }

        if self.usage:
            result["usage"] = {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens
            }

        # Add session IDs if present
        if self.session_id:
            result["session_id"] = self.session_id
        if self.mcp_session_id:
            result["mcp_session_id"] = self.mcp_session_id
        if self.multi_agent_session_id:
            result["multi_agent_session_id"] = self.multi_agent_session_id
        if self.gateway_session_id:
            result["gateway_session_id"] = self.gateway_session_id

        if self.system_fingerprint:
            result["system_fingerprint"] = self.system_fingerprint

        if self.session_fork:
            result["session_fork"] = self.session_fork

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ResponseCompletionResponse':
        """Create ResponseCompletionResponse from dictionary."""
        choices = []
        for choice_data in data.get("choices", []):
            choices.append(ResponseCompletionChoice(
                index=choice_data.get("index", 0),
                message=choice_data.get("message", {}),
                finish_reason=choice_data.get("finish_reason"),
                logprobs=choice_data.get("logprobs")
            ))

        usage = None
        if "usage" in data:
            usage = Usage(
                prompt_tokens=data["usage"].get("prompt_tokens", 0),
                completion_tokens=data["usage"].get("completion_tokens", 0),
                total_tokens=data["usage"].get("total_tokens", 0)
            )

        return cls(
            id=data.get("id", ""),
            object=data.get("object", "response.completion"),
            created=data.get("created", 0),
            model=data.get("model", ""),
            choices=choices,
            usage=usage,
            session_id=data.get("session_id"),
            mcp_session_id=data.get("mcp_session_id"),
            multi_agent_session_id=data.get("multi_agent_session_id"),
            gateway_session_id=data.get("gateway_session_id"),
            system_fingerprint=data.get("system_fingerprint"),
            session_fork=data.get("session_fork"),
        )


@dataclass
class ResponseStreamDelta:
    """Represents a delta in a streaming Response API completion."""
    content: Optional[str] = None
    role: Optional[str] = None
    function_call: Optional[Dict[str, Any]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


@dataclass
class ResponseStreamChoice:
    """Represents a choice in a streaming Response API completion."""
    index: int
    delta: ResponseStreamDelta
    finish_reason: Optional[str] = None
    logprobs: Optional[Dict[str, Any]] = None


@dataclass
class ResponseStreamChunk:
    """Response API streaming chunk model."""
    id: str
    object: str = "response.completion.chunk"
    created: int = 0
    model: str = ""
    choices: List[ResponseStreamChoice] = None
    # Session IDs may be included in first chunk
    session_id: Optional[str] = None
    mcp_session_id: Optional[str] = None

    def __post_init__(self):
        if self.choices is None:
            self.choices = []
        if self.created == 0:
            self.created = int(datetime.now().timestamp())

    def to_dict(self) -> Dict[str, Any]:
        """Convert stream chunk to dictionary format."""
        result = {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "model": self.model,
            "choices": [
                {
                    "index": c.index,
                    "delta": {
                        "content": c.delta.content,
                        "role": c.delta.role,
                        "function_call": c.delta.function_call,
                        "tool_calls": c.delta.tool_calls
                    } if c.delta else {},
                    "finish_reason": c.finish_reason,
                    "logprobs": c.logprobs
                } for c in self.choices
            ]
        }

        if self.session_id:
            result["session_id"] = self.session_id
        if self.mcp_session_id:
            result["mcp_session_id"] = self.mcp_session_id

        return result


@dataclass
class AssistantResponse:
    """Assistant creation/info response."""
    id: str
    object: str = "assistant"
    created_at: int = 0
    name: Optional[str] = None
    description: Optional[str] = None
    model: str = ""
    instructions: Optional[str] = None
    tools: List[Dict[str, Any]] = None
    file_ids: List[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.created_at == 0:
            self.created_at = int(datetime.now().timestamp())
        if self.tools is None:
            self.tools = []
        if self.file_ids is None:
            self.file_ids = []
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ThreadResponse:
    """Thread creation/info response."""
    id: str
    object: str = "thread"
    created_at: int = 0
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.created_at == 0:
            self.created_at = int(datetime.now().timestamp())
        if self.metadata is None:
            self.metadata = {}


@dataclass
class MessageResponse:
    """Message creation/info response."""
    id: str
    object: str = "thread.message"
    created_at: int = 0
    thread_id: str = ""
    role: str = "user"
    content: List[Dict[str, Any]] = None
    file_ids: List[str] = None
    assistant_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.created_at == 0:
            self.created_at = int(datetime.now().timestamp())
        if self.content is None:
            self.content = []
        if self.file_ids is None:
            self.file_ids = []
        if self.metadata is None:
            self.metadata = {}


@dataclass
class RunResponse:
    """Run creation/info response."""
    id: str
    object: str = "thread.run"
    created_at: int = 0
    thread_id: str = ""
    assistant_id: str = ""
    status: str = "queued"
    required_action: Optional[Dict[str, Any]] = None
    last_error: Optional[Dict[str, Any]] = None
    expires_at: Optional[int] = None
    started_at: Optional[int] = None
    cancelled_at: Optional[int] = None
    failed_at: Optional[int] = None
    completed_at: Optional[int] = None
    model: str = ""
    instructions: Optional[str] = None
    tools: List[Dict[str, Any]] = None
    file_ids: List[str] = None
    metadata: Dict[str, Any] = None
    usage: Optional[Usage] = None
    
    def __post_init__(self):
        if self.created_at == 0:
            self.created_at = int(datetime.now().timestamp())
        if self.tools is None:
            self.tools = []
        if self.file_ids is None:
            self.file_ids = []
        if self.metadata is None:
            self.metadata = {}


# UCS Extension Response Models

@dataclass
class AgentInvokeResponse:
    """Response from agent invocation."""
    output: str
    session_id: str
    agent_id: Optional[str] = None
    metadata: Dict[str, Any] = None
    tools_used: List[str] = None
    execution_time: Optional[float] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.tools_used is None:
            self.tools_used = []


@dataclass
class ToolRegistrationResponse:
    """Response from tool registration."""
    status: str = "success"
    message: str = ""
    tool_id: Optional[str] = None
    tool_name: Optional[str] = None


@dataclass
class SessionResponse:
    """Session creation/info response."""
    id: str
    status: str = "active"
    created_at: int = 0
    last_accessed: Optional[int] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.created_at == 0:
            self.created_at = int(datetime.now().timestamp())
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ErrorResponse:
    """Standard error response format."""
    error: Dict[str, Any]
    
    def __post_init__(self):
        # Ensure error dict has required fields
        if "type" not in self.error:
            self.error["type"] = "api_error"
        if "message" not in self.error:
            self.error["message"] = "An error occurred"