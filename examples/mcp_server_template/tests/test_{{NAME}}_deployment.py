"""Tier 2: Integration tests requiring running containers.

Run with: make test-integration
"""

import json
import os

import pytest
import requests


MCP_URL = os.environ.get("MCP_URL", "http://{{NAME}}_mcp_server:{{MCP_PORT}}")
PROXY_URL = os.environ.get("{{NAME_UPPER}}_PROXY_URL", "http://{{NAME}}_nginx_proxy:80")


class TestMCPServerHealth:
    """Verify MCP server is running and healthy."""

    def test_root_endpoint(self):
        resp = requests.get(f"{MCP_URL}/", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert "{{DISPLAY_NAME}}" in data["name"]

    def test_health_endpoint(self):
        resp = requests.get(f"{MCP_URL}/health", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "mcp_tools" in data
        assert isinstance(data["mcp_tools"], list)
        assert len(data["mcp_tools"]) >= 1

    def test_health_contains_expected_tools(self):
        resp = requests.get(f"{MCP_URL}/health", timeout=10)
        data = resp.json()
        tool_names = data["mcp_tools"]
        assert any("example" in t for t in tool_names), f"No example tool in {tool_names}"

    def test_mcp_endpoint_exists(self):
        """POST to /mcp should return a valid MCP response (not 404)."""
        resp = requests.post(
            f"{MCP_URL}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        # MCP endpoint should respond (200 or valid error, not 404)
        assert resp.status_code != 404


class TestNginxProxy:
    """Verify nginx proxy is forwarding correctly."""

    def test_proxy_health(self):
        resp = requests.get(f"{PROXY_URL}/health", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_proxy_mcp_forwarding(self):
        """Proxy should forward /mcp to the MCP server."""
        resp = requests.post(
            f"{PROXY_URL}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert resp.status_code != 404
