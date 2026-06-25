"""JSON-RPC proxy client for ADEPT MCP server.

Forwards tools/list and tools/call requests to the ADEPT MCP server endpoint.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import httpx

from ..config import AdeptConnectorConfig
from ..auth import AuthManager

logger = logging.getLogger(__name__)

# Keep in sync with base.py and pyproject.toml
_CONNECTOR_VERSION = "0.1.0"


class MCPProxyClient:
    """Proxy client for ADEPT's MCP server via JSON-RPC over HTTP.

    Args:
        config: ADEPT connector configuration.
        auth: Authentication manager instance.
        instance_id: Stable connector instance ID for log correlation.
        client_source: Value for X-Client-Source header. Defaults to "adept-connector".
    """

    def __init__(
        self,
        config: AdeptConnectorConfig,
        auth: AuthManager,
        instance_id: Optional[str] = None,
        client_source: str = "adept-connector",
    ) -> None:
        self._config = config
        self._auth = auth
        self._base_url = config.mcp_server_url or self._derive_mcp_url(config.base_url)
        self._instance_id = instance_id or str(uuid.uuid4())
        self._client_source = client_source

    @staticmethod
    def _derive_mcp_url(base_url: str) -> str:
        """Derive MCP server URL from gateway base URL.

        Default: replace /v1 path with /mcp on same host.
        Preserves scheme and explicit port; omits port when using
        standard defaults (80 for http, 443 for https).
        """
        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        # Only include port if explicitly specified in the URL.
        # No trailing slash: nginx exact-match location = /mcp {} handles this.
        # Trailing slash would cause a redirect loop (nginx 301 ↔ FastAPI 307).
        if parsed.port:
            return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}/mcp"
        return f"{parsed.scheme}://{parsed.hostname}/mcp"

    async def _rpc_call(
        self, method: str, params: Optional[dict[str, Any]] = None
    ) -> Any:
        """Send a JSON-RPC 2.0 request."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
        }
        if params:
            payload["params"] = params

        headers = await self._auth.get_auth_headers()
        headers["Content-Type"] = "application/json"
        # Observability headers (same set as BaseAdeptClient)
        headers["X-Client-Source"] = self._client_source
        headers["X-Client-Version"] = _CONNECTOR_VERSION
        headers["X-Connector-Instance-ID"] = self._instance_id
        headers["X-Request-ID"] = str(uuid.uuid4())

        async with httpx.AsyncClient(
            verify=self._config.verify_ssl,
            timeout=httpx.Timeout(self._config.request_timeout),
            follow_redirects=True,
        ) as client:
            resp = await client.post(self._base_url, json=payload, headers=headers)
            resp.raise_for_status()

        result = resp.json()
        if "error" in result:
            error = result["error"]
            raise RuntimeError(
                f"MCP JSON-RPC error {error.get('code', '?')}: {error.get('message', '')}"
            )
        return result.get("result")

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the MCP server."""
        result = await self._rpc_call("tools/list")
        if isinstance(result, dict) and "tools" in result:
            return result["tools"]
        if isinstance(result, list):
            return result
        return []

    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> str:
        """Call a tool on the MCP server and return the result as a string."""
        params: dict[str, Any] = {"name": tool_name}
        if arguments:
            params["arguments"] = arguments

        result = await self._rpc_call("tools/call", params)

        # MCP tool results come as {"content": [{"type": "text", "text": "..."}]}
        if isinstance(result, dict) and "content" in result:
            texts = []
            for item in result["content"]:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return "\n".join(texts) if texts else str(result)

        return str(result) if result is not None else ""
