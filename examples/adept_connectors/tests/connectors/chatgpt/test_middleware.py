"""Tests for Bearer token middleware."""

from __future__ import annotations

import os
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from conftest import create_mock_facade


def _create_test_app(mock_facade, auth_disabled=True):
    """Create app with or without auth bypass."""
    if auth_disabled:
        os.environ["CHATGPT_AUTH_DISABLED"] = "true"
    else:
        os.environ.pop("CHATGPT_AUTH_DISABLED", None)

    from adept_connectors.connectors.chatgpt.app import create_app
    from adept_connectors.connectors.chatgpt.config import ChatGPTConnectorConfig
    from adept_connectors.connectors.chatgpt.rendering import ImageCache

    config = ChatGPTConnectorConfig()
    app = create_app(config)
    app.state.facade = mock_facade
    app.state.image_cache = ImageCache()
    app.state.config = config
    return app


class TestBearerTokenMiddleware:
    """Tests for authentication middleware."""

    @pytest.mark.asyncio
    async def test_public_paths_skip_auth(self, mock_facade):
        """Health and auth endpoints don't require Bearer token."""
        app = _create_test_app(mock_facade, auth_disabled=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_missing_auth_header_returns_401(self, mock_facade):
        app = _create_test_app(mock_facade, auth_disabled=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/tools")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers

    @pytest.mark.asyncio
    async def test_invalid_auth_format_returns_401(self, mock_facade):
        app = _create_test_app(mock_facade, auth_disabled=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/v1/tools",
                headers={"Authorization": "Basic dXNlcjpwYXNz"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_disabled_bypasses_validation(self, mock_facade):
        """CHATGPT_AUTH_DISABLED=true skips all token validation."""
        app = _create_test_app(mock_facade, auth_disabled=True)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/tools")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_valid_token_passes_through(self, mock_facade):
        """A valid token (mocked Keycloak userinfo) passes through."""
        app = _create_test_app(mock_facade, auth_disabled=False)

        # Patch the middleware's _validate_token to return userinfo
        from adept_connectors.connectors.chatgpt.middleware.auth import BearerTokenMiddleware
        original_validate = BearerTokenMiddleware._validate_token

        async def mock_validate(self, token):
            if token == "valid-test-token":
                return {"sub": "user-001", "preferred_username": "testuser"}
            return None

        with patch.object(BearerTokenMiddleware, "_validate_token", mock_validate):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/v1/tools",
                    headers={"Authorization": "Bearer valid-test-token"},
                )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, mock_facade):
        """An invalid token (Keycloak rejects) returns 401."""
        app = _create_test_app(mock_facade, auth_disabled=False)

        from adept_connectors.connectors.chatgpt.middleware.auth import BearerTokenMiddleware

        async def mock_validate(self, token):
            return None  # All tokens invalid

        with patch.object(BearerTokenMiddleware, "_validate_token", mock_validate):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/v1/tools",
                    headers={"Authorization": "Bearer bad-token"},
                )
            assert resp.status_code == 401

    def teardown_method(self):
        """Restore auth bypass for other tests."""
        os.environ["CHATGPT_AUTH_DISABLED"] = "true"
