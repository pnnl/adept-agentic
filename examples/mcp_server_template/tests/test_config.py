"""Tier 1: Validate Pydantic settings and environment variable binding."""

import os
from unittest.mock import patch

import pytest


class TestDefaultSettings:
    """Verify default values without any environment overrides."""

    def test_default_port(self):
        from {{NAME}}_mcp.config import Settings
        s = Settings()
        assert s.port == {{MCP_PORT}}

    def test_default_device(self):
        from {{NAME}}_mcp.config import Settings
        s = Settings()
        assert s.device == "cpu"

    def test_default_redis_url(self):
        from {{NAME}}_mcp.config import Settings
        s = Settings()
        assert "redis://" in s.redis_url

    def test_default_results_dir(self):
        from {{NAME}}_mcp.config import Settings
        s = Settings()
        assert "{{NAME}}" in s.results_dir


class TestEnvOverrides:
    """Verify environment variable prefix binding."""

    def test_port_override(self):
        with patch.dict(os.environ, {"{{NAME_UPPER}}_PORT": "19999"}):
            from {{NAME}}_mcp.config import Settings
            s = Settings()
            assert s.port == 19999

    def test_device_override(self):
        with patch.dict(os.environ, {"{{NAME_UPPER}}_DEVICE": "cuda"}):
            from {{NAME}}_mcp.config import Settings
            s = Settings()
            assert s.device == "cuda"

    def test_redis_url_override(self):
        with patch.dict(os.environ, {"{{NAME_UPPER}}_REDIS_URL": "redis://custom:6380/1"}):
            from {{NAME}}_mcp.config import Settings
            s = Settings()
            assert s.redis_url == "redis://custom:6380/1"

    def test_extra_fields_ignored(self):
        """Extra env vars with the prefix should not raise."""
        with patch.dict(os.environ, {"{{NAME_UPPER}}_UNKNOWN_FIELD": "ignored"}):
            from {{NAME}}_mcp.config import Settings
            s = Settings()
            assert not hasattr(s, "unknown_field")
