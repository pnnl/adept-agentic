"""
Shared fixtures for Slurm HPC test suite.

Provides common config fixtures, mock transport helpers, and sample data
used across unit, integration, and E2E tests.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add the slurm_mcp_server source to Python path for imports
SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)


# ---------------------------------------------------------------------------
# Environment / Config Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def slurm_config_env(monkeypatch):
    """Set up minimal environment for SlurmConfig instantiation."""
    monkeypatch.setenv("SLURM_API_URL", "http://slurmrestd:6820")
    monkeypatch.setenv("SLURM_API_VERSION", "v0.0.41")
    monkeypatch.setenv("SLURM_VERIFY_SSL", "false")
    monkeypatch.setenv("SLURM_TIMEOUT", "30")
    monkeypatch.setenv("SLURM_JWT_KEY", "")
    monkeypatch.setenv("SLURM_SERVICE_JWT", "test-token-123")
    monkeypatch.setenv("SLURM_SERVICE_USER", "testuser")


@pytest.fixture
def deception_env(monkeypatch):
    """Set environment for Deception cluster config."""
    monkeypatch.setenv("DECEPTION_USERNAME", "testuser")
    monkeypatch.setenv("DECEPTION_HOST", "deception.pnl.gov")


@pytest.fixture
def tahoma_env(monkeypatch):
    """Set environment for Tahoma cluster config."""
    monkeypatch.setenv("TAHOMA_USERNAME", "testuser")
    monkeypatch.setenv("TAHOMA_HOST", "tahoma.emsl.pnl.gov")


@pytest.fixture
def fake_ssh_config(tmp_path):
    """Minimal SSH config satisfying the SSHConfig protocol (for unit tests)."""

    class _FakeConfig:
        host = "test-cluster.example.com"
        ssh_port = 22
        username = "testuser"
        ssh_timeout = 30
        default_partition = "compute"
        default_account = "testalloc"

        @property
        def resolved_ssh_key_path(self):
            return tmp_path / "fake_key"

        @property
        def resolved_working_directory(self):
            return "/scratch/testuser"

    return _FakeConfig()


@pytest.fixture
def mock_deception_config():
    """MagicMock of DeceptionConfig for unit tests that need all attributes."""
    config = MagicMock()
    config.host = "deception.pnl.gov"
    config.ssh_port = 22
    config.username = "testuser"
    config.ssh_timeout = 30
    config.default_partition = "slurm"
    config.default_account = "emsl51397"
    config.resolved_ssh_key_path = Path("/app/.ssh/testuser/adept_deception_ed25519")
    config.resolved_working_directory = "/scratch/testuser"
    return config


@pytest.fixture
def mock_tahoma_config():
    """MagicMock of TahomaConfig for unit tests that need all attributes."""
    config = MagicMock()
    config.host = "tahoma.emsl.pnl.gov"
    config.ssh_port = 22
    config.username = "testuser"
    config.ssh_timeout = 30
    config.default_partition = "normal"
    config.default_account = "testalloc"
    config.rest_api_url = "http://tahoma-rest:6820"
    config.rest_api_version = "v0.0.41"
    config.rest_timeout = 30
    config.jwt_key = ""
    config.service_jwt = "test-token-123"
    config.working_directory = "/scratch/testuser"
    config.resolved_ssh_key_path = Path("/app/.ssh/testuser/adept_tahoma_ed25519")
    config.resolved_working_directory = "/scratch/testuser"
    return config


@pytest.fixture
def sample_job_data():
    """Sample job data matching SLURM API response format."""
    return {
        "job_id": 42,
        "name": "test_job",
        "user_name": "testuser",
        "partition": "normal",
        "job_state": ["COMPLETED"],
        "nodes": "c1",
        "cpus": {"number": 2},
        "current_working_directory": "/data",
        "submit_time": {"number": 1709600000},
        "start_time": {"number": 1709600010},
        "end_time": {"number": 1709600100},
        "time_limit": {"number": 60},
        "run_time": {"number": 90},
        "exit_code": {"number": 0},
        "standard_output": "/data/test_42.out",
        "standard_error": "/data/test_42.err",
        "account": "default",
        "tres_alloc_str": "cpu=2,mem=1000M",
    }


@pytest.fixture
def sample_jobs_list():
    """Sample job list for format_job_list testing."""
    return [
        {
            "job_id": 1,
            "name": "alpha",
            "user_name": "alice",
            "job_state": ["RUNNING"],
            "partition": "normal",
            "nodes": "c1",
            "submit_time": 1709600000,
        },
        {
            "job_id": 2,
            "name": "beta",
            "user_name": "bob",
            "job_state": ["PENDING"],
            "partition": "normal",
            "nodes": "",
            "submit_time": 1709600100,
        },
        {
            "job_id": 3,
            "name": "gamma",
            "user_name": "alice",
            "job_state": ["COMPLETED"],
            "partition": "normal",
            "nodes": "c2",
            "submit_time": 1709599000,
        },
    ]
