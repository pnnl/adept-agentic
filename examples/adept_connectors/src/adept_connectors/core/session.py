"""Session manager for ADEPT Connectors.

Maps conversation thread_ids to ADEPT's 4-tier session model and
handles fork updates from Response API and AG-UI META_EVENT.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path.home() / ".adept"
SESSIONS_FILE = SESSIONS_DIR / "sessions.json"


class SessionInfo:
    """Tracks ADEPT's multi-tier session IDs for one conversation."""

    __slots__ = (
        "thread_id",
        "session_id",
        "mcp_session_id",
        "multi_agent_session_id",
        "gateway_session_id",
        "message_count",
        "created_at",
        "updated_at",
    )

    def __init__(
        self,
        thread_id: str,
        session_id: Optional[str] = None,
        mcp_session_id: Optional[str] = None,
        multi_agent_session_id: Optional[str] = None,
        gateway_session_id: Optional[str] = None,
    ) -> None:
        self.thread_id = thread_id
        self.session_id = session_id or thread_id
        self.mcp_session_id = mcp_session_id or thread_id
        self.multi_agent_session_id = multi_agent_session_id
        self.gateway_session_id = gateway_session_id
        self.message_count = 0
        now = datetime.now(timezone.utc).isoformat()
        self.created_at: str = now
        self.updated_at: str = now

    def touch(self) -> None:
        """Update the updated_at timestamp to now."""
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "thread_id": self.thread_id,
            "session_id": self.session_id,
            "mcp_session_id": self.mcp_session_id,
            "multi_agent_session_id": self.multi_agent_session_id,
            "gateway_session_id": self.gateway_session_id,
            "message_count": self.message_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionInfo":
        info = cls(
            thread_id=data["thread_id"],
            session_id=data.get("session_id"),
            mcp_session_id=data.get("mcp_session_id"),
            multi_agent_session_id=data.get("multi_agent_session_id"),
            gateway_session_id=data.get("gateway_session_id"),
        )
        info.message_count = data.get("message_count", 0)
        # Preserve timestamps from persisted data; fall back to now for
        # sessions saved before timestamps were added.
        now = datetime.now(timezone.utc).isoformat()
        info.created_at = data.get("created_at", now)
        info.updated_at = data.get("updated_at", now)
        return info


class SessionManager:
    """Manages ADEPT session mappings with optional disk persistence."""

    def __init__(self, persist: bool = True) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._persist = persist
        if persist:
            self._load()

    def get_or_create(self, thread_id: Optional[str] = None) -> SessionInfo:
        """Get existing session or create a new one."""
        if thread_id and thread_id in self._sessions:
            return self._sessions[thread_id]

        if not thread_id:
            thread_id = str(uuid.uuid4())

        info = SessionInfo(thread_id=thread_id)
        self._sessions[thread_id] = info
        self._save()
        return info

    def get(self, thread_id: str) -> Optional[SessionInfo]:
        return self._sessions.get(thread_id)

    def handle_fork(self, old_thread_id: str, new_thread_id: str) -> SessionInfo:
        """Handle a session fork — update mapping to point to new thread."""
        old = self._sessions.get(old_thread_id)
        if old:
            new_info = SessionInfo(
                thread_id=new_thread_id,
                session_id=new_thread_id,
                mcp_session_id=old.mcp_session_id,
                multi_agent_session_id=old.multi_agent_session_id,
                gateway_session_id=old.gateway_session_id,
            )
            new_info.message_count = old.message_count
        else:
            new_info = SessionInfo(thread_id=new_thread_id)

        self._sessions[new_thread_id] = new_info
        self._save()
        logger.debug("Session fork: %s -> %s", old_thread_id, new_thread_id)
        return new_info

    def list_sessions(self) -> list[dict]:
        return [info.to_dict() for info in self._sessions.values()]

    def _load(self) -> None:
        if not SESSIONS_FILE.exists():
            return
        try:
            data = json.loads(SESSIONS_FILE.read_text())
            for entry in data:
                info = SessionInfo.from_dict(entry)
                self._sessions[info.thread_id] = info
            logger.debug("Loaded %d sessions from disk", len(self._sessions))
        except Exception as e:
            logger.warning("Failed to load sessions: %s", e)

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            data = [info.to_dict() for info in self._sessions.values()]
            SESSIONS_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning("Failed to save sessions: %s", e)
