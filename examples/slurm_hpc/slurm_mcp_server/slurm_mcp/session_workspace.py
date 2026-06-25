"""Session-scoped workspace management for Slurm job directories.

Provides per-user, per-session subdirectories within the shared /data/
volume to prevent cross-session data leakage while allowing the same user
to traverse all their sessions.

Directory structure:
    /data/
        {username}/                  ← user-owned parent (traversable)
            {session_id}/            ← session-specific workspace
                scripts/             ← generated/uploaded batch scripts
                output/              ← job stdout/stderr redirected here
                artifacts/           ← any intermediate files from tools
            {session_id_2}/          ← another session for same user
        {username_2}/                ← a different user's parent
            ...

The user-level parent ensures the same user can list and access outputs
from prior sessions. The session-level subdirectory provides isolation
so concurrent sessions do not collide.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

SLURM_WORKSPACE = os.getenv("SLURM_WORKSPACE", "/data")


@dataclass
class SessionWorkspace:
    """Resolved paths for a session-scoped workspace."""

    base_dir: Path
    user_dir: Path
    session_dir: Path
    scripts_dir: Path
    output_dir: Path
    artifacts_dir: Path

    @property
    def session_id(self) -> str:
        return self.session_dir.name

    @property
    def username(self) -> str:
        return self.user_dir.name


class WorkspaceManager:
    """Manages session-scoped directories within the shared Slurm workspace.

    Thread-safe: directory creation uses exist_ok=True. Multiple concurrent
    sessions for the same user can safely call ensure_session_workspace().
    """

    def __init__(self, workspace_root: Optional[str] = None):
        self._root = Path(workspace_root or SLURM_WORKSPACE)

    @property
    def root(self) -> Path:
        return self._root

    def ensure_session_workspace(
        self, username: str, session_id: str
    ) -> SessionWorkspace:
        """Create (or verify) the full session workspace directory tree.

        Args:
            username: Slurm/ADEPT username (parent directory name).
            session_id: MCP session ID (unique per agent conversation).

        Returns:
            SessionWorkspace with all paths resolved and directories created.
        """
        user_dir = self._root / username
        session_dir = user_dir / session_id
        scripts_dir = session_dir / "scripts"
        output_dir = session_dir / "output"
        artifacts_dir = session_dir / "artifacts"

        for d in (user_dir, session_dir, scripts_dir, output_dir, artifacts_dir):
            d.mkdir(parents=True, exist_ok=True)

        workspace = SessionWorkspace(
            base_dir=self._root,
            user_dir=user_dir,
            session_dir=session_dir,
            scripts_dir=scripts_dir,
            output_dir=output_dir,
            artifacts_dir=artifacts_dir,
        )

        logger.debug(
            "Session workspace ready: %s/%s", username, session_id
        )
        return workspace

    def list_user_sessions(self, username: str) -> List[str]:
        """List all session directories for a given user.

        Enables traversal across sessions by the same user.

        Args:
            username: The user whose sessions to list.

        Returns:
            Sorted list of session_id strings (newest first by mtime).
        """
        user_dir = self._root / username
        if not user_dir.is_dir():
            return []

        sessions = []
        for entry in user_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                sessions.append(entry.name)

        sessions.sort(
            key=lambda s: (user_dir / s).stat().st_mtime, reverse=True
        )
        return sessions

    def get_session_workspace(
        self, username: str, session_id: str
    ) -> Optional[SessionWorkspace]:
        """Get an existing session workspace without creating it.

        Args:
            username: Slurm/ADEPT username.
            session_id: MCP session ID.

        Returns:
            SessionWorkspace if the directory exists, None otherwise.
        """
        session_dir = self._root / username / session_id
        if not session_dir.is_dir():
            return None

        return SessionWorkspace(
            base_dir=self._root,
            user_dir=self._root / username,
            session_dir=session_dir,
            scripts_dir=session_dir / "scripts",
            output_dir=session_dir / "output",
            artifacts_dir=session_dir / "artifacts",
        )

    def list_session_files(
        self, username: str, session_id: str, subdir: str = "output"
    ) -> List[str]:
        """List files in a specific subdirectory of a session workspace.

        Args:
            username: Slurm/ADEPT username.
            session_id: MCP session ID.
            subdir: Subdirectory to list ('scripts', 'output', 'artifacts').

        Returns:
            List of filenames in that subdirectory.
        """
        session_dir = self._root / username / session_id / subdir
        if not session_dir.is_dir():
            return []
        return sorted(f.name for f in session_dir.iterdir() if f.is_file())
