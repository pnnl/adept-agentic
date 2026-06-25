"""
Core Session Management API

This module provides a clean, standardized interface for session management
across all MCP servers in the Agentic Framework. It abstracts away the
underlying implementation details and provides HTTP-based communication
with the orchestration service for session operations.

This is the primary interface that MCP tools should use for session
management instead of directly importing from specific MCP servers.
"""

import os
import json
import aiohttp
from typing import Dict, Any, Optional
from ..logger_config import get_logger

logger = get_logger(__name__)

class SessionAPIClient:
    """
    HTTP-based client for session management operations.
    
    Communicates with the orchestration service's internal session endpoints
    to provide clean session management without cross-service imports.
    """
    
    def __init__(self, orchestration_base_url: Optional[str] = None):
        """
        Initialize the session API client.
        
        Args:
            orchestration_base_url: Base URL of orchestration service.
                                  Defaults to environment variable or localhost.
        """
        self.base_url = orchestration_base_url or os.getenv(
            "ORCHESTRATION_SERVICE_URL", 
            "http://orchestration_service:8084"
        )
        self.internal_api_key = os.getenv("INTERNAL_API_KEY", "internal-service-key")
    
    async def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """
        Retrieve session context data.
        
        Args:
            session_id: The session identifier
            
        Returns:
            Dictionary containing session context data
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.internal_api_key}",
                    "Content-Type": "application/json"
                }
                
                url = f"{self.base_url}/internal/sessions/{session_id}/context"
                
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 404:
                        logger.info(f"Session {session_id} not found, returning empty context")
                        return {}
                    else:
                        logger.error(f"Failed to get session context: {response.status}")
                        return {}
                        
        except Exception as e:
            logger.error(f"Error getting session context for {session_id}: {e}")
            return {}
    
    async def update_session_context(self, session_id: str, context_data: Dict[str, Any]) -> bool:
        """
        Update session context data.
        
        Args:
            session_id: The session identifier
            context_data: Updated context data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.internal_api_key}",
                    "Content-Type": "application/json"
                }
                
                url = f"{self.base_url}/internal/sessions/{session_id}/context"
                
                async with session.put(url, headers=headers, json=context_data) as response:
                    if response.status in [200, 201]:
                        return True
                    else:
                        logger.error(f"Failed to update session context: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error updating session context for {session_id}: {e}")
            return False
    
    async def create_session_if_not_exists(self, session_id: str, initial_context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Create a session if it doesn't exist.
        
        Args:
            session_id: The session identifier
            initial_context: Optional initial context data
            
        Returns:
            True if session exists or was created, False on error
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.internal_api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "session_id": session_id,
                    "context": initial_context or {}
                }
                
                url = f"{self.base_url}/internal/sessions"
                
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status in [200, 201, 409]:  # 409 = already exists
                        return True
                    else:
                        logger.error(f"Failed to create session: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error creating session {session_id}: {e}")
            return False

# Global session API client instance
_session_client: Optional[SessionAPIClient] = None

def get_session_client() -> SessionAPIClient:
    """
    Get the global session API client instance.
    
    Returns:
        SessionAPIClient instance
    """
    global _session_client
    if _session_client is None:
        _session_client = SessionAPIClient()
    return _session_client

# Convenience functions for backward compatibility
async def get_session_context(session_id: str) -> Dict[str, Any]:
    """
    Convenience function to get session context.
    
    Args:
        session_id: The session identifier
        
    Returns:
        Dictionary containing session context data
    """
    client = get_session_client()
    return await client.get_session_context(session_id)

async def update_session_context(session_id: str, context_data: Dict[str, Any]) -> bool:
    """
    Convenience function to update session context.
    
    Args:
        session_id: The session identifier
        context_data: Updated context data
        
    Returns:
        True if successful, False otherwise
    """
    client = get_session_client()
    return await client.update_session_context(session_id, context_data)

async def create_session_if_not_exists(session_id: str, initial_context: Optional[Dict[str, Any]] = None) -> bool:
    """
    Convenience function to create session if it doesn't exist.
    
    Args:
        session_id: The session identifier
        initial_context: Optional initial context data
        
    Returns:
        True if session exists or was created, False on error
    """
    client = get_session_client()
    return await client.create_session_if_not_exists(session_id, initial_context)