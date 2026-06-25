"""STDIO E2E tests — require running ADEPT stack WITH LLM inference.

Tests spawn the Claude connector as a Docker container and exercise the full
pipeline: Claude Code CLI → STDIO → connector → gateway → orchestration →
LLM → tool execution → response back through STDIO.

Run with:
    cd examples/adept_connectors
    make test-stdio-e2e

Or directly:
    uv run pytest tests/connectors/claude/test_stdio_e2e.py -v -m stdio_e2e
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
    pytest.mark.stdio_e2e,
    pytest.mark.e2e,
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


# -- MCP STDIO Client ---------------------------------------------------------


class MCPStdioClient:
    """Minimal MCP STDIO client for E2E testing."""

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

    def recv(self, timeout: float = 60.0) -> Optional[dict]:
        try:
            line = self._queue.get(timeout=timeout)
            if line is None:
                return None
            return json.loads(line.decode().strip())
        except (queue.Empty, json.JSONDecodeError):
            return None

    def call_tool(self, name: str, arguments: dict = None, timeout: float = 60.0) -> dict:
        """Call a tool and return the result content."""
        self.send("tools/call", {"name": name, "arguments": arguments or {}})
        resp = self.recv(timeout)
        assert resp is not None, f"No response to tools/call({name})"
        assert "result" in resp, f"Tool call error for {name}: {resp}"
        return resp["result"]

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
            "clientInfo": {"name": "e2e-test", "version": "0.1.0"},
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
    pytest.skip("No API key found for E2E tests")


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


# -- Tests: Session Lifecycle --------------------------------------------------


class TestSessionLifecycle:
    """Test session creation and listing via STDIO MCP protocol."""

    def test_create_session(self, mcp_client):
        """adept_create_session should return a valid session_id."""
        result = mcp_client.call_tool("adept_create_session", timeout=30)
        content = result["content"]
        assert len(content) >= 1

        text = content[0]["text"]
        assert "session" in text.lower() or "id" in text.lower(), (
            f"Expected session info in response: {text[:200]}"
        )

    def test_list_sessions_after_create(self, mcp_client):
        """After creating a session, adept_list_sessions should show it."""
        # Create a session first
        mcp_client.call_tool("adept_create_session", timeout=30)

        # List sessions
        result = mcp_client.call_tool("adept_list_sessions", timeout=15)
        content = result["content"]
        assert len(content) >= 1

        text = content[0]["text"]
        # Should contain at least one session entry
        assert len(text) > 5


# -- Tests: Chat Round-Trip (LLM Required) ------------------------------------


class TestChatRoundTrip:
    """Test full chat round-trip requiring LLM inference."""

    def test_chat_basic_response(self, mcp_client):
        """adept_chat should return a non-empty LLM response."""
        # Create session first
        create_result = mcp_client.call_tool("adept_create_session", timeout=30)
        create_text = create_result["content"][0]["text"]

        # Extract session_id from response
        session_id = None
        try:
            data = json.loads(create_text)
            session_id = data.get("session_id") or data.get("id")
        except (json.JSONDecodeError, TypeError):
            # Try to find UUID pattern in text
            import re
            match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", create_text)
            if match:
                session_id = match.group(0)

        # Chat with or without explicit session
        args = {"message": "Reply with exactly: ADEPT_E2E_OK"}
        if session_id:
            args["session_id"] = session_id

        result = mcp_client.call_tool("adept_chat", args, timeout=90)
        content = result["content"]
        assert len(content) >= 1

        text = content[0]["text"]
        assert len(text) > 0, "Empty chat response"
        # The LLM should respond (exact wording may vary but should be non-trivial)
        assert len(text) >= 5, f"Response too short: {text}"

    def test_chat_tool_usage(self, mcp_client):
        """adept_chat with a tool-triggering prompt should invoke ADEPT tools."""
        # Create session
        create_result = mcp_client.call_tool("adept_create_session", timeout=30)
        create_text = create_result["content"][0]["text"]

        session_id = None
        try:
            data = json.loads(create_text)
            session_id = data.get("session_id") or data.get("id")
        except (json.JSONDecodeError, TypeError):
            import re
            match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", create_text)
            if match:
                session_id = match.group(0)

        args = {"message": "What tools do you have available? List them briefly."}
        if session_id:
            args["session_id"] = session_id

        result = mcp_client.call_tool("adept_chat", args, timeout=90)
        content = result["content"]
        assert len(content) >= 1

        text = content[0]["text"]
        # Agent should mention some of its tools
        assert len(text) > 50, f"Response too short for tool listing: {text[:100]}"

    def test_chat_sandbox_execution(self, mcp_client):
        """adept_chat should be able to execute code in the sandbox."""
        # Create session
        create_result = mcp_client.call_tool("adept_create_session", timeout=30)
        create_text = create_result["content"][0]["text"]

        session_id = None
        try:
            data = json.loads(create_text)
            session_id = data.get("session_id") or data.get("id")
        except (json.JSONDecodeError, TypeError):
            import re
            match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", create_text)
            if match:
                session_id = match.group(0)

        args = {"message": "Use Python to calculate 7 factorial and print the result. Just the number."}
        if session_id:
            args["session_id"] = session_id

        result = mcp_client.call_tool("adept_chat", args, timeout=120)
        content = result["content"]
        assert len(content) >= 1

        text = content[0]["text"]
        # 7! = 5040
        assert "5040" in text, f"Expected 5040 in response: {text[:300]}"


# -- Tests: Session Introspection (Call Graph) ---------------------------------


class TestSessionIntrospection:
    """Test agent introspection — get_session_history to produce call graphs."""

    def test_introspection_call_graph(self, mcp_client):
        """After tool calls, agent should introspect via get_session_history."""
        # Create session
        create_result = mcp_client.call_tool("adept_create_session", timeout=30)
        create_text = create_result["content"][0]["text"]

        session_id = None
        try:
            data = json.loads(create_text)
            session_id = data.get("session_id") or data.get("id")
        except (json.JSONDecodeError, TypeError):
            import re
            match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", create_text)
            if match:
                session_id = match.group(0)

        # First, make a tool-triggering request to build session history
        args = {"message": "List the available models."}
        if session_id:
            args["session_id"] = session_id
        mcp_client.call_tool("adept_chat", args, timeout=60)

        # Now ask the agent to introspect its own session history
        introspect_args = {
            "message": (
                "Use your get_session_history tool with include_tool_outputs=true "
                "to retrieve the call history for this session, then summarize it "
                "as a call graph showing the sequence of tool invocations."
            ),
        }
        if session_id:
            introspect_args["session_id"] = session_id

        result = mcp_client.call_tool("adept_chat", introspect_args, timeout=120)
        content = result["content"]
        assert len(content) >= 1

        text = content[0]["text"]
        # The response should reference session history or tool calls
        assert len(text) > 100, f"Introspection response too short: {text[:200]}"
        # Should contain evidence of call graph / tool invocation data
        indicators = ["tool", "call", "history", "session", "graph", "sequence", "invocation"]
        found = [ind for ind in indicators if ind.lower() in text.lower()]
        assert len(found) >= 2, (
            f"Expected introspection content with tool/call/history references, "
            f"got: {text[:300]}"
        )
