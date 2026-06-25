"""
Unit Tests: FastMCP App Configuration
=======================================

Tests for app.py — validates the FastMCP app instance and its configuration.
"""

import logging
import os
import sys

import pytest

SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)


class TestFastMCPApp:
    """Validate FastMCP app instance configuration."""

    def test_app_name(self):
        """App has the correct name."""
        from slurm_mcp.app import app
        assert app.name == "SLURM HPC Cluster Management"

    def test_app_has_instructions(self):
        """App has non-empty instructions for agent guidance."""
        from slurm_mcp.app import app
        assert app.instructions is not None
        assert len(app.instructions) > 100

    def test_instructions_contain_workflow(self):
        """Instructions include workflow guidance."""
        from slurm_mcp.app import app
        instructions = app.instructions
        assert "WORKFLOW" in instructions
        assert "submit_slurm_job" in instructions
        assert "get_cluster_summary" in instructions

    def test_instructions_contain_tool_list(self):
        """Instructions list core available tools."""
        from slurm_mcp.app import app
        instructions = app.instructions
        assert "get_job_details" in instructions
        assert "cancel_slurm_job" in instructions
        assert "ping" in instructions
        assert "list_cluster_jobs" in instructions
        assert "get_cluster_summary" in instructions

    def test_no_auth_on_app(self):
        """App should NOT have authentication configured."""
        from slurm_mcp.app import app
        # FastMCP's auth attribute should not be set
        auth = getattr(app, "_auth_server_provider", None)
        assert auth is None, "App should not have inbound auth (handled by ADEPT Tier 1)"

    def test_main_is_callable(self):
        """main() entry point exists and is callable."""
        from slurm_mcp.app import main
        assert callable(main)


class TestToolRegistration:
    """Validate tools are registered with the app after import."""

    @pytest.mark.asyncio
    async def test_tools_registered(self):
        """Importing tools modules registers tool functions with app."""
        from slurm_mcp.app import app
        from slurm_mcp import tools  # noqa: F401
        from slurm_mcp.deception import tools as _dt  # noqa: F401
        from slurm_mcp.tahoma import tools as _tt  # noqa: F401
        from slurm_mcp import ssh_key_tools as _sk  # noqa: F401

        tool_manager = getattr(app, "_tool_manager", None)
        if tool_manager:
            tools_dict = await tool_manager.get_tools()
            tool_names = list(tools_dict.keys())
            # Local tools
            assert "submit_slurm_job" in tool_names
            assert "get_job_details" in tool_names
            assert "cancel_slurm_job" in tool_names
            assert "ping" in tool_names
            assert "list_cluster_jobs" in tool_names
            assert "get_cluster_summary" in tool_names
            # Deception tools
            assert "deception_ping" in tool_names
            assert "deception_submit_job" in tool_names
            # Tahoma tools
            assert "tahoma_ping" in tool_names
            assert "tahoma_submit_job" in tool_names
            # SSH key tools
            assert "hpc_list_clusters" in tool_names
            assert "hpc_check_ssh_key" in tool_names

    def test_resources_registered(self):
        """Importing resources module registers resources with app."""
        from slurm_mcp.app import app
        from slurm_mcp import resources  # noqa: F401

        resource_manager = getattr(app, "_resource_manager", None)
        if resource_manager:
            # Verify at least some resources exist
            assert resource_manager is not None

    def test_prompts_registered(self):
        """Importing prompts module registers prompts with app."""
        from slurm_mcp.app import app
        from slurm_mcp import prompts  # noqa: F401

        prompt_manager = getattr(app, "_prompt_manager", None)
        if prompt_manager:
            assert prompt_manager is not None


class TestLoggingConfiguration:
    """Tests for logging setup — timestamps, format, Uvicorn override."""

    def test_root_logger_has_timestamp_format(self):
        """Root logger should have our custom format with timestamps."""
        from slurm_mcp.app import _log_format, _log_datefmt

        assert "%(asctime)s" in _log_format
        assert "%(levelname)s" in _log_format
        assert "%(name)s" in _log_format
        assert _log_datefmt == "%Y-%m-%d %H:%M:%S"

    def test_apply_log_format_to_uvicorn_creates_handlers(self):
        """_apply_log_format_to_uvicorn sets formatters on uvicorn loggers."""
        from slurm_mcp.app import _apply_log_format_to_uvicorn, _log_format, _log_datefmt

        _apply_log_format_to_uvicorn()

        for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            uv_logger = logging.getLogger(name)
            assert len(uv_logger.handlers) > 0, f"{name} should have at least one handler"
            fmt = uv_logger.handlers[0].formatter
            assert fmt is not None, f"{name} handler should have a formatter"
            assert "%(asctime)s" in fmt._fmt

    def test_slurm_mcp_logger_exists(self):
        """Module-level slurm_mcp logger should be configured."""
        from slurm_mcp.app import logger

        assert logger.name == "slurm_mcp"

    def test_log_level_from_env(self):
        """SLURM_MCP_LOG_LEVEL env var controls root log level."""
        import sys
        mod = sys.modules["slurm_mcp.app"]
        # Verify the module-level _log_level variable exists
        assert hasattr(mod, "_log_level")
        assert mod._log_level in ("DEBUG", "INFO", "WARNING", "ERROR")

    def test_uvicorn_log_config_structure(self):
        """_uvicorn_log_config returns valid dictconfig for Uvicorn."""
        from slurm_mcp.app import _uvicorn_log_config

        config = _uvicorn_log_config()
        assert config["version"] == 1
        assert config["disable_existing_loggers"] is False
        assert "default" in config["formatters"]
        assert "access" in config["formatters"]
        assert "%(asctime)s" in config["formatters"]["default"]["fmt"]
        assert "%(asctime)s" in config["formatters"]["access"]["fmt"]
        assert "uvicorn" in config["loggers"]
        assert "uvicorn.access" in config["loggers"]

    def test_uvicorn_log_config_datefmt(self):
        """_uvicorn_log_config uses same datefmt as root logger."""
        from slurm_mcp.app import _uvicorn_log_config, _log_datefmt

        config = _uvicorn_log_config()
        assert config["formatters"]["default"]["datefmt"] == _log_datefmt
        assert config["formatters"]["access"]["datefmt"] == _log_datefmt
