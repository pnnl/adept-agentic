"""Transparent OpenAI-compatible auth proxy for ADEPT.

Accepts requests at ``localhost:PORT/v1/*``, injects authentication
headers via :class:`~adept_connectors.core.auth.AuthManager`, and
forwards them to the real ADEPT Agent Gateway.  Responses — including
SSE streams — are relayed back verbatim.

Any OpenAI-compatible tool (Roo Code, Continue.dev, Cursor, OBot.ai)
can point at this proxy with zero code changes.  The proxy handles
the full JWT lifecycle (ROPC login, token refresh) transparently.

Usage::

    adept-auth-proxy --port 19283
    # Then configure your IDE:  base_url = http://localhost:19283/v1
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

from adept_connectors.core.auth import AuthManager
from adept_connectors.core.config import AdeptConnectorConfig, ConnectorProfile

logger = logging.getLogger(__name__)

# Headers that must NOT be forwarded to the upstream
_HOP_BY_HOP = frozenset(
    {
        "host",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
        "proxy-authorization",
        "proxy-authenticate",
    }
)

# Response headers that should not be relayed back
_SKIP_RESPONSE_HEADERS = frozenset(
    {
        "transfer-encoding",
        "content-encoding",
        "content-length",
    }
)


class ProxyConfig(ConnectorProfile):
    """Auth proxy configuration.

    Extends :class:`ConnectorProfile` with proxy-specific settings.
    Reads from env vars prefixed ``ADEPT_`` (same as ConnectorProfile).
    """

    model_config = {"env_prefix": "ADEPT_", "env_file": ".env", "extra": "ignore"}

    proxy_host: str = "127.0.0.1"
    proxy_port: int = 19283

    # Auth — when auth_method is set, create a full AdeptConnectorConfig
    auth_method: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    jwt_token: Optional[str] = None
    keycloak_url: Optional[str] = None
    keycloak_realm: str = "master"
    keycloak_client_id: str = "login-client"

    def to_connector_config(self) -> AdeptConnectorConfig:
        """Build a full AdeptConnectorConfig for AuthManager."""
        method = self.auth_method or "api_key"
        return AdeptConnectorConfig(
            base_url=self.base_url,
            request_timeout=self.request_timeout,
            verify_ssl=self.verify_ssl,
            auth_method=method,
            api_key=self.api_key,
            jwt_token=self.jwt_token,
            username=self.username,
            password=self.password,
            keycloak_url=self.keycloak_url,
            keycloak_realm=self.keycloak_realm,
            keycloak_client_id=self.keycloak_client_id,
        )


def create_proxy_app(config: Optional[ProxyConfig] = None) -> FastAPI:
    """Create the auth proxy FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = config or ProxyConfig()
        connector_config = cfg.to_connector_config()
        app.state.config = cfg
        app.state.auth = AuthManager(connector_config)
        app.state.upstream_base = cfg.base_url.rstrip("/")
        app.state.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(cfg.request_timeout, connect=10.0),
            verify=cfg.verify_ssl,
        )
        logger.info(
            "Auth proxy started — listening on %s:%d, forwarding to %s",
            cfg.proxy_host,
            cfg.proxy_port,
            app.state.upstream_base,
        )
        yield
        await app.state.http_client.aclose()
        logger.info("Auth proxy stopped")

    app = FastAPI(
        title="ADEPT Auth Proxy",
        description="Transparent OpenAI-compatible proxy with ADEPT authentication",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "adept-auth-proxy",
            "upstream": app.state.upstream_base,
        }

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_request(request: Request, path: str):
        """Forward any request to the ADEPT upstream with injected auth."""
        auth_headers = await app.state.auth.get_auth_headers()

        # Build upstream URL
        upstream_url = f"{app.state.upstream_base}/{path}"
        if request.url.query:
            upstream_url = f"{upstream_url}?{request.url.query}"

        # Forward headers, replacing auth and stripping hop-by-hop
        headers = {}
        for key, value in request.headers.items():
            if key.lower() not in _HOP_BY_HOP and key.lower() != "authorization":
                headers[key] = value
        headers.update(auth_headers)
        headers["X-Client-Source"] = "adept-auth-proxy"

        # Read request body
        body = await request.body()

        # Determine if upstream response should be streamed
        # (SSE for chat completions, large file downloads, etc.)
        accept = request.headers.get("accept", "")
        wants_stream = "text/event-stream" in accept

        try:
            if wants_stream:
                return await _stream_response(
                    app.state.http_client,
                    request.method,
                    upstream_url,
                    headers=headers,
                    content=body if body else None,
                )
            else:
                return await _forward_response(
                    app.state.http_client,
                    request.method,
                    upstream_url,
                    headers=headers,
                    content=body if body else None,
                )
        except httpx.ConnectError:
            logger.error("Cannot reach upstream %s", upstream_url)
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "message": f"Cannot reach ADEPT upstream at {app.state.upstream_base}",
                        "type": "proxy_error",
                    }
                },
            )
        except httpx.TimeoutException:
            logger.error("Upstream timeout for %s", upstream_url)
            return JSONResponse(
                status_code=504,
                content={
                    "error": {
                        "message": "ADEPT upstream request timed out",
                        "type": "proxy_error",
                    }
                },
            )

    return app


async def _forward_response(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict,
    content: Optional[bytes],
) -> JSONResponse:
    """Send a non-streaming request and return the response."""
    resp = await client.request(method, url, headers=headers, content=content)

    # Build response headers
    resp_headers = {}
    for key, value in resp.headers.items():
        if key.lower() not in _SKIP_RESPONSE_HEADERS:
            resp_headers[key] = value

    return StreamingResponse(
        content=iter([resp.content]),
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type"),
    )


async def _stream_response(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict,
    content: Optional[bytes],
) -> StreamingResponse:
    """Send a streaming request and relay SSE chunks."""

    async def _generate():
        async with client.stream(method, url, headers=headers, content=content) as resp:
            async for chunk in resp.aiter_bytes():
                yield chunk

    return StreamingResponse(
        content=_generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
