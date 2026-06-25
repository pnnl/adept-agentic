"""
Unit Tests: SPIFFE Authentication Module
=========================================

Tests for spiffe_auth.py — feature flag, JWT-SVID, x509-SVID, and mTLS.
All tests run offline (no SPIRE agent required).
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)


class TestSpiffeFeatureFlag:
    """Validate SPIFFE_ENABLED feature flag behavior."""

    def test_disabled_by_default(self, monkeypatch):
        """SPIFFE_ENABLED defaults to false."""
        monkeypatch.delenv("SPIFFE_ENABLED", raising=False)
        # Force reimport
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import SPIFFE_ENABLED
        assert SPIFFE_ENABLED is False

    def test_enabled_with_true(self, monkeypatch):
        """SPIFFE_ENABLED=true activates the module."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import SPIFFE_ENABLED
        assert SPIFFE_ENABLED is True

    def test_enabled_with_1(self, monkeypatch):
        """SPIFFE_ENABLED=1 activates the module."""
        monkeypatch.setenv("SPIFFE_ENABLED", "1")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import SPIFFE_ENABLED
        assert SPIFFE_ENABLED is True


class TestSpiffeEndpointSocket:
    """Validate SPIFFE_ENDPOINT_SOCKET env var behavior."""

    def test_default_socket_path(self, monkeypatch):
        """Default socket path is /run/spire/sockets/agent.sock."""
        monkeypatch.delenv("SPIFFE_ENDPOINT_SOCKET", raising=False)
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import SPIFFE_ENDPOINT_SOCKET
        assert "agent.sock" in SPIFFE_ENDPOINT_SOCKET

    def test_custom_socket_path(self, monkeypatch):
        """Custom socket path is read from env."""
        monkeypatch.setenv(
            "SPIFFE_ENDPOINT_SOCKET",
            "unix:///opt/spire/sockets/workload.sock",
        )
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import SPIFFE_ENDPOINT_SOCKET
        assert SPIFFE_ENDPOINT_SOCKET == "unix:///opt/spire/sockets/workload.sock"

    def test_enabled_with_yes(self, monkeypatch):
        """SPIFFE_ENABLED=yes activates the module."""
        monkeypatch.setenv("SPIFFE_ENABLED", "yes")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import SPIFFE_ENABLED
        assert SPIFFE_ENABLED is True

    def test_disabled_with_no(self, monkeypatch):
        """SPIFFE_ENABLED=no keeps module disabled."""
        monkeypatch.setenv("SPIFFE_ENABLED", "no")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import SPIFFE_ENABLED
        assert SPIFFE_ENABLED is False

    def test_disabled_with_random_string(self, monkeypatch):
        """SPIFFE_ENABLED=random keeps module disabled."""
        monkeypatch.setenv("SPIFFE_ENABLED", "randomstring")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import SPIFFE_ENABLED
        assert SPIFFE_ENABLED is False


class TestGetJwtSvid:
    """Validate get_jwt_svid behavior without SPIRE agent."""

    def test_returns_none_when_disabled(self, monkeypatch):
        """get_jwt_svid returns None when SPIFFE disabled."""
        monkeypatch.setenv("SPIFFE_ENABLED", "false")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import get_jwt_svid
        assert get_jwt_svid() is None

    def test_returns_none_when_no_spiffe_package(self, monkeypatch):
        """get_jwt_svid returns None when py-spiffe not installed."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        # Reset the global singleton so _get_workload_client tries import
        import slurm_mcp.spiffe_auth as mod
        mod._workload_client = None

        with patch.dict("sys.modules", {"spiffe": None}):
            result = mod.get_jwt_svid(audience="slurmrestd")
            assert result is None

    def test_returns_token_from_mock_client(self, monkeypatch):
        """get_jwt_svid returns token from mocked WorkloadApiClient."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod

        mock_svid = MagicMock()
        mock_svid.token = "eyJ-mock-jwt-svid"
        mock_svid.spiffe_id = "spiffe://pnnl.adept.slurm/slurm-mcp-server"

        mock_client = MagicMock()
        mock_client.fetch_jwt_svids.return_value = [mock_svid]
        mod._workload_client = mock_client

        result = mod.get_jwt_svid(audience="slurmrestd")
        assert result == "eyJ-mock-jwt-svid"
        mock_client.fetch_jwt_svids.assert_called_once_with(audiences=["slurmrestd"])

        # Cleanup
        mod._workload_client = None

    def test_returns_none_for_empty_svid_set(self, monkeypatch):
        """get_jwt_svid returns None when SPIRE agent returns empty set."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod

        mock_client = MagicMock()
        mock_client.fetch_jwt_svids.return_value = []
        mod._workload_client = mock_client

        result = mod.get_jwt_svid(audience="slurmrestd")
        assert result is None

        # Cleanup
        mod._workload_client = None

    def test_returns_none_on_fetch_exception(self, monkeypatch):
        """get_jwt_svid returns None when fetch raises an exception."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod

        mock_client = MagicMock()
        mock_client.fetch_jwt_svids.side_effect = RuntimeError("SPIRE agent down")
        mod._workload_client = mock_client

        result = mod.get_jwt_svid(audience="slurmrestd")
        assert result is None

        # Cleanup
        mod._workload_client = None

    def test_custom_audience(self, monkeypatch):
        """get_jwt_svid passes custom audience to SPIRE agent."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod

        mock_svid = MagicMock()
        mock_svid.token = "custom-audience-token"
        mock_svid.spiffe_id = "spiffe://pnnl.adept.slurm/slurm-mcp-server"

        mock_client = MagicMock()
        mock_client.fetch_jwt_svids.return_value = [mock_svid]
        mod._workload_client = mock_client

        result = mod.get_jwt_svid(audience="custom-api")
        assert result == "custom-audience-token"
        mock_client.fetch_jwt_svids.assert_called_once_with(audiences=["custom-api"])

        # Cleanup
        mod._workload_client = None


class TestGetX509Svid:
    """Validate get_x509_svid behavior."""

    def test_returns_none_when_disabled(self, monkeypatch):
        """get_x509_svid returns None when SPIFFE disabled."""
        monkeypatch.setenv("SPIFFE_ENABLED", "false")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import get_x509_svid
        assert get_x509_svid() is None

    def test_returns_tuple_from_mock_client(self, monkeypatch):
        """get_x509_svid returns (cert, key, bundle) tuple."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod

        mock_svid = MagicMock()
        mock_svid.spiffe_id = "spiffe://pnnl.adept.slurm/slurm-mcp-server"
        mock_svid.cert_chain_pem = b"---CERT---"
        mock_svid.private_key_pem = b"---KEY---"
        mock_svid.bundle_pem = b"---BUNDLE---"

        mock_client = MagicMock()
        mock_client.fetch_x509_svid.return_value = mock_svid
        mod._workload_client = mock_client

        result = mod.get_x509_svid()
        assert result == (b"---CERT---", b"---KEY---", b"---BUNDLE---")

        # Cleanup
        mod._workload_client = None


class TestGetX509SvidEdgeCases:
    """Additional x509-SVID edge case coverage."""

    def test_returns_none_when_client_is_none(self, monkeypatch):
        """get_x509_svid returns None when no workload client available."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod
        mod._workload_client = None

        with patch.dict("sys.modules", {"spiffe": None}):
            result = mod.get_x509_svid()
            assert result is None

    def test_returns_none_on_fetch_exception(self, monkeypatch):
        """get_x509_svid returns None when fetch raises exception."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod

        mock_client = MagicMock()
        mock_client.fetch_x509_svid.side_effect = RuntimeError("Agent down")
        mod._workload_client = mock_client

        result = mod.get_x509_svid()
        assert result is None

        # Cleanup
        mod._workload_client = None

    def test_returns_none_for_null_svid(self, monkeypatch):
        """get_x509_svid returns None when agent returns None SVID."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod

        mock_client = MagicMock()
        mock_client.fetch_x509_svid.return_value = None
        mod._workload_client = mock_client

        result = mod.get_x509_svid()
        assert result is None

        # Cleanup
        mod._workload_client = None


class TestGetMtlsSslContext:
    """Validate get_mtls_ssl_context behavior."""

    def test_returns_none_when_disabled(self, monkeypatch):
        """get_mtls_ssl_context returns None when SPIFFE disabled."""
        monkeypatch.setenv("SPIFFE_ENABLED", "false")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]
        from slurm_mcp.spiffe_auth import get_mtls_ssl_context
        assert get_mtls_ssl_context() is None

    def test_returns_none_when_no_x509_svid(self, monkeypatch):
        """get_mtls_ssl_context returns None when x509 fetch returns None."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod

        mock_client = MagicMock()
        mock_client.fetch_x509_svid.return_value = None
        mod._workload_client = mock_client

        result = mod.get_mtls_ssl_context()
        assert result is None

        # Cleanup
        mod._workload_client = None


class TestGetWorkloadClient:
    """Validate _get_workload_client lazy singleton behavior."""

    def test_returns_cached_client(self, monkeypatch):
        """Returns the existing singleton when already set."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod

        sentinel = MagicMock()
        mod._workload_client = sentinel

        result = mod._get_workload_client()
        assert result is sentinel

        # Cleanup
        mod._workload_client = None

    def test_returns_none_on_creation_error(self, monkeypatch):
        """Returns None when WorkloadApiClient constructor raises."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod
        mod._workload_client = None

        mock_spiffe = MagicMock()
        mock_spiffe.WorkloadApiClient.side_effect = RuntimeError("Socket not found")

        with patch.dict("sys.modules", {"spiffe": mock_spiffe}):
            result = mod._get_workload_client()
            assert result is None

        # Cleanup
        mod._workload_client = None


class TestClientSpiffeIntegration:
    """Validate SPIFFE integration in JWTTokenManager.get_token()."""

    def test_spiffe_takes_priority_over_hmac(self, monkeypatch):
        """When SPIFFE enabled and returns a token, HMAC is not used."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import slurm_mcp.spiffe_auth as mod
        mock_svid = MagicMock()
        mock_svid.token = "spiffe-jwt-token"
        mock_svid.spiffe_id = "spiffe://pnnl.adept.slurm/slurm-mcp-server"
        mock_client = MagicMock()
        mock_client.fetch_jwt_svids.return_value = [mock_svid]
        mod._workload_client = mock_client

        from slurm_mcp.client import JWTTokenManager
        mgr = JWTTokenManager(jwt_key="dGVzdA==", service_jwt="static", service_user="root")
        token = mgr.get_token()
        assert token == "spiffe-jwt-token"

        # Cleanup
        mod._workload_client = None

    def test_falls_back_to_hmac_when_spiffe_fails(self, monkeypatch):
        """When SPIFFE returns None, falls back to HMAC."""
        monkeypatch.setenv("SPIFFE_ENABLED", "true")
        if "slurm_mcp.spiffe_auth" in sys.modules:
            del sys.modules["slurm_mcp.spiffe_auth"]

        import secrets, base64
        import slurm_mcp.spiffe_auth as mod
        mod._workload_client = None  # No client = returns None

        key = secrets.token_bytes(32)
        key_b64 = base64.b64encode(key).decode()

        from slurm_mcp.client import JWTTokenManager
        mgr = JWTTokenManager(jwt_key=key_b64, service_jwt="", service_user="root")
        token = mgr.get_token()
        # Should be a valid JWT from HMAC, not None
        assert token is not None
        assert len(token.split(".")) == 3
