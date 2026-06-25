"""Tests for the adept-auth-proxy CLI argument parsing."""

from __future__ import annotations

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Ensure env vars for tests
os.environ.setdefault("ADEPT_API_KEY", "test-api-key-fixture")
os.environ.setdefault("ADEPT_AUTH_METHOD", "api_key")


class TestCLIArgumentParsing:
    """Tests for CLI argument parsing (no actual server startup)."""

    def _run_cli(self, argv=None):
        """Run CLI main() with uvicorn mocked to prevent actual server startup."""
        mock_uvicorn = MagicMock()
        # Inject mock uvicorn into sys.modules so `import uvicorn` inside main() gets it
        with patch.dict(sys.modules, {"uvicorn": mock_uvicorn}):
            from adept_connectors.connectors.generic.cli import main
            main(argv or [])
        return mock_uvicorn

    def test_default_arguments(self):
        """Default values are sane."""
        mock_uvicorn = self._run_cli()
        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs[1]["host"] == "127.0.0.1"
        assert call_kwargs[1]["port"] == 19283

    def test_custom_port(self):
        """--port overrides default."""
        mock_uvicorn = self._run_cli(["--port", "9999"])
        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs[1]["port"] == 9999

    def test_custom_upstream(self):
        """--upstream sets the forwarding target."""
        mock_uvicorn = self._run_cli(["--upstream", "http://adept.example.com/v1"])
        mock_uvicorn.run.assert_called_once()

    def test_password_auth_arguments(self):
        """--auth-method password + --username + --password accepted."""
        mock_uvicorn = self._run_cli([
            "--auth-method", "password",
            "--username", "alice",
            "--password", "secret",
            "--keycloak-url", "http://kc:8180",
        ])
        mock_uvicorn.run.assert_called_once()

    def test_log_level_argument(self):
        """--log-level sets uvicorn log level."""
        mock_uvicorn = self._run_cli(["--log-level", "DEBUG"])
        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs[1]["log_level"] == "debug"

    def test_no_verify_ssl(self):
        """--no-verify-ssl disables SSL verification."""
        mock_uvicorn = self._run_cli(["--no-verify-ssl"])
        mock_uvicorn.run.assert_called_once()
