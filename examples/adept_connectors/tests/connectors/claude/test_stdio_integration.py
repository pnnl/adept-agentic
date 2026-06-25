"""STDIO integration tests — require running ADEPT stack (no LLM inference).

Tests spawn the Claude connector as a Docker container (same pattern as .mcp.json)
and exercise the MCP JSON-RPC protocol end-to-end through the ADEPT gateway.

Run with:
    cd examples/adept_connectors
    make test-stdio-integration

Or directly:
    uv run pytest tests/connectors/claude/test_stdio_integration.py -v -m stdio_integration
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import queue
from pathlib import Path
from typing import Any, Optional

import pytest


pytestmark = [
    pytest.mark.stdio_integration,
    pytest.mark.integration,
]

CONNECTOR_SRC = Path(__file__).resolve().parents[3] / "src"
PROJECT_ROOT = CONNECTOR_SRC.parents[2]

# Pre-flight checks
HAS_DOCKER = False
HAS_ADEPT_NETWORK = False
HAS_DEPS_BASE_IMAGE = False

try:
    r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
    HAS_DOCKER = r.returncode == 0
except (FileNotFoundError, subprocess.TimeoutExpired):
    pass

if HAS_DOCKER:
    r = subprocess.run(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        capture_output=True, text=True, timeout=5,
    )
    HAS_ADEPT_NETWORK = "adept_application_network" in r.stdout

    r = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}", "agentic-framework-deps-base"],
        capture_output=True, text=True, timeout=5,
    )
    HAS_DEPS_BASE_IMAGE = "agentic-framework-deps-base" in r.stdout

pytestmark.append(
    pytest.mark.skipif(
        not (HAS_DOCKER and HAS_ADEPT_NETWORK and HAS_DEPS_BASE_IMAGE),
        reason="Requires Docker, adept_application_network, and deps-base image",
    )
)


# -- MCP STDIO Client Fixture -------------------------------------------------


class MCPStdioClient:
    """Minimal MCP STDIO client for testing."""

    def __init__(self, proc: subprocess.Popen):
        self._proc = proc
        self._queue: queue.Queue = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._next_id = 1

    def _read_loop(self):
        for line in self._proc.stdout:
            self._queue.put(line)
        self._queue.put(None)

    def send(self, method: str, params: dict = None, *, is_notification: bool = False) -> Optional[int]:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        else:
            msg["params"] = {}

        msg_id = None
        if not is_notification:
            msg_id = self._next_id
            msg["id"] = msg_id
            self._next_id += 1

        data = json.dumps(msg) + "\n"
        self._proc.stdin.write(data.encode())
        self._proc.stdin.flush()
        return msg_id

    def recv(self, timeout: float = 15.0) -> Optional[dict]:
        try:
            line = self._queue.get(timeout=timeout)
            if line is None:
                return None
            return json.loads(line.decode().strip())
        except (queue.Empty, json.JSONDecodeError):
            return None

    def close(self):
        try:
            self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()

    def handshake(self) -> dict:
        """Perform full MCP initialize + notifications/initialized handshake."""
        self.send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "0.1.0"},
        })
        resp = self.recv(10)
        assert resp is not None, "No initialize response"
        assert "result" in resp, f"Initialize failed: {resp}"

        self.send("notifications/initialized", {}, is_notification=True)
        time.sleep(0.3)
        return resp["result"]


@pytest.fixture(scope="module")
def api_key():
    """Discover API key from credentials directory."""
    cred_paths = [
        PROJECT_ROOT / "deployment/local/docker-compose/.env-keycloak-credentials-dir/OPENWEBUI_SERVICE_API_KEY",
        PROJECT_ROOT / ".env-keycloak-credentials-dir/OPENWEBUI_SERVICE_API_KEY",
    ]
    for p in cred_paths:
        if p.exists():
            return p.read_text().strip()
    key = os.environ.get("ADEPT_TEST_API_KEY")
    if key:
        return key
    pytest.skip("No API key found for integration tests")


@pytest.fixture
def mcp_client(api_key) -> MCPStdioClient:
    """Spawn a Docker container running the Claude connector and return an MCP client."""
    cmd = [
        "docker", "run", "--rm", "-i",
        "--network=adept_application_network",
        "-v", f"{CONNECTOR_SRC}:/app/connector_src:ro",
        "-e", "PYTHONPATH=/app/connector_src",
        "-e", "ADEPT_BASE_URL=http://agent_gateway:8081/v1",
        "-e", "ADEPT_AUTH_METHOD=api_key",
        "-e", f"ADEPT_API_KEY={api_key}",
        "-e", "ADEPT_VERIFY_SSL=false",
        "agentic-framework-deps-base",
        "/app/.venv/bin/python", "-m", "adept_connectors.connectors.claude",
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    client = MCPStdioClient(proc)
    client.handshake()
    yield client
    client.close()


# -- Tests: tools/list ---------------------------------------------------------


class TestToolsList:
    """Validate tools/list returns all expected ADEPT tools."""

    def test_tools_list_returns_12_tools(self, mcp_client):
        """tools/list should return exactly 12 registered tools."""
        mcp_client.send("tools/list")
        resp = mcp_client.recv(10)

        assert resp is not None, "No response to tools/list"
        assert "result" in resp, f"tools/list error: {resp}"
        tools = resp["result"]["tools"]
        assert len(tools) == 12, f"Expected 12 tools, got {len(tools)}: {[t['name'] for t in tools]}"

    def test_tools_list_contains_expected_names(self, mcp_client):
        """tools/list should include all core ADEPT tool names."""
        mcp_client.send("tools/list")
        resp = mcp_client.recv(10)

        tools = resp["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        expected = {
            "adept_chat",
            "adept_agui_run",
            "adept_upload_file",
            "adept_list_files",
            "adept_list_mcp_resources",
            "adept_get_image",
            "adept_download_artifact",
            "adept_create_session",
            "adept_list_sessions",
            "adept_list_tools",
            "adept_call_tool",
            "adept_list_models",
        }
        assert expected == tool_names

    def test_tools_have_input_schema(self, mcp_client):
        """Each tool should declare an inputSchema for LLM parameter binding."""
        mcp_client.send("tools/list")
        resp = mcp_client.recv(10)

        tools = resp["result"]["tools"]
        for tool in tools:
            assert "inputSchema" in tool, f"Tool {tool['name']} missing inputSchema"
            schema = tool["inputSchema"]
            assert schema.get("type") == "object", f"Tool {tool['name']} schema type is not object"


# -- Tests: tools/call (no LLM needed) ----------------------------------------


class TestToolsCallNoLLM:
    """Test tool invocations that don't require LLM inference."""

    def test_adept_list_models(self, mcp_client):
        """adept_list_models should return available ADEPT models."""
        mcp_client.send("tools/call", {"name": "adept_list_models", "arguments": {}})
        resp = mcp_client.recv(20)

        assert resp is not None, "No response to adept_list_models"
        assert "result" in resp, f"Tool call error: {resp}"
        content = resp["result"]["content"]
        assert len(content) >= 1

        text = content[0]["text"]
        models = json.loads(text)
        assert isinstance(models, list)
        assert len(models) >= 1

        model_ids = [m["id"] for m in models]
        assert any("scientific-agent" in mid for mid in model_ids), (
            f"Expected scientific-agent model, got: {model_ids}"
        )

    def test_adept_list_tools(self, mcp_client):
        """adept_list_tools should return external MCP tools registered with ADEPT."""
        mcp_client.send("tools/call", {"name": "adept_list_tools", "arguments": {}})
        resp = mcp_client.recv(20)

        assert resp is not None, "No response to adept_list_tools"
        assert "result" in resp, f"Tool call error: {resp}"
        content = resp["result"]["content"]
        assert len(content) >= 1

        text = content[0]["text"]
        # Should return a list or description of external tools
        assert len(text) > 10, f"Response too short: {text}"

    def test_adept_list_sessions(self, mcp_client):
        """adept_list_sessions should return without error (may be empty)."""
        mcp_client.send("tools/call", {"name": "adept_list_sessions", "arguments": {}})
        resp = mcp_client.recv(15)

        assert resp is not None, "No response to adept_list_sessions"
        assert "result" in resp, f"Tool call error: {resp}"
        content = resp["result"]["content"]
        assert len(content) >= 1
        # Should be valid text (empty list is fine)
        assert content[0]["type"] == "text"

    def test_adept_list_files(self, mcp_client):
        """adept_list_files should return without error."""
        mcp_client.send("tools/call", {"name": "adept_list_files", "arguments": {}})
        resp = mcp_client.recv(15)

        assert resp is not None, "No response to adept_list_files"
        assert "result" in resp, f"Tool call error: {resp}"
        content = resp["result"]["content"]
        assert len(content) >= 1

    def test_invalid_tool_name_returns_error(self, mcp_client):
        """Calling a non-existent tool should return an error response."""
        mcp_client.send("tools/call", {"name": "nonexistent_tool", "arguments": {}})
        resp = mcp_client.recv(10)

        assert resp is not None
        # Should be an error (either JSON-RPC error or MCP isError content)
        assert "error" in resp or resp.get("result", {}).get("isError"), (
            f"Expected error for invalid tool, got: {resp}"
        )
