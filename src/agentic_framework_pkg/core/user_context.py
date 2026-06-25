"""
Core User Context Management

This module provides utilities for managing user context across MCP servers.
It handles user authentication data, ownership tracking, and context propagation
in a way that's isolated from specific service implementations.
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from ..logger_config import get_logger

logger = get_logger(__name__)

@dataclass
class UserContext:
    """
    Represents user context information for MCP tool execution.
    
    This provides a clean abstraction for user identity that tools
    can use without needing to understand authentication internals.
    """
    user_id: str
    username: str
    groups: list[str]
    session_id: Optional[str] = None
    
    def has_group(self, group_name: str) -> bool:
        """Check if user belongs to a specific group."""
        return group_name in self.groups
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "groups": self.groups,
            "session_id": self.session_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserContext":
        """Create from dictionary."""
        return cls(
            user_id=data["user_id"],
            username=data["username"],
            groups=data.get("groups", []),
            session_id=data.get("session_id")
        )

def extract_user_context_from_headers(headers: Dict[str, str]) -> Optional[UserContext]:
    """
    Extract user context from forwarded headers.
    
    This is used by MCP servers to reconstruct user identity
    from headers forwarded by the orchestration service.
    
    Args:
        headers: HTTP headers dictionary
        
    Returns:
        UserContext if found, None otherwise
    """
    try:
        user_id = headers.get("X-User-ID")
        username = headers.get("X-Username")
        groups_header = headers.get("X-User-Groups", "")
        session_id = headers.get("X-Session-ID")
        
        if not user_id or not username:
            return None
        
        groups = [g.strip() for g in groups_header.split(",") if g.strip()] if groups_header else []
        
        return UserContext(
            user_id=user_id,
            username=username,
            groups=groups,
            session_id=session_id
        )
    except Exception as e:
        logger.error(f"Error extracting user context from headers: {e}")
        return None

def create_forwarding_headers(user_context: UserContext) -> Dict[str, str]:
    """
    Create headers for forwarding user context to other services.
    
    Args:
        user_context: User context to forward
        
    Returns:
        Dictionary of headers to include in service calls
    """
    headers = {
        "X-User-ID": user_context.user_id,
        "X-Username": user_context.username,
        "X-User-Groups": ",".join(user_context.groups)
    }
    
    if user_context.session_id:
        headers["X-Session-ID"] = user_context.session_id
    
    return headers