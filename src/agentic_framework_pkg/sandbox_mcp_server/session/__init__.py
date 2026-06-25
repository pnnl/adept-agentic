"""
Session management for sandbox code execution.

Provides session-based isolation, lifecycle management, and cleanup utilities
for secure multi-tenant code execution environments.
"""

from .session_manager import (
    SessionIsolationManager,
    SessionInfo,
    get_session_manager,
    cleanup_expired_sessions_periodically,
    reap_orphaned_processes_periodically,
)

__all__ = [
    'SessionIsolationManager',
    'SessionInfo',
    'get_session_manager',
    'cleanup_expired_sessions_periodically',
    'reap_orphaned_processes_periodically',
]