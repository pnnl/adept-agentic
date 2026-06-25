"""Shared fixtures for {{DISPLAY_NAME}} MCP server tests."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure {{NAME}}_mcp package is importable
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


@pytest.fixture
def mock_settings():
    """Override settings with test-safe values."""
    env_overrides = {
        "{{NAME_UPPER}}_PORT": "19999",
        "{{NAME_UPPER}}_REDIS_URL": "redis://localhost:6379/15",
        "{{NAME_UPPER}}_RESULTS_DIR": "/tmp/test_results",
        "{{NAME_UPPER}}_DEVICE": "cpu",
    }
    with patch.dict(os.environ, env_overrides):
        from {{NAME}}_mcp.config import Settings
        yield Settings()


@pytest.fixture
def mcp_url():
    """MCP server URL for integration tests."""
    host = os.environ.get("{{NAME_UPPER}}_MCP_HOST", "{{NAME}}_mcp_server")
    port = os.environ.get("{{NAME_UPPER}}_MCP_PORT", "{{MCP_PORT}}")
    return f"http://{host}:{port}"


@pytest.fixture
def session_id():
    """Generate a unique test session ID."""
    import uuid
    return f"test_{uuid.uuid4().hex[:8]}"
