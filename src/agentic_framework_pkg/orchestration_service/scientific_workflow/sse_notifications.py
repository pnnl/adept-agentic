"""
SSE (Server-Sent Events) Notifications for Streaming Tool Execution

This module provides utilities for emitting SSE notifications during agent execution.
Key use cases:
- File redirect notifications when tool output exceeds threshold
- Progress updates for long-running tools
- Real-time feedback during multi-step workflows

Architecture:
- Event queue stores notifications during agent execution
- Streaming response polls queue and emits SSE messages
- Non-blocking design ensures agent execution isn't delayed by SSE
"""

import asyncio
import json
from typing import Dict, Any, Optional
from collections import deque
from ...logger_config import get_logger

logger = get_logger(__name__)


class SSENotificationQueue:
    """
    Thread-safe queue for SSE notifications.

    Supports multiple producers (tools/agents) and single consumer (streaming response).
    """

    def __init__(self, max_size: int = 100):
        """
        Initialize notification queue.

        Args:
            max_size: Maximum number of pending notifications (default: 100)
        """
        self.queue = deque(maxlen=max_size)
        self.lock = asyncio.Lock()

    async def push(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Add notification to queue.

        Args:
            event_type: Type of event (e.g., "file_redirect", "progress")
            data: Event data dictionary
        """
        async with self.lock:
            self.queue.append({
                "event": event_type,
                "data": data,
            })
            logger.debug(f"[SSE_QUEUE] Pushed event: {event_type}, queue size: {len(self.queue)}")

    async def pop(self) -> Optional[Dict[str, Any]]:
        """
        Remove and return next notification from queue.

        Returns:
            Notification dict or None if queue is empty
        """
        async with self.lock:
            if self.queue:
                return self.queue.popleft()
            return None

    async def pop_all(self) -> list:
        """
        Remove and return all notifications from queue.

        Returns:
            List of notification dicts
        """
        async with self.lock:
            notifications = list(self.queue)
            self.queue.clear()
            return notifications

    def size(self) -> int:
        """Return current queue size."""
        return len(self.queue)


def format_sse_message(event_type: str, data: Dict[str, Any]) -> str:
    """
    Format notification as SSE message.

    SSE format:
        event: <event_type>
        data: <json_data>

    Args:
        event_type: Type of event
        data: Event data dictionary

    Returns:
        Formatted SSE message string
    """
    data_json = json.dumps(data)
    return f"event: {event_type}\ndata: {data_json}\n\n"


def format_file_redirect_notification(
    tool_name: str,
    file_id: str,
    total_chars: int,
    threshold_chars: int,
) -> Dict[str, Any]:
    """
    Format file redirect notification data.

    Args:
        tool_name: Name of the tool that generated output
        file_id: ID of the redirected file
        total_chars: Total characters in output
        threshold_chars: Threshold that triggered redirect

    Returns:
        Notification data dictionary
    """
    return {
        "message": f"Tool output ({total_chars:,} chars) exceeded threshold ({threshold_chars:,} chars), saved to file",
        "tool_name": tool_name,
        "file_id": file_id,
        "total_chars": total_chars,
        "threshold_chars": threshold_chars,
        "action": "file_redirect",
    }


def format_progress_notification(
    message: str,
    progress_percent: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Format progress notification data.

    Args:
        message: Progress message
        progress_percent: Optional progress percentage (0-100)
        metadata: Optional additional metadata

    Returns:
        Notification data dictionary
    """
    notification = {
        "message": message,
        "action": "progress",
    }
    if progress_percent is not None:
        notification["progress_percent"] = progress_percent
    if metadata:
        notification["metadata"] = metadata
    return notification


# Global notification queue for current agent execution
# Note: In production, use per-session queues keyed by thread_id
_global_queue = SSENotificationQueue()


async def emit_notification(event_type: str, data: Dict[str, Any]) -> None:
    """
    Emit SSE notification to global queue.

    This is a convenience function for use during agent execution.
    The streaming response will poll this queue and emit SSE messages.

    Args:
        event_type: Type of event (e.g., "file_redirect", "progress")
        data: Event data dictionary
    """
    await _global_queue.push(event_type, data)


async def get_pending_notifications() -> list:
    """
    Get all pending notifications from global queue.

    Returns:
        List of notification dicts
    """
    return await _global_queue.pop_all()


def create_session_queue(session_id: str) -> SSENotificationQueue:
    """
    Create a new SSE notification queue for a session.

    In production, store per-session queues in a registry keyed by session_id.
    For Phase 3 implementation, using global queue for simplicity.

    Args:
        session_id: Session identifier

    Returns:
        New SSENotificationQueue instance
    """
    logger.debug(f"[SSE_NOTIFICATIONS] Created queue for session: {session_id}")
    return SSENotificationQueue()
