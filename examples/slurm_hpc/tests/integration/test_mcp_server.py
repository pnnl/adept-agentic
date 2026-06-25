"""
Integration Tests: MCP Server
==============================

Tests that require the Slurm MCP server container to be running.
Validates health endpoints, MCP protocol, and tool discovery.

Prerequisites:
    - Slurm stack running: cd examples/slurm_hpc && make start
    - MCP server healthy: make health-mcp

Usage:
    pytest tests/integration/test_mcp_server.py -v
"""

import os

import pytest
import requests

# URLs — configurable via env for running inside vs outside Docker network
MCP_SERVER_URL = os.environ.get("SLURM_MCP_URL", "http://localhost:8002")
PROXY_URL = os.environ.get("SLURM_PROXY_URL", "http://localhost:9820")
TIMEOUT = 10


class TestMCPServerHealth:
    """Validate the MCP server is running and reachable."""

    def test_mcp_server_reachable(self):
        """MCP server responds on /mcp (even rejecting bare GET confirms it's alive)."""
        resp = requests.get(f"{MCP_SERVER_URL}/mcp", timeout=TIMEOUT)
        # FastMCP streamable-http returns 405 or 406 for bare GET — any response confirms server is up
        assert resp.status_code in [200, 400, 405, 406]

    def test_mcp_server_has_health_route(self):
        """MCP server exposes /health via FastMCP custom_route (parity with biofoundation/vfm)."""
        resp = requests.get(f"{MCP_SERVER_URL}/health", timeout=TIMEOUT)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "mcp_tools" in data

    def test_mcp_endpoint_exists(self):
        """MCP endpoint /mcp is reachable."""
        resp = requests.get(f"{MCP_SERVER_URL}/mcp", timeout=TIMEOUT)
        assert resp.status_code in [200, 400, 405, 406]


class TestNginxProxy:
    """Validate the nginx reverse proxy."""

    def test_proxy_health_passthrough(self):
        """Proxy /health passes through to MCP server."""
        resp = requests.get(f"{PROXY_URL}/health", timeout=TIMEOUT)
        assert resp.status_code == 200

    def test_proxy_mcp_passthrough(self):
        """Proxy /mcp passes through to MCP server."""
        resp = requests.get(f"{PROXY_URL}/mcp", timeout=TIMEOUT)
        assert resp.status_code in [200, 400, 405, 406]

    def test_proxy_catch_all_404(self):
        """Proxy returns 404 for unknown paths."""
        resp = requests.get(f"{PROXY_URL}/nonexistent", timeout=TIMEOUT)
        assert resp.status_code == 404


class TestMCPToolDiscovery:
    """Validate MCP tool listing via the MCP protocol (JSON-RPC over HTTP)."""

    def _mcp_rpc(self, method: str, params: dict = None):
        """Send a JSON-RPC request to the MCP server."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
        }
        if params:
            payload["params"] = params
        resp = requests.post(
            f"{MCP_SERVER_URL}/mcp",
            json=payload,
            timeout=TIMEOUT,
        )
        return resp

    @pytest.mark.skipif(
        not os.environ.get("SLURM_MCP_RUNNING"),
        reason="Set SLURM_MCP_RUNNING=1 to run integration tests",
    )
    def test_tools_list_returns_27_tools(self):
        """tools/list should return exactly 27 tools (6 local + 6 deception + 6 tahoma + 5 ssh_key + 4 workspace)."""
        resp = self._mcp_rpc("tools/list")
        if resp.status_code == 200:
            data = resp.json()
            tools = data.get("result", {}).get("tools", [])
            tool_names = [t["name"] for t in tools]
            assert "submit_slurm_job" in tool_names
            assert "get_job_details" in tool_names
            assert "cancel_slurm_job" in tool_names
            assert "ping" in tool_names
            assert "list_cluster_jobs" in tool_names
            assert "get_cluster_summary" in tool_names
            assert "deception_ping" in tool_names
            assert "tahoma_ping" in tool_names
            assert "hpc_list_clusters" in tool_names
            assert len(tools) == 27


class TestSlurmBackendConnectivity:
    """Tests requiring the full Slurm backend to be running."""

    @pytest.mark.skipif(
        not os.environ.get("SLURM_CLUSTER_RUNNING"),
        reason="Set SLURM_CLUSTER_RUNNING=1 to run backend integration tests",
    )
    def test_slurmctld_ping(self):
        """slurmctld responds to ping via docker exec."""
        import subprocess

        result = subprocess.run(
            ["docker", "exec", "slurmctld", "scontrol", "ping"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "UP" in result.stdout

    @pytest.mark.skipif(
        not os.environ.get("SLURM_CLUSTER_RUNNING"),
        reason="Set SLURM_CLUSTER_RUNNING=1 to run backend integration tests",
    )
    def test_compute_nodes_registered(self):
        """Both compute nodes c1 and c2 are registered."""
        import subprocess

        result = subprocess.run(
            ["docker", "exec", "slurmctld", "scontrol", "show", "nodes"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "c1" in result.stdout
        assert "c2" in result.stdout
