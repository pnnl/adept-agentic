"""Tests for tool routes — GET /v1/tools, POST /v1/tools/{name}."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

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


class TestToolRoutes:
    """Tests for tool discovery and invocation."""

    @pytest.mark.asyncio
    async def test_list_tools(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/tools")
        assert resp.status_code == 200
        tools = resp.json()
        assert len(tools) == 2
        assert tools[0]["name"] == "websearch"
        assert tools[1]["name"] == "execute_code"
        assert "description" in tools[0]

    @pytest.mark.asyncio
    async def test_call_tool_success(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/tools/websearch", json={
                "arguments": {"query": "CRISPR 2026"},
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_name"] == "websearch"
        assert data["success"] is True
        assert "result" in data

    @pytest.mark.asyncio
    async def test_call_tool_with_session_id(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/tools/execute_code", json={
                "arguments": {"code": "print(42)"},
                "session_id": "sess-001",
            })
        assert resp.status_code == 200
        # Verify session_id was injected into arguments
        call_args = mock_facade.mcp.call_tool.call_args
        assert call_args[0][1]["session_id"] == "sess-001"

    @pytest.mark.asyncio
    async def test_call_tool_failure(self, mock_facade):
        mock_facade.mcp.call_tool = AsyncMock(side_effect=RuntimeError("MCP error"))
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/tools/bad_tool", json={})
        assert resp.status_code == 200  # Returns 200 with error in body
        data = resp.json()
        assert data["success"] is False
        assert "MCP error" in data["error"]

    @pytest.mark.asyncio
    async def test_call_tool_no_arguments(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/tools/list_models", json={})
        assert resp.status_code == 200
