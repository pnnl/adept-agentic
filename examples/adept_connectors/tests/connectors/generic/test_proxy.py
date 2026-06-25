"""Tests for the auth proxy — transparent forwarding + auth injection."""

from __future__ import annotations

import json
import pytest
import httpx
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from adept_connectors.connectors.generic.proxy import ProxyConfig, create_proxy_app
from adept_connectors.core.auth import AuthManager


def _create_test_app(upstream_base="http://adept-test:8083/v1", api_key="test-key-123"):
    """Create a proxy app with state pre-initialized (bypasses lifespan for tests)."""
    config = ProxyConfig(
        base_url=upstream_base,
        proxy_host="127.0.0.1",
        proxy_port=19283,
        api_key=api_key,
        auth_method="api_key",
    )
    app = create_proxy_app(config)

    # Pre-initialize state that lifespan would normally set
    connector_config = config.to_connector_config()
    app.state.config = config
    app.state.auth = AuthManager(connector_config)
    app.state.upstream_base = config.base_url.rstrip("/")
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(config.request_timeout, connect=10.0),
        verify=config.verify_ssl,
    )
    return app


def _mock_response(status_code=200, body=None):
    """Create a mock httpx Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": "application/json"}
    resp.content = json.dumps(body or {}).encode()
    return resp


class TestHealthEndpoint:
    """Tests for GET /health."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        app = _create_test_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "adept-auth-proxy"
        assert "upstream" in data


class TestAuthInjection:
    """Tests for authentication header injection."""

    @pytest.mark.asyncio
    async def test_api_key_injected_into_request(self):
        """Proxy injects Authorization: Bearer <api_key> header."""
        app = _create_test_app(api_key="my-secret-key")
        captured_headers = {}

        async def mock_request(method, url, headers=None, content=None):
            captured_headers.update(headers or {})
            return _mock_response(body={"data": []})

        app.state.http_client.request = AsyncMock(side_effect=mock_request)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/models")

        assert resp.status_code == 200
        assert captured_headers.get("Authorization") == "Bearer my-secret-key"

    @pytest.mark.asyncio
    async def test_client_source_header_added(self):
        """Proxy adds X-Client-Source: adept-auth-proxy header."""
        app = _create_test_app()
        captured_headers = {}

        async def mock_request(method, url, headers=None, content=None):
            captured_headers.update(headers or {})
            return _mock_response()

        app.state.http_client.request = AsyncMock(side_effect=mock_request)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/v1/models")

        assert captured_headers.get("X-Client-Source") == "adept-auth-proxy"

    @pytest.mark.asyncio
    async def test_client_auth_header_stripped(self):
        """Client's own Authorization header is replaced, not forwarded."""
        app = _create_test_app(api_key="proxy-key")
        captured_headers = {}

        async def mock_request(method, url, headers=None, content=None):
            captured_headers.update(headers or {})
            return _mock_response()

        app.state.http_client.request = AsyncMock(side_effect=mock_request)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get(
                "/v1/models",
                headers={"Authorization": "Bearer client-should-be-replaced"},
            )

        # Proxy key should win, not the client's key
        assert captured_headers.get("Authorization") == "Bearer proxy-key"


class TestRequestForwarding:
    """Tests for transparent request forwarding."""

    @pytest.mark.asyncio
    async def test_get_request_forwarded(self):
        """GET /v1/models → upstream GET /v1/models."""
        app = _create_test_app(upstream_base="http://adept:8083/v1")
        captured_url = {}

        async def mock_request(method, url, headers=None, content=None):
            captured_url["method"] = method
            captured_url["url"] = url
            return _mock_response(body={"object": "list", "data": []})

        app.state.http_client.request = AsyncMock(side_effect=mock_request)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/models")

        assert resp.status_code == 200
        assert captured_url["method"] == "GET"
        assert captured_url["url"] == "http://adept:8083/v1/v1/models"

    @pytest.mark.asyncio
    async def test_post_request_with_body_forwarded(self):
        """POST body is forwarded to upstream."""
        app = _create_test_app()
        captured = {}

        async def mock_request(method, url, headers=None, content=None):
            captured["method"] = method
            captured["content"] = content
            return _mock_response(body={"id": "resp-123"})

        app.state.http_client.request = AsyncMock(side_effect=mock_request)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert resp.status_code == 200
        assert captured["method"] == "POST"
        body = json.loads(captured["content"])
        assert body["model"] == "test"

    @pytest.mark.asyncio
    async def test_query_params_forwarded(self):
        """Query parameters are included in upstream URL."""
        app = _create_test_app(upstream_base="http://adept:8083/v1")
        captured_url = {}

        async def mock_request(method, url, headers=None, content=None):
            captured_url["url"] = url
            return _mock_response(body={"data": []})

        app.state.http_client.request = AsyncMock(side_effect=mock_request)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/v1/files", params={"session_id": "s-123"})

        assert "session_id=s-123" in captured_url["url"]


class TestErrorHandling:
    """Tests for upstream error handling."""

    @pytest.mark.asyncio
    async def test_upstream_connect_error_returns_502(self):
        """Connection failure to upstream returns 502."""
        app = _create_test_app()
        app.state.http_client.request = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/models")

        assert resp.status_code == 502
        assert "proxy_error" in resp.json()["error"]["type"]

    @pytest.mark.asyncio
    async def test_upstream_timeout_returns_504(self):
        """Timeout to upstream returns 504."""
        app = _create_test_app()
        app.state.http_client.request = AsyncMock(
            side_effect=httpx.ReadTimeout("Timed out")
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/models")

        assert resp.status_code == 504
        assert "timed out" in resp.json()["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_upstream_error_status_relayed(self):
        """Upstream 4xx/5xx status codes are relayed to client."""
        app = _create_test_app()

        async def mock_request(method, url, headers=None, content=None):
            return _mock_response(status_code=404, body={"error": "not found"})

        app.state.http_client.request = AsyncMock(side_effect=mock_request)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/nonexistent")

        assert resp.status_code == 404


class TestProxyConfig:
    """Tests for ProxyConfig and its conversion to AdeptConnectorConfig."""

    def test_default_config(self):
        config = ProxyConfig(api_key="test-key")
        assert config.proxy_host == "127.0.0.1"
        assert config.proxy_port == 19283
        assert config.base_url == "http://localhost:8083/v1"

    def test_to_connector_config(self):
        config = ProxyConfig(
            base_url="http://custom:9090/v1",
            api_key="sk-123",
            auth_method="api_key",
        )
        connector_config = config.to_connector_config()
        assert connector_config.base_url == "http://custom:9090/v1"
        assert connector_config.api_key == "sk-123"
        assert connector_config.auth_method.value == "api_key"

    def test_password_auth_config(self):
        config = ProxyConfig(
            auth_method="password",
            username="alice",
            password="secret",
            keycloak_url="http://keycloak:8180",
        )
        connector_config = config.to_connector_config()
        assert connector_config.auth_method.value == "password"
        assert connector_config.username == "alice"
        assert connector_config.password == "secret"
