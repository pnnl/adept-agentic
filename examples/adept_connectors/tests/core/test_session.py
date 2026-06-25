"""Tests for SessionManager."""

import json
import time
from pathlib import Path

import pytest

from adept_connectors.core.session import SessionInfo, SessionManager


class TestSessionInfo:

    def test_roundtrip_dict(self):
        info = SessionInfo(
            thread_id="t-1",
            session_id="s-1",
            mcp_session_id="mcp-1",
            multi_agent_session_id="ma-1",
            gateway_session_id="gw-1",
        )
        info.message_count = 5
        d = info.to_dict()
        restored = SessionInfo.from_dict(d)
        assert restored.thread_id == "t-1"
        assert restored.mcp_session_id == "mcp-1"
        assert restored.message_count == 5

    def test_defaults_use_thread_id(self):
        info = SessionInfo(thread_id="abc-123")
        assert info.session_id == "abc-123"
        assert info.mcp_session_id == "abc-123"
        assert info.multi_agent_session_id is None

    def test_timestamps_set_on_creation(self):
        info = SessionInfo(thread_id="t-ts")
        assert info.created_at is not None
        assert info.updated_at is not None
        assert info.created_at == info.updated_at

    def test_touch_updates_updated_at(self):
        info = SessionInfo(thread_id="t-touch")
        original = info.updated_at
        time.sleep(0.01)
        info.touch()
        assert info.updated_at > original
        assert info.created_at != info.updated_at

    def test_timestamps_roundtrip(self):
        info = SessionInfo(thread_id="t-rt")
        info.touch()
        d = info.to_dict()
        assert "created_at" in d
        assert "updated_at" in d
        restored = SessionInfo.from_dict(d)
        assert restored.created_at == info.created_at
        assert restored.updated_at == info.updated_at

    def test_from_dict_missing_timestamps(self):
        """Sessions saved before timestamps were added get default values."""
        d = {"thread_id": "old-session", "message_count": 3}
        info = SessionInfo.from_dict(d)
        assert info.created_at is not None
        assert info.updated_at is not None


class TestSessionManager:

    def test_get_or_create_new(self):
        mgr = SessionManager(persist=False)
        info = mgr.get_or_create("thread-1")
        assert info.thread_id == "thread-1"
        assert info.session_id == "thread-1"

    def test_get_or_create_existing(self):
        mgr = SessionManager(persist=False)
        info1 = mgr.get_or_create("thread-1")
        info1.message_count = 3
        info2 = mgr.get_or_create("thread-1")
        assert info2.message_count == 3
        assert info1 is info2

    def test_get_or_create_auto_id(self):
        mgr = SessionManager(persist=False)
        info = mgr.get_or_create()
        assert info.thread_id is not None
        assert len(info.thread_id) > 0

    def test_get_nonexistent(self):
        mgr = SessionManager(persist=False)
        assert mgr.get("missing") is None

    def test_handle_fork(self):
        mgr = SessionManager(persist=False)
        old = mgr.get_or_create("old-thread")
        old.message_count = 10
        old.mcp_session_id = "shared-mcp"

        new = mgr.handle_fork("old-thread", "new-thread")
        assert new.thread_id == "new-thread"
        assert new.mcp_session_id == "shared-mcp"
        assert new.message_count == 10

    def test_handle_fork_unknown_old(self):
        mgr = SessionManager(persist=False)
        new = mgr.handle_fork("unknown", "new-thread")
        assert new.thread_id == "new-thread"

    def test_list_sessions(self):
        mgr = SessionManager(persist=False)
        mgr.get_or_create("t-1")
        mgr.get_or_create("t-2")
        sessions = mgr.list_sessions()
        assert len(sessions) == 2
        thread_ids = {s["thread_id"] for s in sessions}
        assert thread_ids == {"t-1", "t-2"}

    def test_persistence_roundtrip(self, tmp_path, monkeypatch):
        sessions_file = tmp_path / "sessions.json"
        monkeypatch.setattr(
            "adept_connectors.core.session.SESSIONS_FILE", sessions_file
        )
        monkeypatch.setattr(
            "adept_connectors.core.session.SESSIONS_DIR", tmp_path
        )

        # Write
        mgr1 = SessionManager(persist=True)
        info = mgr1.get_or_create("persistent-thread")
        info.message_count = 7

        mgr1._save()
        assert sessions_file.exists()

        # Read back
        mgr2 = SessionManager(persist=True)
        restored = mgr2.get("persistent-thread")
        assert restored is not None
        assert restored.message_count == 7
        assert restored.created_at == info.created_at
        assert restored.updated_at == info.updated_at
