"""Tier 1: Validate tool schema extraction from Pydantic Field annotations."""

import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR.parent))


class TestSchemaDiscovery:
    """Test that the registration script can discover and extract tool schemas."""

    def _import_register_module(self):
        """Import the registration script as a module."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "register_tools",
            _SCRIPTS_DIR / "register_{{NAME}}_tools.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_discover_tools_returns_list(self):
        mod = self._import_register_module()
        tools = mod.discover_tools()
        assert isinstance(tools, list)
        assert len(tools) == {{TOOL_COUNT}}

    def test_each_tool_has_name(self):
        mod = self._import_register_module()
        tools = mod.discover_tools()
        for tool in tools:
            assert tool.name, f"Tool missing name: {tool}"
            assert tool.name.startswith("{{NAME}}_")

    def test_each_tool_has_description(self):
        mod = self._import_register_module()
        tools = mod.discover_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} missing description"

    def test_framework_fields_stripped(self):
        """Framework-injected fields must NOT appear in args_schema."""
        mod = self._import_register_module()
        tools = mod.discover_tools()
        framework_fields = {"mcp_session_id", "session_id", "user_context"}
        for tool in tools:
            for field in framework_fields:
                assert field not in tool.args_schema, \
                    f"Framework field '{field}' leaked into {tool.name} schema"

    def test_example_tool_schema_params(self):
        """The example tool should have input_file, model, batch_size params."""
        mod = self._import_register_module()
        tools = mod.discover_tools()
        example = next(t for t in tools if "example" in t.name)
        assert "input_file" in example.args_schema
        assert "model" in example.args_schema
        assert "batch_size" in example.args_schema
        assert example.args_schema["batch_size"]["type"] == "integer"

    def test_example_tool_defaults_preserved(self):
        """Default values from Field() annotations should survive extraction."""
        mod = self._import_register_module()
        tools = mod.discover_tools()
        example = next(t for t in tools if "example" in t.name)
        assert example.args_schema["batch_size"].get("default") == 16
        assert example.args_schema["model"].get("default") == "default"
