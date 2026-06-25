"""
Internal Session Management API

Provides HTTP endpoints for MCP servers to manage session state
without cross-service imports or direct database access.
"""

import json
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

from ....logger_config import get_logger
from ...hybrid_orchestration import hybrid_service
from ...session_hierarchy import SessionHierarchy

logger = get_logger(__name__)

router = APIRouter()

class SessionContextRequest(BaseModel):
    session_id: str
    context: Dict[str, Any] = {}

def verify_internal_api_key(authorization: str = Header(...)):
    """
    Verify internal service API key.
    
    This is a simple authentication mechanism for internal service calls.
    In production, this should be replaced with proper service-to-service auth.
    """
    expected_key = "Bearer internal-service-key"
    if authorization != expected_key:
        raise HTTPException(status_code=401, detail="Invalid internal API key")

@router.get("/sessions/{session_id}/context")
async def get_session_context(
    session_id: str,
    _: str = Depends(verify_internal_api_key)
) -> Dict[str, Any]:
    """
    Get session context data.
    
    This endpoint provides MCP servers with read access to session state
    without requiring direct imports or database connections.
    """
    try:
        # Use the hybrid orchestration service to get session context
        # This leverages the existing session management infrastructure
        session_data = await hybrid_service.get_session_data(session_id)
        
        if not session_data:
            logger.info(f"Session {session_id} not found")
            return {}
        
        # Extract context from session data
        context = session_data.get("context", {})
        logger.debug(f"Retrieved context for session {session_id}: {len(context)} keys")
        
        return context
        
    except Exception as e:
        logger.error(f"Error retrieving session context for {session_id}: {e}")
        return {}

@router.put("/sessions/{session_id}/context")
async def update_session_context(
    session_id: str,
    context_data: Dict[str, Any],
    _: str = Depends(verify_internal_api_key)
) -> Dict[str, Any]:
    """
    Update session context data.
    
    This endpoint allows MCP servers to update session state
    without requiring direct database access.
    """
    try:
        # Store the updated context using hybrid service
        await hybrid_service.update_session_data(session_id, {"context": context_data})
        
        logger.debug(f"Updated context for session {session_id}")
        return {"status": "success", "session_id": session_id}
        
    except Exception as e:
        logger.error(f"Error updating session context for {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update session context.")

@router.post("/sessions")
async def create_session(
    request: SessionContextRequest,
    _: str = Depends(verify_internal_api_key)
) -> Dict[str, Any]:
    """
    Create a new session if it doesn't exist.
    
    This endpoint allows MCP servers to ensure sessions exist
    before attempting to store context.
    """
    try:
        session_id = request.session_id
        initial_context = request.context
        
        # Check if session already exists
        existing_data = await hybrid_service.get_session_data(session_id)
        if existing_data:
            logger.debug(f"Session {session_id} already exists")
            return {"status": "exists", "session_id": session_id}
        
        # Create new session with initial context
        await hybrid_service.update_session_data(session_id, {"context": initial_context})
        
        logger.info(f"Created new session {session_id}")
        return {"status": "created", "session_id": session_id}
        
    except Exception as e:
        logger.error(f"Error creating session {request.session_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to create session.")

@router.get("/sessions/{session_id}")
async def get_session_info(
    session_id: str,
    _: str = Depends(verify_internal_api_key)
) -> Dict[str, Any]:
    """
    Get basic session information.

    Returns whether the session has context loaded. For full context data,
    use the /sessions/{session_id}/context endpoint.
    """
    try:
        session_data = await hybrid_service.get_session_data(session_id)
        has_context = bool(session_data and session_data.get("context"))
    except Exception as e:
        logger.error(f"Error retrieving session {session_id}: {type(e).__name__}")
        has_context = False

    return {"session_id": session_id, "has_context": has_context}

# Health check for internal services
@router.get("/health")
async def internal_health_check() -> Dict[str, str]:
    """Simple health check for internal session API."""
    return {"status": "ok", "service": "internal-session-api"}