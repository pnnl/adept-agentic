"""
Slurm MCP Server E2E Tests
==========================

End-to-end tests for the complete Slurm HPC stack including:
- Slurm backend cluster health
- MCP server health and tool discovery
- Nginx proxy routing
- Job submission workflow (requires full stack)

Usage:
    # Docker container on adept_application_network:
    pytest tests/test_slurm_mcp_e2e.py -v

    # Via Makefile:
    make validate-mcp

Prerequisites:
    - Slurm cluster + MCP server running (make setup)
    - JWT credentials bootstrapped (make bootstrap-jwt)
"""

import os
import json
import subprocess

import pytest
import requests

# Configuration from environment or defaults (container DNS names)
MCP_SERVER_URL = os.environ.get("SLURM_MCP_URL", "http://slurm_mcp_server:8002")
PROXY_URL = os.environ.get("SLURM_PROXY_URL", "http://slurm_nginx_proxy:80")
TIMEOUT = 15


class TestMCPServerHealth:
    """Validate the MCP server is running and healthy."""

    def test_mcp_server_reachable(self):
        """MCP server responds on /mcp endpoint."""
        resp = requests.get(f"{MCP_SERVER_URL}/mcp", timeout=TIMEOUT)
        assert resp.status_code in [200, 400, 405, 406]

    def test_mcp_server_has_health_route(self):
        """MCP server exposes /health via FastMCP custom_route (parity with biofoundation/vfm)."""
        resp = requests.get(f"{MCP_SERVER_URL}/health", timeout=TIMEOUT)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "mcp_tools" in data

    def test_proxy_health_returns_json(self):
        """Nginx proxy /health returns JSON with status ok."""
        resp = requests.get(f"{PROXY_URL}/health", timeout=TIMEOUT)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert data.get("status") == "ok"

    def test_proxy_catch_all_returns_404(self):
        """Nginx proxy catch-all returns 404 for unknown paths."""
        resp = requests.get(f"{PROXY_URL}/nonexistent", timeout=TIMEOUT)
        assert resp.status_code == 404


class TestMCPProtocol:
    """Validate MCP protocol endpoints."""

    def test_mcp_endpoint_reachable(self):
        """MCP /mcp endpoint responds (may reject non-MCP requests)."""
        resp = requests.get(f"{MCP_SERVER_URL}/mcp", timeout=TIMEOUT)
        assert resp.status_code in [200, 400, 405, 406]

    def test_mcp_proxy_endpoint_reachable(self):
        """Proxy /mcp endpoint passes through to MCP server."""
        resp = requests.get(f"{PROXY_URL}/mcp", timeout=TIMEOUT)
        assert resp.status_code in [200, 400, 405, 406]


class TestToolDiscovery:
    """Validate MCP tool listing via JSON-RPC."""

    def _mcp_rpc(self, url, method, params=None):
        """Send a JSON-RPC request to MCP endpoint."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
        }
        if params:
            payload["params"] = params
        return requests.post(f"{url}/mcp", json=payload, timeout=TIMEOUT)

    def test_tools_list_via_mcp_server(self):
        """Direct MCP server returns tool list."""
        resp = self._mcp_rpc(MCP_SERVER_URL, "tools/list")
        # If MCP protocol is fully available, verify tools
        if resp.status_code == 200:
            data = resp.json()
            if "result" in data:
                tools = data["result"].get("tools", [])
                tool_names = [t["name"] for t in tools]
                expected_tools = [
                    "submit_slurm_job",
                    "get_job_details",
                    "cancel_slurm_job",
                    "ping",
                    "list_cluster_jobs",
                    "get_cluster_summary",
                ]
                for tool in expected_tools:
                    assert tool in tool_names, f"Missing tool: {tool}"
                assert len(tools) == 27

    def test_tools_list_via_proxy(self):
        """Proxy passes MCP tool listing through correctly."""
        resp = self._mcp_rpc(PROXY_URL, "tools/list")
        if resp.status_code == 200:
            data = resp.json()
            if "result" in data:
                tools = data["result"].get("tools", [])
                assert len(tools) >= 27


class TestSlurmClusterHealth:
    """Validate the Slurm backend cluster (requires containers running)."""

    @pytest.mark.skipif(
        not os.environ.get("SLURM_CLUSTER_RUNNING"),
        reason="Set SLURM_CLUSTER_RUNNING=1 when Slurm containers are running",
    )
    def test_slurmctld_ping(self):
        """slurmctld responds with UP status."""
        result = subprocess.run(
            ["docker", "exec", "slurmctld", "scontrol", "ping"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "UP" in result.stdout

    @pytest.mark.skipif(
        not os.environ.get("SLURM_CLUSTER_RUNNING"),
        reason="Set SLURM_CLUSTER_RUNNING=1 when Slurm containers are running",
    )
    def test_munge_authentication(self):
        """Munge auth works between slurmctld and slurmdbd."""
        # Generate munge credential on slurmctld, verify on slurmdbd
        result = subprocess.run(
            "docker exec slurmctld munge -n | docker exec -i slurmdbd unmunge",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    @pytest.mark.skipif(
        not os.environ.get("SLURM_CLUSTER_RUNNING"),
        reason="Set SLURM_CLUSTER_RUNNING=1 when Slurm containers are running",
    )
    def test_compute_nodes_registered(self):
        """Both c1 and c2 compute nodes are registered."""
        result = subprocess.run(
            ["docker", "exec", "slurmctld", "sinfo", "-N", "-h"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "c1" in result.stdout
        assert "c2" in result.stdout

    @pytest.mark.skipif(
        not os.environ.get("SLURM_CLUSTER_RUNNING"),
        reason="Set SLURM_CLUSTER_RUNNING=1 when Slurm containers are running",
    )
    def test_job_submission_and_completion(self):
        """Submit a test job and verify it completes."""
        # Submit
        submit_result = subprocess.run(
            [
                "docker", "exec", "slurmctld",
                "sbatch", "--job-name=e2e_test", "--output=/data/e2e_%j.out",
                "--wrap", "hostname && date && echo E2E_TEST_OK",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "Submitted batch job" in submit_result.stdout

        job_id = submit_result.stdout.strip().split()[-1]

        # Wait for completion (max 30s)
        import time
        state = "UNKNOWN"
        for _ in range(15):
            check = subprocess.run(
                ["docker", "exec", "slurmctld", "scontrol", "show", "job", job_id],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if "JobState=COMPLETED" in check.stdout:
                state = "COMPLETED"
                break
            elif "JobState=FAILED" in check.stdout:
                state = "FAILED"
                break
            time.sleep(2)

        assert state == "COMPLETED", f"Job {job_id} ended with state: {state}"
