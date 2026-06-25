"""Tier 1: Validate that all modules can be imported without error."""

import importlib

import pytest


MODULES = [
    "{{NAME}}_mcp",
    "{{NAME}}_mcp.app",
    "{{NAME}}_mcp.server",
    "{{NAME}}_mcp.config",
    "{{NAME}}_mcp.tools",
    "{{NAME}}_mcp.tools.example_tool",
    "{{NAME}}_mcp.tools.get_job_status",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name):
    """Each module should import without raising."""
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_version_string():
    """Package exposes a __version__ attribute."""
    from {{NAME}}_mcp import __version__
    assert isinstance(__version__, str)
    assert __version__  # non-empty


def test_app_instance():
    """FastAPI app can be imported."""
    from {{NAME}}_mcp.app import app
    assert app is not None
    assert app.title == "{{DISPLAY_NAME}} MCP Server"


def test_mcp_instance():
    """FastMCP instance is accessible."""
    from {{NAME}}_mcp.server import mcp
    assert mcp is not None


def test_settings_instance():
    """Settings singleton is accessible."""
    from {{NAME}}_mcp.config import settings
    assert settings is not None
    assert settings.port == {{MCP_PORT}}
