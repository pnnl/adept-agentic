"""Session routes — POST /v1/sessions, GET /v1/sessions.

Session lifecycle management for ChatGPT conversations.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()


class CreateSessionRequest(BaseModel):
    """Request body for POST /v1/sessions."""

    session_id: Optional[str] = Field(
        default=None, description="Specific session ID (auto-generated if omitted)"
    )


class SessionResponse(BaseModel):
    """Response body for session operations."""

    thread_id: str
    session_id: str
    mcp_session_id: str
    multi_agent_session_id: Optional[str] = None
    gateway_session_id: Optional[str] = None
    message_count: int = 0
    created_at: str = ""
    updated_at: str = ""


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: Request, body: CreateSessionRequest
) -> SessionResponse:
    """Create a new ADEPT session or retrieve an existing one.

    Always call this first before sending chat messages.
    Pass the returned session_id to POST /v1/chat.
    """
    facade = request.app.state.facade
    session = facade.session_mgr.get_or_create(body.session_id)
    return SessionResponse(**session.to_dict())


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(request: Request) -> list[SessionResponse]:
    """List all active ADEPT sessions."""
    facade = request.app.state.facade
    sessions = facade.session_mgr.list_sessions()
    return [SessionResponse(**s) for s in sessions]
