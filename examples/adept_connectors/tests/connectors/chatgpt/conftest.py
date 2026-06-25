"""Shared test fixtures for ChatGPT connector tests.

Provides:
- Mock AdeptFacade that returns canned responses
- Test FastAPI client (httpx.AsyncClient via ASGI transport)
- Image cache fixtures
- Config fixtures with auth disabled
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set auth bypass before any imports
os.environ["CHATGPT_AUTH_DISABLED"] = "true"
os.environ.setdefault("ADEPT_API_KEY", "test-key-for-chatgpt-tests")


@dataclass
class MockSessionInfo:
    """Minimal session info for tests."""

    thread_id: str = "test-thread-001"
    session_id: str = "test-thread-001"
    mcp_session_id: str = "test-thread-001"
    multi_agent_session_id: Optional[str] = None
    gateway_session_id: Optional[str] = None
    message_count: int = 0
    created_at: str = "2026-03-31T00:00:00+00:00"
    updated_at: str = "2026-03-31T00:00:00+00:00"

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

    def touch(self) -> None:
        pass


@dataclass
class MockChatResult:
    """Mock ChatResult for testing."""

    text: str = "Hello from ADEPT!"
    images: list = field(default_factory=list)
    session_fork: Optional[dict] = None
    session: Optional[MockSessionInfo] = None
    model: str = "agentic-framework:scientific-agent-v1"
    finish_reason: Optional[str] = "stop"
    tool_calls: list = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        return len(self.images) > 0


class MockSessionManager:
    """Mock session manager for tests."""

    def __init__(self) -> None:
        self._sessions: dict[str, MockSessionInfo] = {}

    def get_or_create(self, thread_id: Optional[str] = None) -> MockSessionInfo:
        if thread_id and thread_id in self._sessions:
            return self._sessions[thread_id]
        import uuid
        tid = thread_id or str(uuid.uuid4())
        info = MockSessionInfo(thread_id=tid, session_id=tid, mcp_session_id=tid)
        self._sessions[tid] = info
        return info

    def list_sessions(self) -> list[dict]:
        return [s.to_dict() for s in self._sessions.values()]


def create_mock_facade():
    """Create a mock AdeptFacade with sensible defaults."""
    facade = MagicMock()

    # chat() returns a mock result
    default_session = MockSessionInfo()
    default_result = MockChatResult(session=default_session)

    async def mock_chat(message, session_id=None, model=None, auto_fetch_images=True):
        return MockChatResult(
            text=f"ADEPT response to: {message}",
            session=MockSessionInfo(thread_id=session_id or "auto-session"),
        )

    facade.chat = AsyncMock(side_effect=mock_chat)
    facade.render = MagicMock(side_effect=lambda r: r.text)

    # Session manager
    facade.session_mgr = MockSessionManager()

    # Files client
    facade.files = MagicMock()
    facade.files.upload = AsyncMock(return_value={
        "id": "file-test-001",
        "filename": "test.csv",
        "bytes": 1024,
        "purpose": "assistants",
    })
    facade.files.list_files = AsyncMock(return_value=[
        {"id": "file-001", "filename": "data.csv", "bytes": 2048, "purpose": "assistants"},
        {"id": "file-002", "filename": "plot.png", "bytes": 50000, "purpose": "assistants"},
    ])

    # MCP proxy client
    facade.mcp = MagicMock()
    facade.mcp.list_tools = AsyncMock(return_value=[
        {"name": "websearch", "description": "Search the web", "inputSchema": {"type": "object"}},
        {"name": "execute_code", "description": "Run Python code", "inputSchema": {"type": "object"}},
    ])
    facade.mcp.call_tool = AsyncMock(return_value="Tool result: success")

    # Close
    facade.close = AsyncMock()

    return facade


@pytest.fixture
def mock_facade():
    """Provide a mock AdeptFacade."""
    return create_mock_facade()


@pytest.fixture
def image_cache():
    """Provide a fresh ImageCache."""
    from adept_connectors.connectors.chatgpt.rendering import ImageCache
    return ImageCache(max_size=10, ttl_seconds=5)


@pytest.fixture
def sample_image_data():
    """Provide a sample ImageData for testing."""
    from adept_connectors.core.rendering import ImageData
    # 1x1 red PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
        b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
        b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return ImageData(
        data=png_bytes,
        mime_type="image/png",
        source_url="https://adept.example.com/v1/plots/test.png",
    )
