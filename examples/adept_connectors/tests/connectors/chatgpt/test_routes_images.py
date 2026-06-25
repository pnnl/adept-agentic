"""Tests for image proxy route — GET /v1/images/{token}."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from conftest import create_mock_facade


def _create_test_app(mock_facade, image_cache):
    from adept_connectors.connectors.chatgpt.app import create_app
    from adept_connectors.connectors.chatgpt.config import ChatGPTConnectorConfig

    config = ChatGPTConnectorConfig()
    app = create_app(config)
    app.state.facade = mock_facade
    app.state.image_cache = image_cache
    app.state.config = config
    return app


class TestImageProxyRoute:
    """Tests for the image proxy endpoint."""

    @pytest.mark.asyncio
    async def test_get_cached_image(self, mock_facade, image_cache, sample_image_data):
        token = image_cache.store(sample_image_data)
        app = _create_test_app(mock_facade, image_cache)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/v1/images/{token}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content == sample_image_data.data
        assert "X-Image-Size" in resp.headers

    @pytest.mark.asyncio
    async def test_get_missing_image_returns_404(self, mock_facade, image_cache):
        app = _create_test_app(mock_facade, image_cache)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/images/nonexistent-token")
        assert resp.status_code == 404
        assert "error" in resp.json()

    @pytest.mark.asyncio
    async def test_get_expired_image_returns_404(self, mock_facade):
        import time
        from adept_connectors.connectors.chatgpt.rendering import ImageCache
        from adept_connectors.core.rendering import ImageData

        cache = ImageCache(max_size=10, ttl_seconds=1)
        img = ImageData(data=b"expiring-image", mime_type="image/jpeg")
        token = cache.store(img)

        time.sleep(1.1)

        app = _create_test_app(mock_facade, cache)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/v1/images/{token}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cache_control_header(self, mock_facade, image_cache, sample_image_data):
        token = image_cache.store(sample_image_data)
        app = _create_test_app(mock_facade, image_cache)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/v1/images/{token}")
        assert "public, max-age=300" in resp.headers.get("cache-control", "")
