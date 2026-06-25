"""
Request model classes for the Agentic Framework SDK.

These models provide structured representations for API requests
compatible with OpenAI's API format while supporting UCS extensions.
"""

from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field


@dataclass
class ChatCompletionRequest:
    """OpenAI-compatible chat completion request."""
    model: str
    messages: List[Dict[str, Any]]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = None
    stream: bool = False
    stop: Optional[Union[str, List[str]]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Dict[str, int]] = None
    user: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    
    # UCS Extensions
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class CompletionRequest:
    """OpenAI-compatible completion request."""
    model: str
    prompt: Union[str, List[str]]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = None
    stream: bool = False
    logprobs: Optional[int] = None
    echo: bool = False
    stop: Optional[Union[str, List[str]]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    best_of: Optional[int] = None
    logit_bias: Optional[Dict[str, int]] = None
    user: Optional[str] = None
    
    # UCS Extensions
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


@dataclass
class AssistantCreateRequest:
    """Assistant creation request."""
    model: str
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    file_ids: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ThreadCreateRequest:
    """Thread creation request."""
    messages: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class MessageCreateRequest:
    """Message creation request."""
    role: str
    content: str
    file_ids: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class RunCreateRequest:
    """Run creation request."""
    assistant_id: str
    model: Optional[str] = None
    instructions: Optional[str] = None
    additional_instructions: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None


# UCS Extension Request Models

@dataclass
class AgentInvokeRequest:
    """Agent invocation request."""
    input: str
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    tools: Optional[List[str]] = None
    max_execution_time: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ToolRegistrationRequest:
    """Tool registration request."""
    name: str
    description: str
    args_schema: Dict[str, Any]
    invocation: Dict[str, Any]
    acl: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.acl is None:
            self.acl = {"global": False, "users": [], "groups": []}
        if self.metadata is None:
            self.metadata = {}


@dataclass
class SessionCreateRequest:
    """Session creation request."""
    agent_id: Optional[str] = None
    initial_context: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    ttl: Optional[int] = None  # Time to live in seconds


@dataclass
class ToolACLUpdateRequest:
    """Tool ACL update request."""
    global_access: bool = False
    users: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)