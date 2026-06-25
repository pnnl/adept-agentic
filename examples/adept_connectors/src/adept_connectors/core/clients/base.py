"""Base HTTP client for ADEPT API communication."""

from __future__ import annotations

import logging
import uuid
from typing import Optional

import httpx

from ..auth import AuthManager
from ..config import AdeptConnectorConfig

logger = logging.getLogger(__name__)

# Connector version — kept in sync with pyproject.toml
_CONNECTOR_VERSION = "0.1.0"


class BaseAdeptClient:
    """Shared httpx.AsyncClient lifecycle with auth header injection.

    Injects observability headers on every request so gateway/orchestration
    logs can correlate connector traffic with other ADEPT clients.

    Args:
        config: ADEPT connector configuration.
        auth: Authentication manager instance.
        client_source: Value for X-Client-Source header (e.g. "claude-desktop-connector",
            "chatgpt-connector", "roo-code-proxy"). Defaults to "adept-connector".

    Usage:
        client = BaseAdeptClient(config, auth_manager, client_source="my-connector")
        async with client:
            resp = await client.get("/responses/models")
    """

    def __init__(
        self,
        config: AdeptConnectorConfig,
        auth: AuthManager,
        client_source: str = "adept-connector",
    ) -> None:
        self._config = config
        self._auth = auth
        self._client_source = client_source
        self._client: Optional[httpx.AsyncClient] = None
        # Stable instance ID for the lifetime of this connector process.
        # Correlates all requests from one connector session.
        self._instance_id = str(uuid.uuid4())

    @property
    def base_url(self) -> str:
        return self._config.base_url.rstrip("/")

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self._config.request_timeout),
                verify=self._config.verify_ssl,
            )
        return self._client

    async def _headers(self) -> dict[str, str]:
        headers = await self._auth.get_auth_headers()
        headers["Content-Type"] = "application/json"
        # Observability headers for cross-client log correlation
        headers["X-Client-Source"] = self._client_source
        headers["X-Client-Version"] = _CONNECTOR_VERSION
        headers["X-Connector-Instance-ID"] = self._instance_id
        headers["X-Request-ID"] = str(uuid.uuid4())
        return headers

    async def get(self, path: str, **kwargs) -> httpx.Response:
        client = await self._ensure_client()
        headers = await self._headers()
        headers.update(kwargs.pop("headers", {}))
        return await client.get(path, headers=headers, **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        client = await self._ensure_client()
        headers = await self._headers()
        headers.update(kwargs.pop("headers", {}))
        return await client.post(path, headers=headers, **kwargs)

    async def post_stream(self, path: str, **kwargs):
        """POST with streaming response (for SSE/JSONL).

        Returns an async context manager from httpx.AsyncClient.stream().
        Must be used as: async with (await client.post_stream(...)) as resp:
        """
        client = await self._ensure_client()
        headers = await self._headers()
        headers.update(kwargs.pop("headers", {}))
        return client.stream("POST", path, headers=headers, **kwargs)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "BaseAdeptClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()
