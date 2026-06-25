"""Tests for the health check endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import create_mock_facade


class TestHealthCheck:
    """Tests for GET /health."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, mock_facade):
        from adept_connectors.connectors.chatgpt.app import create_app
        from adept_connectors.connectors.chatgpt.config import ChatGPTConnectorConfig
        from adept_connectors.connectors.chatgpt.rendering import ImageCache

        config = ChatGPTConnectorConfig()
        app = create_app(config)
        app.state.facade = mock_facade
        app.state.image_cache = ImageCache()
        app.state.config = config

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "adept-chatgpt-connector"
