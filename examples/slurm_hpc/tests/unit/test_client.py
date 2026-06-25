"""
Unit Tests: Client and JWTTokenManager
========================================

Tests for SlurmClient, JWTTokenManager, and get_service_client.
"""

import base64
import os
import sys
import time

import pytest

SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)

from slurm_mcp.client import JWTTokenManager, SlurmClient, SlurmError, get_service_client


class TestJWTTokenManager:
    """Validate JWTTokenManager token generation and fallback logic."""

    def test_has_hmac_key(self):
        """has_hmac_key returns True when key is set."""
        mgr = JWTTokenManager(jwt_key="dGVzdA==", service_jwt="", service_user="root")
        assert mgr.has_hmac_key is True

    def test_no_hmac_key(self):
        """has_hmac_key returns False when key is empty."""
        mgr = JWTTokenManager(jwt_key="", service_jwt="", service_user="root")
        assert mgr.has_hmac_key is False

    def test_has_static_token(self):
        """has_static_token returns True when service_jwt is set."""
        mgr = JWTTokenManager(jwt_key="", service_jwt="token123", service_user="root")
        assert mgr.has_static_token is True

    def test_no_static_token(self):
        """has_static_token returns False when service_jwt is empty."""
        mgr = JWTTokenManager(jwt_key="", service_jwt="", service_user="root")
        assert mgr.has_static_token is False

    def test_static_token_fallback(self):
        """get_token returns static JWT when no HMAC key."""
        mgr = JWTTokenManager(jwt_key="", service_jwt="my-static-token", service_user="root")
        token = mgr.get_token()
        assert token == "my-static-token"

    def test_no_credentials_raises(self):
        """get_token raises SlurmError when no credentials available."""
        mgr = JWTTokenManager(jwt_key="", service_jwt="", service_user="root")
        with pytest.raises(SlurmError, match="No JWT credentials"):
            mgr.get_token()

    def test_generate_token_with_hmac_key(self):
        """get_token generates a valid JWT when HMAC key is available."""
        # Generate a 32-byte key and base64 encode it
        import secrets
        key = secrets.token_bytes(32)
        key_b64 = base64.b64encode(key).decode()

        mgr = JWTTokenManager(jwt_key=key_b64, service_jwt="", service_user="testuser")
        token = mgr.get_token()

        assert isinstance(token, str)
        assert len(token) > 0
        # JWT has 3 parts separated by dots
        parts = token.split(".")
        assert len(parts) == 3

    def test_generated_token_has_correct_claims(self):
        """Generated JWT contains expected claims (sun, iat, exp)."""
        import jwt as pyjwt
        import secrets

        key = secrets.token_bytes(32)
        key_b64 = base64.b64encode(key).decode()

        mgr = JWTTokenManager(jwt_key=key_b64, service_jwt="", service_user="slurmadmin")
        token = mgr.get_token()

        # Decode and verify claims
        decoded = pyjwt.decode(token, key, algorithms=["HS256"])
        assert decoded["sun"] == "slurmadmin"
        assert "iat" in decoded
        assert "exp" in decoded
        assert decoded["exp"] > decoded["iat"]

    def test_token_caching(self):
        """Same token is returned within cache window."""
        import secrets

        key = secrets.token_bytes(32)
        key_b64 = base64.b64encode(key).decode()

        mgr = JWTTokenManager(jwt_key=key_b64, service_jwt="", service_user="root")
        token1 = mgr.get_token()
        token2 = mgr.get_token()
        assert token1 == token2  # Cached

    def test_username_property(self):
        """username property returns service_user."""
        mgr = JWTTokenManager(jwt_key="", service_jwt="", service_user="myuser")
        assert mgr.username == "myuser"

    def test_custom_username_in_get_token(self):
        """get_token(username=...) uses custom username for token generation."""
        import secrets

        key = secrets.token_bytes(32)
        key_b64 = base64.b64encode(key).decode()

        mgr = JWTTokenManager(jwt_key=key_b64, service_jwt="", service_user="default")
        token = mgr.get_token(username="custom_user")
        assert isinstance(token, str)


class TestSlurmError:
    """Validate SlurmError exception."""

    def test_basic_error(self):
        """SlurmError stores message."""
        err = SlurmError("Something failed")
        assert str(err) == "Something failed"
        assert err.status_code is None

    def test_error_with_status(self):
        """SlurmError stores status code."""
        err = SlurmError("Auth failed", status_code=401)
        assert err.status_code == 401


class TestSlurmClient:
    """Validate SlurmClient initialization."""

    @pytest.mark.asyncio
    async def test_client_requires_context_manager(self):
        """SlurmClient.request raises if not used as context manager."""
        import secrets
        key = secrets.token_bytes(32)
        key_b64 = base64.b64encode(key).decode()

        mgr = JWTTokenManager(jwt_key=key_b64, service_jwt="", service_user="root")

        class FakeConfig:
            api_url = "http://localhost:6820"
            timeout = 10
            verify_ssl = False

        client = SlurmClient(FakeConfig(), mgr)
        with pytest.raises(RuntimeError, match="must be used as async context manager"):
            await client.request("GET", "/test")


class TestGetServiceClient:
    """Validate get_service_client helper."""

    def test_returns_username_and_client(self, monkeypatch):
        """get_service_client returns (username, SlurmClient)."""
        monkeypatch.setenv("SLURM_SERVICE_JWT", "test-token")
        monkeypatch.setenv("SLURM_SERVICE_USER", "testuser")
        monkeypatch.setenv("SLURM_JWT_KEY", "")

        # Force reimport with new env
        if "slurm_mcp.config" in sys.modules:
            del sys.modules["slurm_mcp.config"]

        from slurm_mcp.client import get_service_client
        username, client = get_service_client()
        assert username == "testuser"
        assert isinstance(client, SlurmClient)
