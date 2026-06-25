"""Tier 3: Tool registration validation (MCP discovery + ADEPT Redis + CLI lifecycle).

Run with: make test-registration
"""

import json
import os
import subprocess

import pytest
import requests


MCP_URL = os.environ.get("MCP_URL", "http://{{NAME}}_mcp_server:{{MCP_PORT}}")
REDIS_URL = os.environ.get("{{NAME_UPPER}}_REDIS_URL", "redis://{{NAME}}_redis:6379/0")
REDIS_CONTAINER = "{{NAME}}_redis"


def _redis_get(key: str) -> str | None:
    """Get value from Redis using dual strategy (redis-py or docker exec)."""
    # Strategy 1: redis-py (if available and REDIS_URL is accessible)
    try:
        import redis
        client = redis.from_url(REDIS_URL, decode_responses=True)
        return client.get(key)
    except Exception:
        pass

    # Strategy 2: docker exec redis-cli
    try:
        result = subprocess.run(
            ["docker", "exec", REDIS_CONTAINER, "redis-cli", "GET", key],
            capture_output=True,
            text=True,
            check=True,
        )
        value = result.stdout.strip()
        return None if value == "(nil)" else value
    except Exception:
        return None


def _redis_del(key: str) -> bool:
    """Delete key from Redis using dual strategy (redis-py or docker exec)."""
    # Strategy 1: redis-py
    try:
        import redis
        client = redis.from_url(REDIS_URL, decode_responses=True)
        return client.delete(key) > 0
    except Exception:
        pass

    # Strategy 2: docker exec redis-cli
    try:
        result = subprocess.run(
            ["docker", "exec", REDIS_CONTAINER, "redis-cli", "DEL", key],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() == "1"
    except Exception:
        return False


class TestMCPToolDiscovery:
    """Tier 3A: Validate MCP tools/list returns correct tool schemas."""

    def test_tools_list_returns_tools(self):
        resp = requests.post(
            f"{MCP_URL}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "tools" in data["result"]
        assert len(data["result"]["tools"]) == {{TOOL_COUNT}}

    def test_tool_names_prefixed(self):
        resp = requests.post(
            f"{MCP_URL}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
        tools = data["result"]["tools"]
        for tool in tools:
            assert tool["name"].startswith("{{NAME}}_"), f"Tool {tool['name']} missing prefix"

    def test_tool_has_description(self):
        resp = requests.post(
            f"{MCP_URL}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
        tools = data["result"]["tools"]
        for tool in tools:
            assert tool.get("description"), f"Tool {tool['name']} missing description"

    def test_tool_has_input_schema(self):
        resp = requests.post(
            f"{MCP_URL}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
        tools = data["result"]["tools"]
        for tool in tools:
            assert "inputSchema" in tool, f"Tool {tool['name']} missing inputSchema"
            assert tool["inputSchema"]["type"] == "object"

    def test_framework_fields_not_in_schema(self):
        """Framework-injected fields must NOT appear in MCP tool schemas."""
        resp = requests.post(
            f"{MCP_URL}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
        tools = data["result"]["tools"]
        framework_fields = {"mcp_session_id", "session_id", "user_context"}
        for tool in tools:
            props = tool["inputSchema"].get("properties", {})
            for field in framework_fields:
                assert field not in props, \
                    f"Framework field '{field}' leaked into {tool['name']} schema"

    def test_tool_count(self):
        """Verify expected number of tools."""
        resp = requests.post(
            f"{MCP_URL}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
        tools = data["result"]["tools"]
        assert len(tools) == {{TOOL_COUNT}}, f"Expected {{TOOL_COUNT}} tools, got {len(tools)}"


class TestADEPTToolRegistration:
    """Tier 3B: Validate tools registered in ADEPT Redis."""

    def test_tool_exists_in_redis(self):
        """At least one tool should be registered in Redis."""
        tool_key = "tool:{{NAME}}_example_tool"
        value = _redis_get(tool_key)
        assert value is not None, f"Tool {tool_key} not found in Redis"

    def test_tool_has_protocol_mcp(self):
        """Registered tool should have protocol=mcp."""
        tool_key = "tool:{{NAME}}_example_tool"
        value = _redis_get(tool_key)
        assert value is not None
        data = json.loads(value)
        assert data["protocol"] == "mcp"

    def test_tool_has_url(self):
        """Registered tool should have an MCP URL."""
        tool_key = "tool:{{NAME}}_example_tool"
        value = _redis_get(tool_key)
        assert value is not None
        data = json.loads(value)
        assert "url" in data
        assert data["url"]

    def test_tool_url_contains_mcp_path(self):
        """Tool URL should point to /mcp endpoint."""
        tool_key = "tool:{{NAME}}_example_tool"
        value = _redis_get(tool_key)
        assert value is not None
        data = json.loads(value)
        assert "/mcp" in data["url"]

    def test_tool_has_args_schema(self):
        """Registered tool should have args_schema."""
        tool_key = "tool:{{NAME}}_example_tool"
        value = _redis_get(tool_key)
        assert value is not None
        data = json.loads(value)
        assert "args_schema" in data

    def test_args_schema_is_dict(self):
        """args_schema should be a dictionary."""
        tool_key = "tool:{{NAME}}_example_tool"
        value = _redis_get(tool_key)
        assert value is not None
        data = json.loads(value)
        assert isinstance(data["args_schema"], dict)

    def test_args_schema_has_expected_params(self):
        """args_schema should contain expected parameters."""
        tool_key = "tool:{{NAME}}_example_tool"
        value = _redis_get(tool_key)
        assert value is not None
        data = json.loads(value)
        schema = data["args_schema"]
        assert "input_file" in schema
        assert "model" in schema
        assert "batch_size" in schema


class TestCLIRegistrationLifecycle:
    """Tier 3C: Validate CLI registration, verification, and deletion."""

    def test_register_via_cli(self):
        """CLI should register tools without error."""
        result = subprocess.run(
            ["python", "scripts/register_{{NAME}}_tools.py", "--register"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Registration failed: {result.stderr}"
        assert "registered" in result.stdout.lower() or "success" in result.stdout.lower()

    def test_verify_after_register(self):
        """Tools should exist in Redis after registration."""
        # First register
        subprocess.run(
            ["python", "scripts/register_{{NAME}}_tools.py", "--register"],
            capture_output=True,
            check=True,
        )
        # Then verify
        tool_key = "tool:{{NAME}}_example_tool"
        value = _redis_get(tool_key)
        assert value is not None, f"Tool {tool_key} not found after registration"

    def test_delete_via_cli(self):
        """CLI should delete tools without error."""
        # First register
        subprocess.run(
            ["python", "scripts/register_{{NAME}}_tools.py", "--register"],
            capture_output=True,
            check=True,
        )
        # Then delete
        result = subprocess.run(
            ["python", "scripts/register_{{NAME}}_tools.py", "--delete"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Deletion failed: {result.stderr}"
        # Verify deletion
        tool_key = "tool:{{NAME}}_example_tool"
        value = _redis_get(tool_key)
        assert value is None, f"Tool {tool_key} still exists after deletion"
