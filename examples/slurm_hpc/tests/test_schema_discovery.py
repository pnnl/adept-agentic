"""
MCP Tool Schema Discovery Tests
================================

Validates that the FastMCP app correctly registers all expected tools
and that tool schemas have proper names, descriptions, and parameters.

Aligned with biofoundation_mcp_server/tests/test_schema_discovery.py
canonical pattern. Accesses ToolManager registry directly (fastmcp 2.14+).

Run with: pytest tests/test_schema_discovery.py -v
"""

import inspect
import os
import sys

import pytest

# Ensure slurm_mcp_server source is importable
SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)


EXPECTED_LOCAL_TOOLS = {
    "submit_slurm_job",
    "get_job_details",
    "cancel_slurm_job",
    "ping",
    "list_cluster_jobs",
    "get_cluster_summary",
}

EXPECTED_DECEPTION_TOOLS = {
    "deception_ping",
    "deception_submit_job",
    "deception_get_job_details",
    "deception_cancel_job",
    "deception_list_jobs",
    "deception_get_cluster_summary",
}

EXPECTED_TAHOMA_TOOLS = {
    "tahoma_ping",
    "tahoma_submit_job",
    "tahoma_get_job_details",
    "tahoma_cancel_job",
    "tahoma_list_jobs",
    "tahoma_get_cluster_summary",
}

EXPECTED_SSH_KEY_TOOLS = {
    "hpc_list_clusters",
    "hpc_check_ssh_key",
    "hpc_generate_ssh_key",
    "hpc_test_ssh_connectivity",
    "hpc_get_provisioning_instructions",
}

EXPECTED_WORKSPACE_TOOLS = {
    "workspace_list_files",
    "workspace_upload_file",
    "workspace_download_file",
    "workspace_read_file",
}

EXPECTED_TOOLS = (
    EXPECTED_LOCAL_TOOLS
    | EXPECTED_DECEPTION_TOOLS
    | EXPECTED_TAHOMA_TOOLS
    | EXPECTED_SSH_KEY_TOOLS
    | EXPECTED_WORKSPACE_TOOLS
)


@pytest.fixture(scope="module")
def mcp_app():
    """Get the FastMCP app instance with all tools registered."""
    from slurm_mcp.app import app
    from slurm_mcp import tools  # noqa: F401
    from slurm_mcp.deception import tools as _deception_tools  # noqa: F401
    from slurm_mcp.tahoma import tools as _tahoma_tools  # noqa: F401
    from slurm_mcp import ssh_key_tools as _ssh_key_tools  # noqa: F401
    from slurm_mcp import workspace_tools as _workspace_tools  # noqa: F401
    return app


@pytest.fixture(scope="module")
def tool_map(mcp_app):
    """Map of tool name → FunctionTool object via ToolManager internal registry."""
    return mcp_app._tool_manager._tools


class TestToolDiscovery:
    """Validate FastMCP tool registration via @app.tool decorators."""

    def test_discovers_all_tools(self, tool_map):
        """All 27 SLURM tools are registered."""
        assert EXPECTED_TOOLS.issubset(tool_map.keys()), (
            f"Missing tools: {EXPECTED_TOOLS - tool_map.keys()}"
        )

    def test_tool_count(self, tool_map):
        """Exactly 27 tools registered (6 local + 6 deception + 6 tahoma + 5 ssh_key + 4 workspace)."""
        our_tools = set(tool_map.keys()) & EXPECTED_TOOLS
        assert len(our_tools) == 27

    def test_all_tools_have_descriptions(self, tool_map):
        """Every tool has a non-empty description."""
        for name in EXPECTED_TOOLS:
            tool = tool_map[name]
            assert tool.description, f"{name} has empty description"

    @pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOLS))
    def test_tool_is_callable(self, tool_map, tool_name):
        """Each registered tool has a callable function."""
        tool = tool_map[tool_name]
        assert callable(tool.fn), f"{tool_name} fn is not callable"


class TestSubmitSlurmJobSchema:
    """Validate submit_slurm_job tool schema."""

    def test_has_request_parameter(self, tool_map):
        """submit_slurm_job accepts a JobSubmissionRequest parameter."""
        sig = inspect.signature(tool_map["submit_slurm_job"].fn)
        assert "request" in sig.parameters


class TestGetJobDetailsSchema:
    """Validate get_job_details tool schema."""

    def test_has_job_id_parameter(self, tool_map):
        """get_job_details accepts a job_id string parameter."""
        sig = inspect.signature(tool_map["get_job_details"].fn)
        assert "job_id" in sig.parameters


class TestPingSchema:
    """Validate ping tool has no required user-facing parameters."""

    def test_no_required_params(self, tool_map):
        """ping tool has no parameters."""
        sig = inspect.signature(tool_map["ping"].fn)
        assert len(sig.parameters) == 0


class TestListClusterJobsSchema:
    """Validate list_cluster_jobs tool schema."""

    def test_has_optional_filters(self, tool_map):
        """list_cluster_jobs has an optional filters parameter."""
        sig = inspect.signature(tool_map["list_cluster_jobs"].fn)
        assert "filters" in sig.parameters
        assert sig.parameters["filters"].default is None


class TestGetClusterSummarySchema:
    """Validate get_cluster_summary tool schema."""

    def test_has_optional_partition(self, tool_map):
        """get_cluster_summary has an optional partition parameter."""
        sig = inspect.signature(tool_map["get_cluster_summary"].fn)
        assert "partition" in sig.parameters
        assert sig.parameters["partition"].default is None


class TestRegistrationSchemaDrift:
    """Validate tool_registry.json contract via Pydantic round-trip.

    This prevents the class of bug where a Python function declares a parameter
    (e.g., mcp_session_id) but the registration schema doesn't include it,
    causing LangChain to silently strip it during validation.

    Run `make generate-schemas` to fix any drift detected by this test.
    """

    def test_generated_registry_validates(self, mcp_app):
        """Generated ToolRegistry passes Pydantic validation and round-trips cleanly."""
        scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
        gen_mod_path = os.path.join(scripts_dir, "generate-registration-schemas.py")

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "generate_registration_schemas", gen_mod_path
        )
        gen_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen_mod)

        registry = gen_mod.generate_registry(mcp_app)
        assert len(registry.tools) == 27, (
            f"Expected 27 tools, got {len(registry.tools)}"
        )

        serialized = registry.model_dump_json()
        reloaded = gen_mod.ToolRegistry.model_validate_json(serialized)
        assert reloaded == registry, "Round-trip serialization mismatch"

    def test_all_tools_have_registered_names(self, mcp_app):
        """Every tool entry has a non-empty registered_name with the correct prefix."""
        scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
        gen_mod_path = os.path.join(scripts_dir, "generate-registration-schemas.py")

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "generate_registration_schemas", gen_mod_path
        )
        gen_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen_mod)

        registry = gen_mod.generate_registry(mcp_app)
        for entry in registry.tools:
            assert entry.registered_name.startswith("slurm_hpc_"), (
                f"{entry.remote_name} has wrong prefix: {entry.registered_name}"
            )
