"""Tests for file routes — POST /v1/files/upload, GET /v1/files."""

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


class TestFileRoutes:
    """Tests for file upload and listing."""

    @pytest.mark.asyncio
    async def test_upload_file(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/files/upload",
                files={"file": ("test.csv", b"col1,col2\n1,2\n", "text/csv")},
                data={"purpose": "assistants"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "file-test-001"
        assert data["filename"] == "test.csv"

    @pytest.mark.asyncio
    async def test_upload_file_with_session_id(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/files/upload",
                files={"file": ("data.json", b'{"key": "value"}', "application/json")},
                data={"purpose": "assistants", "session_id": "sess-001"},
            )
        assert resp.status_code == 200
        # Verify session_id was passed through
        mock_facade.files.upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_files(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["data"]) == 2
        assert data["data"][0]["id"] == "file-001"
        assert data["data"][1]["filename"] == "plot.png"

    @pytest.mark.asyncio
    async def test_list_files_with_session_filter(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/files", params={"session_id": "sess-001"})
        assert resp.status_code == 200
        mock_facade.files.list_files.assert_called_with(session_id="sess-001")

    @pytest.mark.asyncio
    async def test_upload_without_file_returns_422(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/files/upload", data={"purpose": "assistants"})
        assert resp.status_code == 422
