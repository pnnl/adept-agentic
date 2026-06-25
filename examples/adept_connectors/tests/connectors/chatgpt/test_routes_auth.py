"""Tests for OAuth2 auth routes — /auth/authorize, /auth/callback, /auth/token."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

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


class TestAuthorizeRoute:
    """Tests for GET /auth/authorize."""

    @pytest.mark.asyncio
    async def test_authorize_redirects_to_keycloak(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get("/auth/authorize")
        assert resp.status_code in (302, 307)
        location = resp.headers["location"]
        assert "/realms/master/protocol/openid-connect/auth" in location
        assert "client_id=chatgpt-connector" in location
        assert "response_type=code" in location

    @pytest.mark.asyncio
    async def test_authorize_includes_state(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get("/auth/authorize", params={"state": "xyz123"})
        location = resp.headers["location"]
        assert "state=xyz123" in location


class TestTokenExchangeRoute:
    """Tests for POST /auth/token."""

    @pytest.mark.asyncio
    async def test_exchange_authorization_code(self, mock_facade):
        # Pre-populate the token store with a code
        from adept_connectors.connectors.chatgpt.routes.auth import _token_store
        _token_store["test-code-001"] = {
            "access_token": "at-12345",
            "refresh_token": "rt-67890",
            "expires_in": 300,
            "obtained_at": 1000000,
        }

        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auth/token", json={
                "grant_type": "authorization_code",
                "code": "test-code-001",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "at-12345"
        assert data["refresh_token"] == "rt-67890"
        assert data["token_type"] == "Bearer"

    @pytest.mark.asyncio
    async def test_exchange_invalid_code_returns_400(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auth/token", json={
                "grant_type": "authorization_code",
                "code": "invalid-code",
            })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_exchange_code_single_use(self, mock_facade):
        from adept_connectors.connectors.chatgpt.routes.auth import _token_store
        _token_store["single-use-code"] = {
            "access_token": "at-once",
            "expires_in": 300,
            "obtained_at": 1000000,
        }

        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First use succeeds
            resp1 = await client.post("/auth/token", json={
                "grant_type": "authorization_code",
                "code": "single-use-code",
            })
            assert resp1.status_code == 200

            # Second use fails (code consumed)
            resp2 = await client.post("/auth/token", json={
                "grant_type": "authorization_code",
                "code": "single-use-code",
            })
            assert resp2.status_code == 400

    @pytest.mark.asyncio
    async def test_unsupported_grant_type_returns_400(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auth/token", json={
                "grant_type": "client_credentials",
            })
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_missing_code_returns_400(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auth/token", json={
                "grant_type": "authorization_code",
            })
        assert resp.status_code == 400


class TestAuthSuccessRoute:
    """Tests for GET /auth/success."""

    @pytest.mark.asyncio
    async def test_auth_success_page(self, mock_facade):
        app = _create_test_app(mock_facade)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/auth/success", params={"code": "test"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "authenticated"
