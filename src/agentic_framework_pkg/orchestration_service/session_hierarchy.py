"""
Session Hierarchy Management for Hybrid Architecture

This module defines the SessionHierarchy data model and related utilities
for managing multi-tier session contexts in the hybrid orchestration approach.

The SessionHierarchy preserves all four session tiers while enabling
efficient agent persistence and reuse.
"""

import time
import uuid
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from enum import Enum


class SessionTier(Enum):
    """Enumeration of session tier types"""
    BASIC = "session_id"              # Basic user session
    TOOL_PERSISTENCE = "mcp_session_id"     # Tool persistence context
    MULTI_AGENT = "multi_agent_session_id"  # Team coordination
    GATEWAY_MESH = "gateway_session_id"     # A2A delegation


class InteractionType(Enum):
    """Types of interactions supported by the session hierarchy"""
    DIRECT_USER = "direct_user"              # Direct user interaction (Streamlit, CLI)
    MULTI_AGENT_COORDINATION = "multi_agent" # Multi-agent team workflow
    A2A_DELEGATION = "a2a_delegation"        # Agent-to-agent cross-gateway
    API_COMPATIBILITY = "api_compat"         # OpenAI API compatibility layer


@dataclass
class SessionHierarchy:
    """
    Complete multi-tier session hierarchy for hybrid architecture.
    
    This data structure preserves all session context while enabling
    efficient agent persistence and inter-service communication.
    """
    # Core session identifiers (4-tier hierarchy)
    session_id: str                          # Basic user session
    mcp_session_id: Optional[str] = None     # Tool persistence context
    multi_agent_session_id: Optional[str] = None  # Team coordination
    gateway_session_id: Optional[str] = None      # A2A delegation
    
    # Lifecycle metadata
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    interaction_count: int = 0
    
    # Session context and capabilities
    interaction_type: InteractionType = InteractionType.DIRECT_USER
    supports_a2a: bool = field(init=False)
    supports_multi_agent: bool = field(init=False)
    
    # A2A delegation context (for cross-gateway workflows)
    delegation_source: Optional[str] = None
    delegation_chain: List[str] = field(default_factory=list)
    return_path: Optional[Dict[str, Any]] = None
    
    # OpenAI API compatibility context
    assistant_id: Optional[str] = None
    thread_id: Optional[str] = None
    
    def __post_init__(self):
        """Initialize computed fields after creation"""
        self.supports_a2a = bool(self.gateway_session_id)
        self.supports_multi_agent = bool(self.multi_agent_session_id)
        
        # Generate mcp_session_id if not provided
        if not self.mcp_session_id:
            self.mcp_session_id = f"{self.session_id}::mcp-{uuid.uuid4().hex[:8]}"
    
    def refresh_usage(self) -> None:
        """Update last_used timestamp and interaction count"""
        self.last_used = time.time()
        self.interaction_count += 1
    
    def get_pool_key(self) -> str:
        """
        Generate a unique pool key for agent caching.
        
        The pool key includes all relevant session tiers to ensure
        proper isolation between different session contexts.
        """
        key_parts = [f"session:{self.session_id}"]
        
        if self.mcp_session_id:
            key_parts.append(f"mcp:{self.mcp_session_id}")
        
        if self.multi_agent_session_id:
            key_parts.append(f"multi:{self.multi_agent_session_id}")
        
        if self.gateway_session_id:
            key_parts.append(f"gateway:{self.gateway_session_id}")
        
        return "||".join(key_parts)
    
    def get_session_context_dict(self) -> Dict[str, Optional[str]]:
        """
        Get complete session context as dictionary for tool binding.
        
        Returns all session tier IDs that tools may need for context.
        """
        return {
            "session_id": self.session_id,
            "mcp_session_id": self.mcp_session_id,
            "multi_agent_session_id": self.multi_agent_session_id,
            "gateway_session_id": self.gateway_session_id
        }
    
    def is_expired(self, ttl_seconds: int = 3600) -> bool:
        """
        Check if session hierarchy has expired.
        
        Args:
            ttl_seconds: Time-to-live in seconds (default: 1 hour)
        """
        return (time.time() - self.last_used) > ttl_seconds
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization/API responses"""
        return {
            "session_id": self.session_id,
            "mcp_session_id": self.mcp_session_id,
            "multi_agent_session_id": self.multi_agent_session_id,
            "gateway_session_id": self.gateway_session_id,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "interaction_count": self.interaction_count,
            "interaction_type": self.interaction_type.value,
            "supports_a2a": self.supports_a2a,
            "supports_multi_agent": self.supports_multi_agent,
            "delegation_source": self.delegation_source,
            "delegation_chain": self.delegation_chain,
            "return_path": self.return_path,
            "assistant_id": self.assistant_id,
            "thread_id": self.thread_id,
            "pool_key": self.get_pool_key()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionHierarchy':
        """Create SessionHierarchy from dictionary"""
        # Extract core fields
        hierarchy = cls(
            session_id=data["session_id"],
            mcp_session_id=data.get("mcp_session_id"),
            multi_agent_session_id=data.get("multi_agent_session_id"),
            gateway_session_id=data.get("gateway_session_id"),
            created_at=data.get("created_at", time.time()),
            last_used=data.get("last_used", time.time()),
            interaction_count=data.get("interaction_count", 0),
            interaction_type=InteractionType(data.get("interaction_type", "direct_user")),
            delegation_source=data.get("delegation_source"),
            delegation_chain=data.get("delegation_chain", []),
            return_path=data.get("return_path"),
            assistant_id=data.get("assistant_id"),
            thread_id=data.get("thread_id")
        )
        return hierarchy
    
    @classmethod
    def create_for_direct_user(cls, session_id: str, assistant_id: Optional[str] = None, 
                              thread_id: Optional[str] = None) -> 'SessionHierarchy':
        """
        Create session hierarchy for direct user interaction (Streamlit, CLI).
        
        This is the simplest case - just basic user session with tool persistence.
        """
        return cls(
            session_id=session_id,
            interaction_type=InteractionType.DIRECT_USER,
            assistant_id=assistant_id,
            thread_id=thread_id
        )
    
    @classmethod 
    def create_for_multi_agent(cls, session_id: str, multi_agent_session_id: str,
                              gateway_session_id: Optional[str] = None) -> 'SessionHierarchy':
        """
        Create session hierarchy for multi-agent coordination.
        
        Includes team coordination session and optional cross-gateway support.
        """
        return cls(
            session_id=session_id,
            multi_agent_session_id=multi_agent_session_id,
            gateway_session_id=gateway_session_id,
            interaction_type=InteractionType.MULTI_AGENT_COORDINATION
        )
    
    @classmethod
    def create_for_a2a_delegation(cls, original_hierarchy: 'SessionHierarchy',
                                 gateway_session_id: str, delegation_source: str,
                                 delegation_chain: List[str] = None) -> 'SessionHierarchy':
        """
        Create session hierarchy for A2A delegation across gateways.
        
        Preserves original session context while adding delegation metadata.
        """
        return cls(
            session_id=original_hierarchy.session_id,
            mcp_session_id=original_hierarchy.mcp_session_id,
            multi_agent_session_id=original_hierarchy.multi_agent_session_id,
            gateway_session_id=gateway_session_id,
            interaction_type=InteractionType.A2A_DELEGATION,
            delegation_source=delegation_source,
            delegation_chain=delegation_chain or [],
            return_path={"target_gateway": delegation_source}
        )
    
    def __str__(self) -> str:
        """Human-readable string representation"""
        parts = [f"session:{self.session_id}"]
        if self.multi_agent_session_id:
            parts.append(f"team:{self.multi_agent_session_id}")
        if self.gateway_session_id:
            parts.append(f"gateway:{self.gateway_session_id}")
        
        return f"SessionHierarchy({', '.join(parts)}, type:{self.interaction_type.value})"


class SessionHierarchyBuilder:
    """
    Builder utility for creating session hierarchies from various contexts.
    
    This helps extract and construct SessionHierarchy instances from different
    sources like OpenAI API requests, direct service calls, etc.
    """
    
    @staticmethod
    def from_openai_context(thread_id: str, assistant_id: Optional[str] = None) -> SessionHierarchy:
        """
        Build session hierarchy from OpenAI API context.
        
        Extracts session information from OpenAI thread/assistant IDs.
        """
        # Extract base session from thread_id if it follows our naming convention
        if "::" in thread_id:
            base_session = thread_id.split("::")[0]
        else:
            base_session = f"openai-{thread_id}"
        
        return SessionHierarchy.create_for_direct_user(
            session_id=base_session,
            assistant_id=assistant_id,
            thread_id=thread_id
        )
    
    @staticmethod
    def from_request_headers(headers: Dict[str, str]) -> Optional[SessionHierarchy]:
        """
        Build session hierarchy from request headers.
        
        Extracts session context from X-Session-* headers.
        """
        session_id = headers.get("x-session-id")
        if not session_id:
            return None
        
        return SessionHierarchy(
            session_id=session_id,
            mcp_session_id=headers.get("x-mcp-session-id"),
            multi_agent_session_id=headers.get("x-multi-agent-session-id"),
            gateway_session_id=headers.get("x-gateway-session-id"),
            interaction_type=InteractionType(headers.get("x-interaction-type", "direct_user"))
        )
    
    @staticmethod
    def from_service_request(request_context: Dict[str, Any]) -> SessionHierarchy:
        """
        Build session hierarchy from service request context.
        
        This is the most flexible builder that can handle various input formats.
        """
        # Check if we already have a complete hierarchy
        if "session_hierarchy" in request_context:
            return SessionHierarchy.from_dict(request_context["session_hierarchy"])
        
        # Build from individual session components
        session_id = request_context.get("session_id")
        if not session_id:
            # Generate one if none provided
            session_id = f"auto-{uuid.uuid4().hex[:12]}"
        
        # Determine interaction type
        if request_context.get("gateway_session_id"):
            interaction_type = InteractionType.A2A_DELEGATION
        elif request_context.get("multi_agent_session_id"):
            interaction_type = InteractionType.MULTI_AGENT_COORDINATION
        else:
            interaction_type = InteractionType.DIRECT_USER
        
        return SessionHierarchy(
            session_id=session_id,
            mcp_session_id=request_context.get("mcp_session_id"),
            multi_agent_session_id=request_context.get("multi_agent_session_id"),
            gateway_session_id=request_context.get("gateway_session_id"),
            interaction_type=interaction_type,
            assistant_id=request_context.get("assistant_id"),
            thread_id=request_context.get("thread_id")
        )