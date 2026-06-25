"""Tests for MCPProxyClient — JSON-RPC proxy."""

import json

import httpx
import pytest
import respx

from adept_connectors.core.auth import AuthManager
from adept_connectors.core.clients.mcp_proxy import MCPProxyClient
from adept_connectors.core.config import AdeptConnectorConfig


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
    monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
    monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")
    monkeypatch.setenv("ADEPT_MCP_SERVER_URL", "http://adept-test:8080/mcp")
    return AdeptConnectorConfig()


@pytest.fixture
def client(config):
    return MCPProxyClient(config, AuthManager(config))


class TestMCPProxyClient:

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_tools(self, client, config):
        rpc_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "websearch", "description": "Search the web", "inputSchema": {}},
                    {"name": "blast_search", "description": "BLAST query", "inputSchema": {}},
                ]
            },
        }
        respx.post(config.mcp_server_url).mock(
            return_value=httpx.Response(200, json=rpc_response)
        )

        tools = await client.list_tools()
        assert len(tools) == 2
        assert tools[0]["name"] == "websearch"

    @pytest.mark.asyncio
    @respx.mock
    async def test_call_tool(self, client, config):
        rpc_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {"type": "text", "text": "Found 42 results for protein query"}
                ]
            },
        }
        route = respx.post(config.mcp_server_url).mock(
            return_value=httpx.Response(200, json=rpc_response)
        )

        result = await client.call_tool("websearch", {"query": "protein"})
        assert result == "Found 42 results for protein query"

        # Verify JSON-RPC payload
        sent = json.loads(route.calls[0].request.content)
        assert sent["method"] == "tools/call"
        assert sent["params"]["name"] == "websearch"
        assert sent["params"]["arguments"] == {"query": "protein"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_rpc_error_raises(self, client, config):
        rpc_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid request"},
        }
        respx.post(config.mcp_server_url).mock(
            return_value=httpx.Response(200, json=rpc_response)
        )

        with pytest.raises(RuntimeError, match="Invalid request"):
            await client.list_tools()

    @pytest.mark.asyncio
    @respx.mock
    async def test_call_tool_no_arguments(self, client, config):
        rpc_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "pong"}]},
        }
        route = respx.post(config.mcp_server_url).mock(
            return_value=httpx.Response(200, json=rpc_response)
        )

        result = await client.call_tool("ping")
        assert result == "pong"
        sent = json.loads(route.calls[0].request.content)
        assert "arguments" not in sent["params"]

    def test_derive_mcp_url_with_port(self):
        url = MCPProxyClient._derive_mcp_url("http://rc-server:8083/v1")
        assert url == "http://rc-server:8083/mcp"

    def test_derive_mcp_url_https_no_port(self):
        """HTTPS without explicit port must NOT append :80 (causes SSL mismatch)."""
        url = MCPProxyClient._derive_mcp_url("https://your-adept-host.example.com/v1")
        assert url == "https://your-adept-host.example.com/mcp"
        assert ":80" not in url

    def test_derive_mcp_url_http_no_port(self):
        url = MCPProxyClient._derive_mcp_url("http://rc-server/v1")
        assert url == "http://rc-server/mcp"

    def test_derive_mcp_url_no_trailing_slash(self):
        """Trailing slash causes redirect loop (nginx 301 <-> FastAPI 307)."""
        url = MCPProxyClient._derive_mcp_url("https://example.com/v1")
        assert not url.endswith("/")
        url2 = MCPProxyClient._derive_mcp_url("http://localhost:8083/v1")
        assert not url2.endswith("/")

    def test_client_source_header(self, config):
        """Verify custom client_source is stored."""
        client = MCPProxyClient(
            config, AuthManager(config), client_source="my-connector"
        )
        assert client._client_source == "my-connector"
