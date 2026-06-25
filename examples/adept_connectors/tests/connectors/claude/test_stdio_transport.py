"""STDIO transport and Docker container launch tests for Claude Code CLI.

Tests validate:
1. MCP server starts in STDIO mode and responds to JSON-RPC initialize
2. Doctor command exits with expected checks
3. Docker container launch pattern (the .mcp.json command) works end-to-end

Run with:
    cd examples/adept_connectors
    uv run pytest tests/connectors/claude/test_stdio_transport.py -v

For Docker-based tests (requires running ADEPT stack):
    uv run pytest tests/connectors/claude/test_stdio_transport.py -v -m stdio_docker
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# -- Markers ------------------------------------------------------------------

pytestmark = [pytest.mark.unit]

CONNECTOR_SRC = Path(__file__).resolve().parents[3] / "src"
CONNECTOR_MODULE = "adept_connectors.connectors.claude"

# Docker tests need a running ADEPT stack
HAS_DOCKER = bool(
    subprocess.run(
        ["docker", "info"], capture_output=True, timeout=5
    ).returncode == 0
    if subprocess.run(["which", "docker"], capture_output=True).returncode == 0
    else False
)

HAS_ADEPT_NETWORK = False
if HAS_DOCKER:
    result = subprocess.run(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        capture_output=True, text=True, timeout=5,
    )
    HAS_ADEPT_NETWORK = "adept_application_network" in result.stdout

HAS_DEPS_BASE_IMAGE = False
if HAS_DOCKER:
    result = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}", "agentic-framework-deps-base"],
        capture_output=True, text=True, timeout=5,
    )
    HAS_DEPS_BASE_IMAGE = "agentic-framework-deps-base" in result.stdout


# -- Helpers ------------------------------------------------------------------


def _build_initialize_request() -> bytes:
    """Build a JSON-RPC initialize request per MCP spec."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.1.0"},
        },
    }
    body = json.dumps(request)
    return body.encode() + b"\n"


def _build_tools_list_request() -> bytes:
    """Build a JSON-RPC tools/list request."""
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }
    body = json.dumps(request)
    return body.encode() + b"\n"


def _parse_jsonrpc_response(output: str) -> list[dict]:
    """Parse JSON-RPC responses from raw STDIO output."""
    responses = []
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if "jsonrpc" in obj:
                responses.append(obj)
        except json.JSONDecodeError:
            continue
    return responses


# -- Unit Tests: CLI argument parsing ------------------------------------------


class TestCLIArgumentParsing:
    """Test that CLI entry point handles arguments correctly."""

    def test_default_mode_is_stdio(self):
        """Default (no args) should invoke run_stdio."""
        with patch("adept_connectors.connectors.claude.cli.run_stdio") as mock_stdio:
            from adept_connectors.connectors.claude.cli import main
            with patch("sys.argv", ["prog"]):
                main()
            mock_stdio.assert_called_once()

    def test_http_flag_detected_in_sys_argv(self):
        """--http in sys.argv should route to run_http (after argparse tolerates it)."""
        # cli.py checks `"--http" in sys.argv` AFTER parse_args(). Since argparse
        # doesn't know --http, it raises SystemExit(2). This test validates the
        # detection logic by patching parse_args to return a no-command namespace.
        import argparse

        fake_ns = argparse.Namespace(command=None)
        with patch("argparse.ArgumentParser.parse_args", return_value=fake_ns):
            with patch("adept_connectors.connectors.claude.cli.run_http") as mock_http:
                from adept_connectors.connectors.claude.cli import main
                with patch("sys.argv", ["prog", "--http"]):
                    main()
                mock_http.assert_called_once()

    def test_doctor_subcommand(self):
        """doctor subcommand should invoke _cmd_doctor."""
        with patch("adept_connectors.connectors.claude.cli._cmd_doctor") as mock_doc:
            from adept_connectors.connectors.claude.cli import main
            with patch("sys.argv", ["prog", "doctor"]):
                main()
            mock_doc.assert_called_once()


# -- Unit Tests: Server creation -----------------------------------------------


class TestServerCreation:
    """Test that the MCP server creates correctly with expected tools."""

    def test_create_server_returns_fastmcp_instance(self):
        """create_server() should return a FastMCP server."""
        from adept_connectors.connectors.claude.server import create_server

        server = create_server()
        assert server is not None
        assert hasattr(server, "run")

    def test_server_has_all_expected_tools(self):
        """Server should register all 12 ADEPT tools."""
        from adept_connectors.connectors.claude.server import mcp

        tools = {t.name for t in mcp._tool_manager._tools.values()}
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
        assert expected == tools


# -- STDIO Transport Tests (subprocess-based) ----------------------------------


class TestSTDIOTransport:
    """Test MCP server STDIO transport via subprocess.

    These tests spawn the connector as a subprocess and communicate
    via stdin/stdout using the MCP JSON-RPC protocol.
    """

    @pytest.fixture
    def stdio_env(self, monkeypatch):
        """Env vars for a test STDIO process (auth will fail but init should succeed)."""
        env = os.environ.copy()
        env["ADEPT_AUTH_METHOD"] = "api_key"
        env["ADEPT_API_KEY"] = "sk-test-stdio-transport"
        env["ADEPT_BASE_URL"] = "http://localhost:9999/v1"
        env["ADEPT_VERIFY_SSL"] = "false"
        env["PYTHONPATH"] = str(CONNECTOR_SRC)
        return env

    def test_stdio_process_starts_and_accepts_initialize(self, stdio_env):
        """MCP server should start via python -m and respond to initialize."""
        proc = subprocess.Popen(
            [sys.executable, "-m", CONNECTOR_MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=stdio_env,
            cwd=str(CONNECTOR_SRC.parent),
        )
        try:
            stdin_data = _build_initialize_request()
            stdout, stderr = proc.communicate(input=stdin_data, timeout=10)

            output = stdout.decode("utf-8", errors="replace")
            responses = _parse_jsonrpc_response(output)

            assert len(responses) >= 1, (
                f"Expected at least 1 JSON-RPC response, got {len(responses)}. "
                f"stdout: {output[:500]}, stderr: {stderr.decode()[:500]}"
            )

            init_resp = responses[0]
            assert init_resp.get("id") == 1
            assert "result" in init_resp, f"Expected result in response: {init_resp}"
            assert "serverInfo" in init_resp["result"]
            assert "capabilities" in init_resp["result"]
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("STDIO process timed out waiting for initialize response")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_stdio_server_info_fields(self, stdio_env):
        """Server info should include name and version."""
        proc = subprocess.Popen(
            [sys.executable, "-m", CONNECTOR_MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=stdio_env,
            cwd=str(CONNECTOR_SRC.parent),
        )
        try:
            stdin_data = _build_initialize_request()
            stdout, _ = proc.communicate(input=stdin_data, timeout=10)

            responses = _parse_jsonrpc_response(stdout.decode())
            assert len(responses) >= 1
            server_info = responses[0]["result"]["serverInfo"]
            assert "name" in server_info
            assert "version" in server_info
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Timeout")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_stdio_capabilities_include_tools(self, stdio_env):
        """Server capabilities should declare tools support."""
        proc = subprocess.Popen(
            [sys.executable, "-m", CONNECTOR_MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=stdio_env,
            cwd=str(CONNECTOR_SRC.parent),
        )
        try:
            stdin_data = _build_initialize_request()
            stdout, _ = proc.communicate(input=stdin_data, timeout=10)

            responses = _parse_jsonrpc_response(stdout.decode())
            assert len(responses) >= 1
            capabilities = responses[0]["result"]["capabilities"]
            assert "tools" in capabilities
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Timeout")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_stdio_exits_cleanly_on_stdin_close(self, stdio_env):
        """Server should exit cleanly when stdin is closed (client disconnect)."""
        proc = subprocess.Popen(
            [sys.executable, "-m", CONNECTOR_MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=stdio_env,
            cwd=str(CONNECTOR_SRC.parent),
        )
        try:
            # Close stdin immediately without sending anything
            proc.stdin.close()
            proc.wait(timeout=10)
            # Should exit without error (0) or with a clean EOF exit
            assert proc.returncode in (0, 1), f"Unexpected exit code: {proc.returncode}"
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Process did not exit after stdin close")


# -- Doctor Command Tests ------------------------------------------------------


class TestDoctorCommand:
    """Test the doctor diagnostic subcommand."""

    def test_doctor_exits_with_failure_when_no_adept(self, monkeypatch):
        """Doctor should exit non-zero when ADEPT is unreachable."""
        env = os.environ.copy()
        env["ADEPT_AUTH_METHOD"] = "api_key"
        env["ADEPT_API_KEY"] = "sk-test-doctor"
        env["ADEPT_BASE_URL"] = "http://localhost:1/v1"
        env["ADEPT_VERIFY_SSL"] = "false"
        env["PYTHONPATH"] = str(CONNECTOR_SRC)

        result = subprocess.run(
            [sys.executable, "-m", CONNECTOR_MODULE, "doctor"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(CONNECTOR_SRC.parent),
            timeout=30,
        )
        # Doctor should fail (non-zero) since ADEPT is not at localhost:1
        assert result.returncode != 0
        assert "FAIL" in result.stdout or "FAIL" in result.stderr

    def test_doctor_outputs_check_structure(self, monkeypatch):
        """Doctor output should contain structured check labels."""
        env = os.environ.copy()
        env["ADEPT_AUTH_METHOD"] = "api_key"
        env["ADEPT_API_KEY"] = "sk-test-doctor"
        env["ADEPT_BASE_URL"] = "http://localhost:1/v1"
        env["ADEPT_VERIFY_SSL"] = "false"
        env["PYTHONPATH"] = str(CONNECTOR_SRC)

        result = subprocess.run(
            [sys.executable, "-m", CONNECTOR_MODULE, "doctor"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(CONNECTOR_SRC.parent),
            timeout=30,
        )
        output = result.stdout
        # Should show configuration check (first check always passes if env is set)
        assert "configuration" in output.lower() or "PASS" in output
        # Should show a Result line with pass/total format
        assert "Result:" in output or "checks passed" in output.lower()

    def test_doctor_config_check_passes_with_valid_env(self, monkeypatch):
        """Doctor config check should pass when env vars are set correctly."""
        env = os.environ.copy()
        env["ADEPT_AUTH_METHOD"] = "api_key"
        env["ADEPT_API_KEY"] = "sk-test-doctor-config"
        env["ADEPT_BASE_URL"] = "http://localhost:9999/v1"
        env["ADEPT_VERIFY_SSL"] = "false"
        env["PYTHONPATH"] = str(CONNECTOR_SRC)

        result = subprocess.run(
            [sys.executable, "-m", CONNECTOR_MODULE, "doctor"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(CONNECTOR_SRC.parent),
            timeout=30,
        )
        # First check (config) should pass
        assert "[PASS] Configuration loaded" in result.stdout


# -- Docker Container Launch Tests ---------------------------------------------


@pytest.mark.stdio_docker
@pytest.mark.skipif(not HAS_DOCKER, reason="Docker not available")
@pytest.mark.skipif(not HAS_DEPS_BASE_IMAGE, reason="agentic-framework-deps-base image not built")
@pytest.mark.skipif(not HAS_ADEPT_NETWORK, reason="adept_application_network not found")
class TestDockerContainerLaunch:
    """Test the Docker container launch pattern used by .mcp.json.

    These tests validate that the exact command pattern from .mcp.json works:
      docker run --rm -i --network=adept_application_network ...
    """

    @pytest.fixture
    def connector_src_path(self):
        return str(CONNECTOR_SRC)

    @pytest.fixture
    def docker_base_cmd(self, connector_src_path):
        """Base docker command matching .mcp.json pattern."""
        return [
            "docker", "run", "--rm", "-i",
            "--network=adept_application_network",
            "-v", f"{connector_src_path}:/app/connector_src:ro",
            "-e", "PYTHONPATH=/app/connector_src",
            "-e", "ADEPT_BASE_URL=http://agent_gateway:8081/v1",
            "-e", "ADEPT_AUTH_METHOD=api_key",
            "-e", "ADEPT_VERIFY_SSL=false",
        ]

    @pytest.fixture
    def api_key(self):
        """Discover API key from credentials directory."""
        cred_paths = [
            Path("deployment/local/docker-compose/.env-keycloak-credentials-dir/OPENWEBUI_SERVICE_API_KEY"),
            Path(".env-keycloak-credentials-dir/OPENWEBUI_SERVICE_API_KEY"),
        ]
        # Try from project root (walk up from test file)
        project_root = CONNECTOR_SRC.parents[2]
        for p in cred_paths:
            full = project_root / p
            if full.exists():
                return full.read_text().strip()
        # Fallback to env
        return os.environ.get("ADEPT_TEST_API_KEY", "sk-test-docker")

    def test_container_starts_and_responds_to_initialize(self, docker_base_cmd, api_key):
        """Docker container should start and respond to MCP initialize."""
        cmd = docker_base_cmd + [
            "-e", f"ADEPT_API_KEY={api_key}",
            "agentic-framework-deps-base",
            "/app/.venv/bin/python", "-m", "adept_connectors.connectors.claude",
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdin_data = _build_initialize_request()
            stdout, stderr = proc.communicate(input=stdin_data, timeout=30)

            output = stdout.decode("utf-8", errors="replace")
            responses = _parse_jsonrpc_response(output)

            assert len(responses) >= 1, (
                f"No JSON-RPC response from container. "
                f"stdout: {output[:500]}, stderr: {stderr.decode()[:500]}"
            )
            assert responses[0].get("id") == 1
            assert "result" in responses[0]
            assert "serverInfo" in responses[0]["result"]
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Docker container timed out")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_container_doctor_passes(self, docker_base_cmd, api_key):
        """Docker container doctor command should pass connectivity checks."""
        cmd = docker_base_cmd + [
            "-e", f"ADEPT_API_KEY={api_key}",
            "agentic-framework-deps-base",
            "/app/.venv/bin/python", "-m", "adept_connectors.connectors.claude", "doctor",
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )

        # Doctor should pass at least config + auth + connectivity (3/7 minimum)
        assert "checks passed" in result.stdout.lower() or "Result:" in result.stdout
        # Count passes
        pass_count = result.stdout.count("[PASS]")
        assert pass_count >= 3, (
            f"Expected at least 3 checks to pass, got {pass_count}. "
            f"Output: {result.stdout}"
        )

    def test_container_network_resolves_internal_dns(self, docker_base_cmd, api_key):
        """Container on adept_application_network should resolve internal service DNS."""
        cmd = [
            "docker", "run", "--rm",
            "--network=adept_application_network",
            "agentic-framework-deps-base",
            "/app/.venv/bin/python", "-c",
            "import socket; print(socket.gethostbyname('agent_gateway'))",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, f"DNS resolution failed: {result.stderr}"
        # Should resolve to an IP address
        ip = result.stdout.strip()
        assert ip.count(".") == 3, f"Expected IP address, got: {ip}"

    def test_container_can_reach_agent_gateway(self, docker_base_cmd, api_key):
        """Container should be able to reach agent_gateway HTTP port."""
        cmd = [
            "docker", "run", "--rm",
            "--network=adept_application_network",
            "agentic-framework-deps-base",
            "/app/.venv/bin/python", "-c",
            "import httpx; r = httpx.get('http://agent_gateway:8081/v1/responses/models', timeout=10); print(r.status_code)",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"Gateway unreachable: {result.stderr}"
        # 200 = success, 401 = auth required (endpoint exists and is reachable)
        status = result.stdout.strip()
        assert status in ("200", "401"), f"Expected 200 or 401, got: {status}"
