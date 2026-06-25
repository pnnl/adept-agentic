"""Chat route — POST /v1/chat.

Main conversation endpoint. ChatGPT sends user messages here and
receives text responses with optional inline image proxy URLs.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    """Request body for POST /v1/chat."""

    message: str = Field(..., description="User message to send to ADEPT")
    session_id: Optional[str] = Field(
        default=None, description="Session ID from POST /v1/sessions"
    )
    model: Optional[str] = Field(
        default=None, description="Model override (default: scientific-agent-v1)"
    )


class ChatResponse(BaseModel):
    """Response body for POST /v1/chat."""

    content: str = Field(..., description="Assistant response text (may include markdown image links)")
    session_id: Optional[str] = Field(default=None, description="Active session ID")
    model: str = Field(default="", description="Model used")
    finish_reason: Optional[str] = Field(default=None, description="Why generation stopped")
    image_count: int = Field(default=0, description="Number of images auto-fetched and embedded")
    session_forked: bool = Field(default=False, description="Whether the session was forked (context overflow)")


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Send a message to ADEPT and return the rendered response.

    Images in the response are automatically fetched from ADEPT's
    internal servers and served via proxy URLs that ChatGPT can render
    as inline markdown images.
    """
    facade = request.app.state.facade

    result = await facade.chat(
        message=body.message,
        session_id=body.session_id,
        model=body.model,
        auto_fetch_images=True,
    )

    # Render with ChatGPTImageRenderer (replaces image URLs with proxy URLs)
    rendered_text = facade.render(result)

    return ChatResponse(
        content=rendered_text,
        session_id=result.session.thread_id if result.session else None,
        model=result.model,
        finish_reason=result.finish_reason,
        image_count=len(result.images),
        session_forked=result.session_fork is not None,
    )
