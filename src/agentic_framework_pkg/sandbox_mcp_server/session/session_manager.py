"""
Session-based isolation manager for sandbox code execution.

Provides secure session-specific working directories that:
- Isolate each execution session from others
- Prevent filesystem traversal between sessions  
- Enable lifecycle management of temporary resources
- Support cleanup of abandoned sessions
- Maintain compatibility with agent_gateway file serving

Architecture:
- Base shared volume: /app/data/uploaded_files/
- Session directories: /app/data/uploaded_files/sessions/{session_id}/
- Sandbox working dir: /app/data/uploaded_files/sessions/{session_id}/workspace/
- Output files: /app/data/uploaded_files/sessions/{session_id}/outputs/

TODO: tmpfs was supposed to be used via hybrid approach

The llm-sandbox only sees its session workspace, preventing traversal.
The agent_gateway can serve files from any session for authorized users.
"""

import os
import signal
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio
import json

from ...logger_config import get_logger

logger = get_logger(__name__)

@dataclass
class SessionInfo:
    """Information about a sandbox execution session."""
    session_id: str
    created_at: datetime
    last_accessed: datetime
    user_id: Optional[str] = None
    multi_agent_session_id: Optional[str] = None
    gateway_session_id: Optional[str] = None
    workspace_path: str = None
    outputs_path: str = None
    is_active: bool = True
    cleanup_after: Optional[datetime] = None
    active_pids: Set[int] = field(default_factory=set)

class SessionIsolationManager:
    """Manages isolated execution sessions for sandbox security."""
    
    def __init__(self, 
                 base_shared_path: str = "/app/data/uploaded_files",
                 tmpfs_path: str = "/tmp/sandbox_sessions",
                 session_timeout_hours: int = 24,
                 max_sessions_per_user: int = 10,
                 use_hybrid_approach: bool = True):
        """
        Initialize session isolation manager.
        
        Args:
            base_shared_path: Base path for persistent storage (shared volume)
            tmpfs_path: Base path for temporary execution (tmpfs mount)
            session_timeout_hours: Hours before session cleanup
            max_sessions_per_user: Maximum concurrent sessions per user
            use_hybrid_approach: Use tmpfs for execution, shared volume for outputs
        """
        self.base_shared_path = Path(base_shared_path)
        self.tmpfs_path = Path(tmpfs_path)
        self.sessions_path = self.base_shared_path / "sessions"
        self.session_timeout = timedelta(hours=session_timeout_hours)
        self.max_sessions_per_user = max_sessions_per_user
        self.use_hybrid_approach = use_hybrid_approach and self.tmpfs_path.exists()
        
        # In-memory session registry
        # Thread safety note: With Uvicorn workers=1 (default), the asyncio event
        # loop is single-threaded and dict mutations between await points are safe.
        # If workers > 1, each worker gets its own SessionIsolationManager instance
        # (module-level singleton per process), so no cross-process race conditions.
        # The _lock is provided for callers that need to do read-modify-write across
        # await points (e.g., check-then-create in execute_code_subprocess).
        self.active_sessions: Dict[str, SessionInfo] = {}
        self.user_sessions: Dict[str, Set[str]] = {}
        self._lock = asyncio.Lock()
        
        # Ensure directory structure exists
        self._ensure_directory_structure()
        
        # Load existing sessions from filesystem
        self._load_existing_sessions()
    
    def _ensure_directory_structure(self):
        """Create necessary directory structure."""
        self.sessions_path.mkdir(parents=True, exist_ok=True)
        
        # Create .gitignore to exclude session data from version control
        gitignore_path = self.sessions_path / ".gitignore"
        if not gitignore_path.exists():
            with open(gitignore_path, 'w') as f:
                f.write("# Exclude all session data\\n*\\n!.gitignore\\n")
    
    def _load_existing_sessions(self):
        """Load existing sessions from filesystem on startup."""
        try:
            for session_dir in self.sessions_path.iterdir():
                if session_dir.is_dir() and not session_dir.name.startswith('.'):
                    session_id = session_dir.name
                    metadata_file = session_dir / "session_metadata.json"
                    
                    if metadata_file.exists():
                        try:
                            with open(metadata_file) as f:
                                data = json.load(f)
                            
                            session_info = SessionInfo(
                                session_id=session_id,
                                created_at=datetime.fromisoformat(data['created_at']),
                                last_accessed=datetime.fromisoformat(data['last_accessed']),
                                user_id=data.get('user_id'),
                                multi_agent_session_id=data.get('multi_agent_session_id'),
                                gateway_session_id=data.get('gateway_session_id'),
                                workspace_path=str(session_dir / "workspace"),
                                outputs_path=str(session_dir / "outputs"),
                                is_active=data.get('is_active', True)
                            )
                            
                            self.active_sessions[session_id] = session_info
                            
                            if session_info.user_id:
                                if session_info.user_id not in self.user_sessions:
                                    self.user_sessions[session_info.user_id] = set()
                                self.user_sessions[session_info.user_id].add(session_id)
                                
                        except Exception as e:
                            logger.warning(f"Failed to load session {session_id}: {e}")
            
            logger.info(f"Loaded {len(self.active_sessions)} existing sessions")
            
        except Exception as e:
            logger.error(f"Failed to load existing sessions: {e}")
    
    def create_session(self, 
                      user_id: Optional[str] = None,
                      multi_agent_session_id: Optional[str] = None,
                      gateway_session_id: Optional[str] = None,
                      session_id: Optional[str] = None) -> SessionInfo:
        """
        Create a new isolated execution session.
        
        Args:
            user_id: User identifier for the session
            multi_agent_session_id: Multi-agent orchestration session ID  
            gateway_session_id: Gateway session ID
            session_id: Optional custom session ID
            
        Returns:
            SessionInfo for the created session
        """
        # Generate session ID if not provided
        if not session_id:
            session_id = f"sandbox_{uuid.uuid4().hex[:12]}"
        
        # Check user session limits
        if user_id and user_id in self.user_sessions:
            user_session_count = len(self.user_sessions[user_id])
            if user_session_count >= self.max_sessions_per_user:
                # Cleanup oldest session for this user
                oldest_session_id = min(
                    self.user_sessions[user_id],
                    key=lambda sid: self.active_sessions[sid].last_accessed
                )
                self.cleanup_session(oldest_session_id)
        
        # Create session directory structure in both tmpfs and shared volume
        if self.use_hybrid_approach:
            # Hybrid approach: tmpfs for execution, shared for persistence
            tmpfs_session_dir = self.tmpfs_path / "sessions" / session_id
            workspace_dir = tmpfs_session_dir / "workspace"
            outputs_dir = tmpfs_session_dir / "outputs"
            
            # Also create in shared volume for persistent storage
            shared_session_dir = self.sessions_path / session_id
            shared_outputs_dir = shared_session_dir / "outputs"
        else:
            # Fallback to shared volume only
            session_dir = self.sessions_path / session_id
            workspace_dir = session_dir / "workspace"
            outputs_dir = session_dir / "outputs"
        
        try:
            if self.use_hybrid_approach:
                # Create tmpfs directories for execution
                tmpfs_session_dir.mkdir(parents=True, exist_ok=True)
                workspace_dir.mkdir(exist_ok=True)
                outputs_dir.mkdir(exist_ok=True)
                
                # Set permissions on tmpfs
                os.chmod(tmpfs_session_dir, 0o755)
                os.chmod(workspace_dir, 0o755)
                os.chmod(outputs_dir, 0o755)
                
                # Create shared volume directories for persistence
                shared_session_dir.mkdir(parents=True, exist_ok=True)
                shared_outputs_dir.mkdir(exist_ok=True)
                os.chmod(shared_session_dir, 0o755)
                os.chmod(shared_outputs_dir, 0o755)
                
                logger.info(f"Hybrid session created: tmpfs={tmpfs_session_dir}, shared={shared_session_dir}")
            else:
                # Single location setup
                session_dir.mkdir(parents=True, exist_ok=True)
                workspace_dir.mkdir(exist_ok=True)
                outputs_dir.mkdir(exist_ok=True)
                
                # Set proper permissions (readable by agent_gateway)
                os.chmod(session_dir, 0o755)
                os.chmod(workspace_dir, 0o755)
                os.chmod(outputs_dir, 0o755)
            
        except Exception as e:
            logger.error(f"Failed to create session directory {session_id}: {e}")
            raise
        
        # Create session info
        now = datetime.utcnow()
        session_info = SessionInfo(
            session_id=session_id,
            created_at=now,
            last_accessed=now,
            user_id=user_id,
            multi_agent_session_id=multi_agent_session_id,
            gateway_session_id=gateway_session_id,
            workspace_path=str(workspace_dir),
            outputs_path=str(outputs_dir),
            cleanup_after=now + self.session_timeout
        )
        
        # Save session metadata
        self._save_session_metadata(session_info)
        
        # Register session
        self.active_sessions[session_id] = session_info
        
        if user_id:
            if user_id not in self.user_sessions:
                self.user_sessions[user_id] = set()
            self.user_sessions[user_id].add(session_id)
        
        logger.info(f"Created session {session_id} for user {user_id}")
        return session_info
    
    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """
        Get session information by ID.
        
        Args:
            session_id: Session identifier
            
        Returns:
            SessionInfo if found, None otherwise
        """
        session = self.active_sessions.get(session_id)
        if session:
            # Update last accessed time
            session.last_accessed = datetime.utcnow()
            self._save_session_metadata(session)
        return session
    
    def get_session_workspace(self, session_id: str) -> Optional[str]:
        """
        Get the isolated workspace path for a session.
        This is the path that should be used as the working directory
        for sandbox code execution.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Workspace path if session exists, None otherwise
        """
        session = self.get_session(session_id)
        return session.workspace_path if session else None
    
    def get_session_outputs(self, session_id: str) -> Optional[str]:
        """
        Get the outputs directory path for a session.
        This is where generated files should be stored.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Outputs path if session exists, None otherwise
        """
        session = self.get_session(session_id)
        return session.outputs_path if session else None
    
    def list_user_sessions(self, user_id: str) -> List[SessionInfo]:
        """
        List all active sessions for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            List of SessionInfo objects for the user
        """
        user_session_ids = self.user_sessions.get(user_id, set())
        return [self.active_sessions[sid] for sid in user_session_ids 
                if sid in self.active_sessions]
    
    def cleanup_session(self, session_id: str) -> bool:
        """
        Clean up a session and all its resources.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if cleanup was successful, False otherwise
        """
        session = self.active_sessions.get(session_id)
        if not session:
            return False

        try:
            # Kill any tracked processes first (before filesystem cleanup)
            for pid in list(session.active_pids):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                    logger.info(f"[SESSION_CLEANUP] Killed process group {pid} for session {session_id}")
                except (ProcessLookupError, OSError):
                    pass  # Already dead
            session.active_pids.clear()

            # Remove session directory and all contents
            session_dir = self.sessions_path / session_id
            if session_dir.exists():
                shutil.rmtree(session_dir)
            
            # Remove from registries
            if session.user_id and session.user_id in self.user_sessions:
                self.user_sessions[session.user_id].discard(session_id)
                if not self.user_sessions[session.user_id]:
                    del self.user_sessions[session.user_id]
            
            del self.active_sessions[session_id]
            
            logger.info(f"Cleaned up session {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cleanup session {session_id}: {e}")
            return False
    
    def cleanup_expired_sessions(self) -> int:
        """
        Clean up all expired sessions based on timeout.
        
        Returns:
            Number of sessions cleaned up
        """
        now = datetime.utcnow()
        expired_sessions = []
        
        for session_id, session in self.active_sessions.items():
            if session.cleanup_after and now > session.cleanup_after:
                expired_sessions.append(session_id)
        
        cleaned_count = 0
        for session_id in expired_sessions:
            if self.cleanup_session(session_id):
                cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} expired sessions")
        
        return cleaned_count
    
    def get_file_path_for_agent_gateway(self, session_id: str, filename: str) -> Optional[str]:
        """
        Get the full file path for agent_gateway to serve files from a session.
        This enables the agent_gateway to serve files while maintaining isolation.
        
        Args:
            session_id: Session identifier
            filename: Name of file within session outputs
            
        Returns:
            Full path relative to base shared path for agent_gateway
        """
        session = self.get_session(session_id)
        if not session:
            return None
        
        # Return path relative to base shared path that agent_gateway can access
        return f"sessions/{session_id}/outputs/{filename}"
    
    def publish_session_outputs_to_shared_volume(self, session_id: str, shared_volume_base: str = "/app/data/uploaded_files") -> bool:
        """
        Copy session outputs from tmpfs to shared volume for agent_gateway serving.
        
        This enables a hybrid approach:
        1. Session isolation in tmpfs (/tmp/sandbox_sessions) for security
        2. Output publishing to shared volume for agent_gateway file serving
        
        Args:
            session_id: Session identifier
            shared_volume_base: Base path of the shared volume mount
            
        Returns:
            True if publishing was successful, False otherwise
        """
        session = self.get_session(session_id)
        if not session:
            logger.error(f"Session {session_id} not found for output publishing")
            return False
        
        try:
            import shutil
            from pathlib import Path
            
            # Source: tmpfs session workspace (where files are generated)
            source_outputs_dir = Path(session.workspace_path)
            
            # Destination: shared volume for agent_gateway
            shared_volume_path = Path(shared_volume_base)
            dest_session_dir = shared_volume_path / "sessions" / session_id
            dest_outputs_dir = dest_session_dir / "outputs"
            
            # Create destination directory structure
            dest_outputs_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy all files from tmpfs session outputs to shared volume
            if source_outputs_dir.exists():
                for source_file in source_outputs_dir.glob("*"):
                    if source_file.is_file():
                        dest_file = dest_outputs_dir / source_file.name
                        shutil.copy2(source_file, dest_file)
                        logger.info(f"Published {source_file.name} from session {session_id} to shared volume")
                
                logger.info(f"Successfully published outputs from session {session_id} to shared volume")
                return True
            else:
                logger.info(f"No outputs found in session {session_id} to publish")
                return True
                
        except Exception as e:
            logger.error(f"Failed to publish session {session_id} outputs to shared volume: {e}")
            return False
    
    def _save_session_metadata(self, session: SessionInfo):
        """Save session metadata to filesystem."""
        try:
            session_dir = self.sessions_path / session.session_id
            metadata_file = session_dir / "session_metadata.json"
            
            metadata = {
                'session_id': session.session_id,
                'created_at': session.created_at.isoformat(),
                'last_accessed': session.last_accessed.isoformat(),
                'user_id': session.user_id,
                'multi_agent_session_id': session.multi_agent_session_id,
                'gateway_session_id': session.gateway_session_id,
                'is_active': session.is_active,
                'cleanup_after': session.cleanup_after.isoformat() if session.cleanup_after else None
            }
            
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save session metadata for {session.session_id}: {e}")

# Global session manager instance
_session_manager: Optional[SessionIsolationManager] = None

def get_session_manager() -> SessionIsolationManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        # Check if tmpfs is available for hybrid approach
        tmpfs_available = Path("/tmp/sandbox_sessions").exists()
        logger.info(f"Initializing SessionIsolationManager (tmpfs_available={tmpfs_available})")
        _session_manager = SessionIsolationManager(
            use_hybrid_approach=tmpfs_available
        )
    return _session_manager

async def cleanup_expired_sessions_periodically(interval_minutes: int = 60):
    """
    Background task to periodically clean up expired sessions.

    Args:
        interval_minutes: Cleanup interval in minutes
    """
    while True:
        try:
            manager = get_session_manager()
            manager.cleanup_expired_sessions()
        except Exception as e:
            logger.error(f"Error in session cleanup task: {e}")

        await asyncio.sleep(interval_minutes * 60)


async def reap_orphaned_processes_periodically(interval_minutes: int = 5):
    """Background task to find and kill orphaned Python subprocess scripts.

    Scans for Python processes running sandbox scripts (identifiable by
    ``script_`` prefix and ``/tmp/sandbox_sessions`` path) that have
    escaped normal cleanup.  Runs every *interval_minutes* minutes.
    """
    import subprocess as sp

    while True:
        try:
            result = sp.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if "script_" in line and "/tmp/sandbox_sessions" in line:
                    parts = line.split()
                    try:
                        pid = int(parts[1])
                    except (IndexError, ValueError):
                        continue
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                        logger.warning(
                            f"[ORPHAN_REAPER] Killed orphaned process group {pid}: {line[:120]}"
                        )
                    except (ProcessLookupError, OSError):
                        pass
        except Exception as e:
            logger.error(f"Error in orphan reaper: {e}")

        await asyncio.sleep(interval_minutes * 60)