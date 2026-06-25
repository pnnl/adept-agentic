"""Tests for session routes — POST /v1/sessions, GET /v1/sessions."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import create_mock_facade


def _create_test_app(mock_facade):
    from adept_connectors.connectors.chatgpt.app import create_app
    from adept_connectors.connectors.chatgpt.config import ChatGPTConnectorConfig
    from adept_connectors.connectors.chatgpt.rendering import ImageCache

    config = ChatGPTConnectorConfig()
    app = create_app(config)
    app.state.facade = mock_facade
    app.state.image_cache = ImageCache()
    app.state.config = config
    return app


class TestSessionRoutes:
    """Tests for session CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_session(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/sessions", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "thread_id" in data
        assert "session_id" in data
        assert data["message_count"] == 0

    @pytest.mark.asyncio
    async def test_create_session_with_specific_id(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/sessions", json={"session_id": "my-session"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == "my-session"

    @pytest.mark.asyncio
    async def test_create_session_idempotent(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.post("/v1/sessions", json={"session_id": "same-id"})
            resp2 = await client.post("/v1/sessions", json={"session_id": "same-id"})
        assert resp1.json()["thread_id"] == resp2.json()["thread_id"]

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_sessions_after_creation(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/v1/sessions", json={"session_id": "s1"})
            await client.post("/v1/sessions", json={"session_id": "s2"})
            resp = await client.get("/v1/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 2
        thread_ids = {s["thread_id"] for s in sessions}
        assert "s1" in thread_ids
        assert "s2" in thread_ids
