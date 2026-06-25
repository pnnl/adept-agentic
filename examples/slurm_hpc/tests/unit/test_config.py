"""
Unit Tests: Configuration
=========================

Tests for SlurmConfig environment-based configuration.
"""

import os
import sys

import pytest

SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)

from slurm_mcp.config import SlurmConfig


class TestSlurmConfig:
    """Validate SlurmConfig initialization and env var mapping."""

    def test_default_values(self):
        """Config has sensible defaults without env vars."""
        config = SlurmConfig(
            _env_file=None,  # Don't read .env file
        )
        assert "6820" in config.api_url or "localhost" in config.api_url
        assert config.api_version == "v0.0.41"
        assert config.timeout == 30

    def test_env_prefix_mapping(self, monkeypatch):
        """SLURM_ prefixed env vars map to config fields."""
        monkeypatch.setenv("SLURM_API_URL", "http://custom:9999")
        monkeypatch.setenv("SLURM_API_VERSION", "v0.0.42")
        monkeypatch.setenv("SLURM_TIMEOUT", "60")
        monkeypatch.setenv("SLURM_VERIFY_SSL", "true")

        config = SlurmConfig(_env_file=None)
        assert config.api_url == "http://custom:9999"
        assert config.api_version == "v0.0.42"
        assert config.timeout == 60
        assert config.verify_ssl is True

    def test_jwt_settings(self, monkeypatch):
        """JWT-related env vars are read correctly."""
        monkeypatch.setenv("SLURM_JWT_KEY", "dGVzdGtleQ==")
        monkeypatch.setenv("SLURM_SERVICE_JWT", "jwt-token-123")
        monkeypatch.setenv("SLURM_SERVICE_USER", "slurmadmin")

        config = SlurmConfig(_env_file=None)
        assert config.jwt_key == "dGVzdGtleQ=="
        assert config.service_jwt == "jwt-token-123"
        assert config.service_user == "slurmadmin"

    def test_job_state_emojis_defined(self):
        """Common job states have emoji mappings."""
        config = SlurmConfig(_env_file=None)
        for state in ["RUNNING", "PENDING", "COMPLETED", "FAILED", "CANCELLED"]:
            assert state in config.JOB_STATE_EMOJIS

    def test_node_state_emojis_defined(self):
        """Common node states have emoji mappings."""
        config = SlurmConfig(_env_file=None)
        for state in ["IDLE", "ALLOCATED", "MIXED", "DOWN", "DRAIN"]:
            assert state in config.NODE_STATE_EMOJIS

    def test_extra_env_vars_ignored(self, monkeypatch):
        """Extra SLURM_ env vars don't cause errors (extra='ignore')."""
        monkeypatch.setenv("SLURM_UNKNOWN_SETTING", "whatever")
        config = SlurmConfig(_env_file=None)
        assert config is not None


class TestSlurmConfigSpiffe:
    """Validate SPIFFE-related config fields."""

    def test_spiffe_disabled_by_default(self):
        """spiffe_enabled defaults to False."""
        config = SlurmConfig(_env_file=None)
        assert config.spiffe_enabled is False

    def test_spiffe_endpoint_socket_default(self):
        """spiffe_endpoint_socket has default Workload API path."""
        config = SlurmConfig(_env_file=None)
        assert "agent.sock" in config.spiffe_endpoint_socket

    def test_spiffe_audience_default(self):
        """spiffe_audience defaults to slurmrestd."""
        config = SlurmConfig(_env_file=None)
        assert config.spiffe_audience == "slurmrestd"

    def test_spiffe_enabled_from_env(self, monkeypatch):
        """SLURM_SPIFFE_ENABLED=true activates SPIFFE."""
        monkeypatch.setenv("SLURM_SPIFFE_ENABLED", "true")
        config = SlurmConfig(_env_file=None)
        assert config.spiffe_enabled is True

    def test_spiffe_socket_from_env(self, monkeypatch):
        """SLURM_SPIFFE_ENDPOINT_SOCKET overrides default."""
        monkeypatch.setenv(
            "SLURM_SPIFFE_ENDPOINT_SOCKET",
            "unix:///opt/spire/sockets/workload.sock",
        )
        config = SlurmConfig(_env_file=None)
        assert "workload.sock" in config.spiffe_endpoint_socket

    def test_spiffe_audience_from_env(self, monkeypatch):
        """SLURM_SPIFFE_AUDIENCE overrides default."""
        monkeypatch.setenv("SLURM_SPIFFE_AUDIENCE", "custom-audience")
        config = SlurmConfig(_env_file=None)
        assert config.spiffe_audience == "custom-audience"
