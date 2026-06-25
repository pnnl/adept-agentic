"""Unit tests for session-scoped workspace management."""

import os
import sys
import tempfile

import pytest

SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)

from slurm_mcp.session_workspace import SessionWorkspace, WorkspaceManager


class TestWorkspaceManager:
    """Test session-scoped directory lifecycle."""

    @pytest.fixture
    def tmp_workspace(self, tmp_path):
        """Create a WorkspaceManager rooted at a temp directory."""
        return WorkspaceManager(workspace_root=str(tmp_path))

    def test_ensure_session_workspace_creates_dirs(self, tmp_workspace):
        """Verify full directory tree is created."""
        ws = tmp_workspace.ensure_session_workspace("rigo160", "session-abc123")

        assert ws.user_dir.is_dir()
        assert ws.session_dir.is_dir()
        assert ws.scripts_dir.is_dir()
        assert ws.output_dir.is_dir()
        assert ws.artifacts_dir.is_dir()

        assert ws.username == "rigo160"
        assert ws.session_id == "session-abc123"

    def test_ensure_session_workspace_idempotent(self, tmp_workspace):
        """Multiple calls with same args don't fail."""
        ws1 = tmp_workspace.ensure_session_workspace("rigo160", "sess1")
        ws2 = tmp_workspace.ensure_session_workspace("rigo160", "sess1")

        assert ws1.session_dir == ws2.session_dir

    def test_multiple_sessions_same_user(self, tmp_workspace):
        """Same user can have multiple session directories."""
        ws1 = tmp_workspace.ensure_session_workspace("rigo160", "sess-a")
        ws2 = tmp_workspace.ensure_session_workspace("rigo160", "sess-b")

        assert ws1.session_dir != ws2.session_dir
        assert ws1.user_dir == ws2.user_dir

    def test_different_users_isolated(self, tmp_workspace):
        """Different users get different parent directories."""
        ws1 = tmp_workspace.ensure_session_workspace("alice", "sess1")
        ws2 = tmp_workspace.ensure_session_workspace("bob", "sess1")

        assert ws1.user_dir != ws2.user_dir
        assert ws1.user_dir.parent == ws2.user_dir.parent

    def test_list_user_sessions_empty(self, tmp_workspace):
        """No sessions → empty list."""
        sessions = tmp_workspace.list_user_sessions("nobody")
        assert sessions == []

    def test_list_user_sessions_returns_all(self, tmp_workspace):
        """All session dirs are listed for the user."""
        tmp_workspace.ensure_session_workspace("rigo160", "sess-a")
        tmp_workspace.ensure_session_workspace("rigo160", "sess-b")
        tmp_workspace.ensure_session_workspace("rigo160", "sess-c")

        sessions = tmp_workspace.list_user_sessions("rigo160")
        assert len(sessions) == 3
        assert set(sessions) == {"sess-a", "sess-b", "sess-c"}

    def test_list_user_sessions_excludes_other_users(self, tmp_workspace):
        """User A cannot see user B's sessions."""
        tmp_workspace.ensure_session_workspace("alice", "sess1")
        tmp_workspace.ensure_session_workspace("bob", "sess2")

        alice_sessions = tmp_workspace.list_user_sessions("alice")
        assert alice_sessions == ["sess1"]

    def test_get_session_workspace_existing(self, tmp_workspace):
        """Get returns workspace for existing session."""
        tmp_workspace.ensure_session_workspace("rigo160", "sess-x")
        ws = tmp_workspace.get_session_workspace("rigo160", "sess-x")

        assert ws is not None
        assert ws.session_id == "sess-x"

    def test_get_session_workspace_nonexistent(self, tmp_workspace):
        """Get returns None for non-existent session."""
        ws = tmp_workspace.get_session_workspace("rigo160", "no-such-session")
        assert ws is None

    def test_list_session_files(self, tmp_workspace):
        """Files placed in a subdirectory are listed."""
        ws = tmp_workspace.ensure_session_workspace("rigo160", "sess-files")

        (ws.output_dir / "job_123.out").write_text("hello")
        (ws.output_dir / "job_123.err").write_text("")
        (ws.scripts_dir / "run.sh").write_text("#!/bin/bash")

        output_files = tmp_workspace.list_session_files(
            "rigo160", "sess-files", "output"
        )
        assert sorted(output_files) == ["job_123.err", "job_123.out"]

        script_files = tmp_workspace.list_session_files(
            "rigo160", "sess-files", "scripts"
        )
        assert script_files == ["run.sh"]

    def test_list_session_files_nonexistent_subdir(self, tmp_workspace):
        """Non-existent subdir returns empty list."""
        files = tmp_workspace.list_session_files("rigo160", "nope", "output")
        assert files == []

    def test_workspace_paths_are_absolute(self, tmp_workspace):
        """All returned paths should be absolute."""
        ws = tmp_workspace.ensure_session_workspace("user1", "sess1")

        assert ws.base_dir.is_absolute()
        assert ws.user_dir.is_absolute()
        assert ws.session_dir.is_absolute()
        assert ws.scripts_dir.is_absolute()
        assert ws.output_dir.is_absolute()
        assert ws.artifacts_dir.is_absolute()

    def test_hidden_dirs_excluded_from_session_list(self, tmp_workspace):
        """Directories starting with '.' are not listed as sessions."""
        ws = tmp_workspace.ensure_session_workspace("rigo160", "real-session")
        (ws.user_dir / ".hidden").mkdir()

        sessions = tmp_workspace.list_user_sessions("rigo160")
        assert ".hidden" not in sessions
        assert "real-session" in sessions
