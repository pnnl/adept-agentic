"""Session tools — adept_create_session and adept_list_sessions."""

from __future__ import annotations

import json
from typing import Optional

from ..server import get_context, mcp


@mcp.tool()
async def adept_create_session(session_id: Optional[str] = None) -> str:
    """Create a new ADEPT session or retrieve an existing one.

    IMPORTANT: Call this ONCE at the start of every conversation before using
    adept_chat, adept_agui_run, adept_upload_file, or any other ADEPT tool.
    Save the returned session_id and pass it to all subsequent tool calls.
    This ensures ADEPT maintains conversation history, file context, and
    multi-agent state across the entire conversation.

    If session_id is provided and exists, returns the existing session
    (useful for resuming a prior conversation).

    Typical workflow:
    1. Call adept_create_session() to get a session_id
    2. Pass that session_id to every adept_chat() or adept_agui_run() call
    3. ADEPT automatically manages memory and context forking server-side

    Args:
        session_id: Optional specific session ID. Auto-generated if omitted.

    Returns:
        JSON with session_id, mcp_session_id, and message_count.
    """
    ctx = get_context()
    session = ctx.session_mgr.get_or_create(session_id)
    return json.dumps(session.to_dict(), indent=2)


@mcp.tool()
async def adept_list_sessions() -> str:
    """List all active ADEPT conversation sessions.

    Shows sessions created via adept_create_session, including their
    thread IDs, message counts, and creation timestamps. Use this to
    find a previous session_id to resume a conversation, or to check
    how many messages have been exchanged in the current session.

    Sessions persist across connector restarts (saved to
    ~/.adept/sessions.json) when ADEPT_SESSION_PERSISTENCE is enabled
    (default: true).

    Returns:
        JSON array of session objects with thread_id, message_count, etc.
    """
    ctx = get_context()
    sessions = ctx.session_mgr.list_sessions()
    return json.dumps(sessions, indent=2)
