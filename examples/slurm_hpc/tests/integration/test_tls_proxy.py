"""
Integration Tests: TLS Proxy
=============================

Tests for the nginx reverse proxy HTTPS/TLS configuration.
Validates both HTTP-only (no certs) and HTTPS (with certs) modes.

Prerequisites:
    - Slurm stack running: cd examples/slurm_hpc && make start
    - For HTTPS tests: certs generated (make generate-certs) and proxy restarted

Usage:
    # HTTP-only tests (always available)
    pytest tests/integration/test_tls_proxy.py -v -k "http"

    # Full TLS tests (requires certs + HTTPS port)
    SLURM_PROXY_HTTPS_URL=https://localhost:9821 \
    SLURM_CA_CERT=./certs/ca.crt \
    pytest tests/integration/test_tls_proxy.py -v
"""

import os
import shutil
import subprocess
import time

import pytest
import requests
import urllib3

# URLs — configurable via env
PROXY_HTTP_URL = os.environ.get("SLURM_PROXY_URL", "http://localhost:9820")
PROXY_HTTPS_URL = os.environ.get("SLURM_PROXY_HTTPS_URL", "https://localhost:9821")
CA_CERT_PATH = os.environ.get("SLURM_CA_CERT", "./certs/ca.crt")
TIMEOUT = 10


def _has_certs():
    """Check if CA cert exists (proxy should be in TLS mode)."""
    return os.path.isfile(CA_CERT_PATH)


def _proxy_http_reachable():
    """Check if HTTP proxy is reachable (retries briefly for startup timing)."""
    for attempt in range(3):
        try:
            requests.get(f"{PROXY_HTTP_URL}/health", timeout=3)
            return True
        except (requests.ConnectionError, requests.Timeout):
            if attempt < 2:
                time.sleep(2)
    return False


def _has_docker_cli():
    """Check if docker CLI is available (needed for log inspection)."""
    return shutil.which("docker") is not None


class TestHTTPProxy:
    """HTTP proxy tests — always work regardless of TLS configuration."""

    @pytest.mark.skipif(
        not _proxy_http_reachable(),
        reason="HTTP proxy not reachable (stack not running?)",
    )
    def test_http_health_returns_200(self):
        """HTTP /health returns 200."""
        resp = requests.get(f"{PROXY_HTTP_URL}/health", timeout=TIMEOUT)
        assert resp.status_code == 200

    @pytest.mark.skipif(
        not _proxy_http_reachable(),
        reason="HTTP proxy not reachable (stack not running?)",
    )
    def test_http_mcp_endpoint_exists(self):
        """HTTP /mcp is reachable."""
        resp = requests.get(f"{PROXY_HTTP_URL}/mcp", timeout=TIMEOUT)
        assert resp.status_code in [200, 400, 405, 406]

    @pytest.mark.skipif(
        not _proxy_http_reachable(),
        reason="HTTP proxy not reachable (stack not running?)",
    )
    def test_http_catchall_404(self):
        """HTTP unknown paths return 404."""
        resp = requests.get(f"{PROXY_HTTP_URL}/nonexistent", timeout=TIMEOUT)
        assert resp.status_code == 404


@pytest.mark.skipif(not _has_certs(), reason="No certs found (TLS not configured)")
class TestHTTPSProxy:
    """HTTPS proxy tests — require certs generated and proxy restarted."""

    def test_https_health_with_ca_cert(self):
        """HTTPS /health returns 200 when CA cert is provided."""
        resp = requests.get(
            f"{PROXY_HTTPS_URL}/health",
            verify=CA_CERT_PATH,
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200

    def test_https_mcp_endpoint_with_ca_cert(self):
        """HTTPS /mcp is reachable with CA cert verification."""
        resp = requests.get(
            f"{PROXY_HTTPS_URL}/mcp",
            verify=CA_CERT_PATH,
            timeout=TIMEOUT,
        )
        assert resp.status_code in [200, 400, 405, 406]

    def test_https_fails_without_ca_cert(self):
        """HTTPS fails with SSL error when no CA cert provided (self-signed)."""
        with pytest.raises(requests.exceptions.SSLError):
            requests.get(
                f"{PROXY_HTTPS_URL}/health",
                verify=True,  # System cert bundle — won't have our CA
                timeout=TIMEOUT,
            )

    def test_https_catchall_404(self):
        """HTTPS unknown paths return 404."""
        resp = requests.get(
            f"{PROXY_HTTPS_URL}/nonexistent",
            verify=CA_CERT_PATH,
            timeout=TIMEOUT,
        )
        assert resp.status_code == 404

    def test_https_mcp_jsonrpc_passthrough(self):
        """HTTPS MCP JSON-RPC request passes through to backend."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        }
        resp = requests.post(
            f"{PROXY_HTTPS_URL}/mcp",
            json=payload,
            verify=CA_CERT_PATH,
            timeout=TIMEOUT,
        )
        # MCP server should respond (may need SSE, so accept various codes)
        assert resp.status_code in [200, 400, 405, 406]


@pytest.mark.skipif(not _has_certs(), reason="No certs found (TLS not configured)")
class TestCertificateProperties:
    """Validate the deployed certificates have correct properties."""

    def test_server_cert_matches_ca(self):
        """Server cert is signed by the CA cert in certs/."""
        result = subprocess.run(
            [
                "openssl", "verify",
                "-CAfile", CA_CERT_PATH,
                CA_CERT_PATH.replace("ca.crt", "slurm.crt"),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_server_cert_not_expired(self):
        """Server cert is not expired and valid for at least 1 day."""
        slurm_crt = CA_CERT_PATH.replace("ca.crt", "slurm.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", slurm_crt, "-checkend", "86400", "-noout"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, "Server cert expires within 24 hours"

    def test_ca_cert_not_expired(self):
        """CA cert is not expired and valid for at least 1 day."""
        result = subprocess.run(
            ["openssl", "x509", "-in", CA_CERT_PATH, "-checkend", "86400", "-noout"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, "CA cert expires within 24 hours"


class TestProxyTLSDetection:
    """Validate the conditional TLS detection in docker-compose command."""

    @pytest.mark.skipif(
        not _proxy_http_reachable(),
        reason="HTTP proxy not reachable (stack not running?)",
    )
    @pytest.mark.skipif(
        not _has_docker_cli(),
        reason="Docker CLI not available in test container",
    )
    def test_proxy_logs_tls_status(self):
        """Proxy container logs show TLS status message."""
        result = subprocess.run(
            ["docker", "logs", "slurm_nginx_proxy"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        combined = result.stdout + result.stderr
        assert (
            "[slurm-proxy] TLS enabled (certs found)" in combined
            or "[slurm-proxy] HTTP-only mode (no certs)" in combined
        ), f"No TLS status message in proxy logs (first 500 chars): {combined[:500]}"

    @pytest.mark.skipif(
        not _proxy_http_reachable(),
        reason="HTTP proxy not reachable (stack not running?)",
    )
    @pytest.mark.skipif(
        not _has_docker_cli(),
        reason="Docker CLI not available in test container",
    )
    @pytest.mark.skipif(not _has_certs(), reason="No certs found (TLS not configured)")
    def test_proxy_logs_tls_enabled(self):
        """When certs present, proxy logs show TLS enabled."""
        result = subprocess.run(
            ["docker", "logs", "slurm_nginx_proxy", "--since", "30s"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        combined = result.stdout + result.stderr
        assert "[slurm-proxy] TLS enabled (certs found)" in combined
