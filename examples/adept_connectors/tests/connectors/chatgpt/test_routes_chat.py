"""Tests for POST /v1/chat route."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import MockChatResult, MockSessionInfo, create_mock_facade


def _create_test_app(mock_facade):
    """Create a test app with a mock facade."""
    from adept_connectors.connectors.chatgpt.app import create_app
    from adept_connectors.connectors.chatgpt.config import ChatGPTConnectorConfig
    from adept_connectors.connectors.chatgpt.rendering import ImageCache

    config = ChatGPTConnectorConfig()
    app = create_app(config)

    # Inject mock facade (bypasses lifespan)
    app.state.facade = mock_facade
    app.state.image_cache = ImageCache()
    app.state.config = config

    return app


class TestChatRoute:
    """Tests for POST /v1/chat."""

    @pytest.mark.asyncio
    async def test_basic_chat(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/chat", json={
                "message": "What is BLAST?",
                "session_id": "sess-001",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "content" in data
        assert "ADEPT response to: What is BLAST?" in data["content"]
        assert data["image_count"] == 0
        assert data["session_forked"] is False

    @pytest.mark.asyncio
    async def test_chat_without_session_id(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/chat", json={"message": "Hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] is not None

    @pytest.mark.asyncio
    async def test_chat_with_model_override(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/chat", json={
                "message": "test",
                "model": "gpt-4o",
            })
        assert resp.status_code == 200
        # Verify model was passed to facade
        mock_facade.chat.assert_called_once()
        call_kwargs = mock_facade.chat.call_args
        assert call_kwargs.kwargs.get("model") == "gpt-4o" or call_kwargs[1].get("model") == "gpt-4o"

    @pytest.mark.asyncio
    async def test_chat_missing_message_returns_422(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/chat", json={})
        assert resp.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_chat_with_session_fork(self, mock_facade):
        """When ADEPT forks a session, the response indicates it."""
        from unittest.mock import AsyncMock

        async def mock_chat_fork(message, session_id=None, model=None, auto_fetch_images=True):
            return MockChatResult(
                text="Continued with new context",
                session=MockSessionInfo(thread_id="forked-session"),
                session_fork={"forked_session_id": "forked-session"},
            )

        mock_facade.chat = AsyncMock(side_effect=mock_chat_fork)

        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/chat", json={"message": "continue"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_forked"] is True
