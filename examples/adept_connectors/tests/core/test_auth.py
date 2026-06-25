"""Tests for AuthManager."""

import time

import httpx
import pytest
import respx

from adept_connectors.core.auth import AuthManager
from adept_connectors.core.config import AdeptConnectorConfig, AuthMethod


def _make_config(monkeypatch, method="api_key", **overrides):
    """Helper to create config with env vars."""
    monkeypatch.setenv("ADEPT_AUTH_METHOD", method)
    if method == "api_key":
        monkeypatch.setenv("ADEPT_API_KEY", overrides.get("api_key", "sk-test-key"))
    elif method == "jwt":
        monkeypatch.setenv("ADEPT_JWT_TOKEN", overrides.get("jwt_token", "eyJ.test.jwt"))
    elif method == "password":
        monkeypatch.setenv("ADEPT_USERNAME", overrides.get("username", "alice@pnnl.gov"))
        monkeypatch.setenv("ADEPT_PASSWORD", overrides.get("password", "secret"))
    return AdeptConnectorConfig()


class TestAuthManagerApiKey:

    @pytest.mark.asyncio
    async def test_returns_bearer_header(self, monkeypatch):
        cfg = _make_config(monkeypatch, "api_key", api_key="sk-user-alice-abc123")
        auth = AuthManager(cfg)
        headers = await auth.get_auth_headers()
        assert headers == {"Authorization": "Bearer sk-user-alice-abc123"}

    @pytest.mark.asyncio
    async def test_stable_across_calls(self, monkeypatch):
        cfg = _make_config(monkeypatch, "api_key")
        auth = AuthManager(cfg)
        h1 = await auth.get_auth_headers()
        h2 = await auth.get_auth_headers()
        assert h1 == h2


class TestAuthManagerJwt:

    @pytest.mark.asyncio
    async def test_returns_bearer_header(self, monkeypatch):
        cfg = _make_config(monkeypatch, "jwt", jwt_token="eyJ.payload.sig")
        auth = AuthManager(cfg)
        headers = await auth.get_auth_headers()
        assert headers == {"Authorization": "Bearer eyJ.payload.sig"}


class TestAuthManagerPassword:

    @pytest.mark.asyncio
    @respx.mock
    async def test_ropc_flow(self, monkeypatch):
        cfg = _make_config(monkeypatch, "password")
        auth = AuthManager(cfg)

        token_url = (
            f"{cfg.keycloak_url}/realms/{cfg.keycloak_realm}"
            f"/protocol/openid-connect/token"
        )
        respx.post(token_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "fresh-jwt-token",
                    "refresh_token": "refresh-abc",
                    "expires_in": 300,
                },
            )
        )

        headers = await auth.get_auth_headers()
        assert headers == {"Authorization": "Bearer fresh-jwt-token"}
        assert auth._refresh_token == "refresh-abc"

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_when_near_expiry(self, monkeypatch):
        cfg = _make_config(monkeypatch, "password")
        auth = AuthManager(cfg)

        token_url = (
            f"{cfg.keycloak_url}/realms/{cfg.keycloak_realm}"
            f"/protocol/openid-connect/token"
        )

        # First call — ROPC
        respx.post(token_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "token-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 300,
                },
            )
        )
        await auth.get_auth_headers()

        # Simulate near-expiry
        auth._expires_at = time.time() + 30  # 30s left, below 60s threshold

        # Second call — should use refresh_token grant
        respx.post(token_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "token-2",
                    "refresh_token": "refresh-2",
                    "expires_in": 300,
                },
            )
        )
        headers = await auth.get_auth_headers()
        assert headers == {"Authorization": "Bearer token-2"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_raises(self, monkeypatch):
        cfg = _make_config(monkeypatch, "password")
        auth = AuthManager(cfg)

        token_url = (
            f"{cfg.keycloak_url}/realms/{cfg.keycloak_realm}"
            f"/protocol/openid-connect/token"
        )
        respx.post(token_url).mock(
            return_value=httpx.Response(401, json={"error": "invalid_grant"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            await auth.get_auth_headers()
