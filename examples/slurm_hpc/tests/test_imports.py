"""
Module Import Tests
===================

Validates that all slurm_mcp modules can be imported without errors.
This catches missing dependencies, circular imports, and import-time exceptions.
"""

import importlib
import os
import sys

import pytest

# Add source to path
SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)


class TestModuleImports:
    """Verify all modules import cleanly."""

    def test_import_config(self):
        """config module imports and SlurmConfig is accessible."""
        from slurm_mcp.config import SlurmConfig, config
        assert SlurmConfig is not None
        assert config is not None

    def test_import_models(self):
        """models module imports with all Pydantic models."""
        from slurm_mcp.models import JobSpec, JobSubmissionRequest, JobListFilters
        assert JobSpec is not None
        assert JobSubmissionRequest is not None
        assert JobListFilters is not None

    def test_import_client(self):
        """client module imports with SlurmClient and JWTTokenManager."""
        from slurm_mcp.client import (
            SlurmClient,
            SlurmError,
            JWTTokenManager,
            get_service_client,
        )
        assert SlurmClient is not None
        assert SlurmError is not None
        assert JWTTokenManager is not None
        assert get_service_client is not None

    def test_import_utils(self):
        """utils module imports with formatting functions."""
        from slurm_mcp.utils import format_job_details, format_job_list
        assert callable(format_job_details)
        assert callable(format_job_list)

    def test_import_app(self):
        """app module imports and FastMCP app is accessible."""
        from slurm_mcp.app import app, main
        assert app is not None
        assert callable(main)

    def test_import_tools(self):
        """tools module imports (registers tool functions with app)."""
        from slurm_mcp import tools
        assert tools is not None

    def test_import_resources(self):
        """resources module imports (registers resources with app)."""
        from slurm_mcp import resources
        assert resources is not None

    def test_import_prompts(self):
        """prompts module imports (registers prompts with app)."""
        from slurm_mcp import prompts
        assert prompts is not None

    def test_import_spiffe_auth(self):
        """spiffe_auth module imports with all public symbols."""
        from slurm_mcp.spiffe_auth import (
            SPIFFE_ENABLED,
            SPIFFE_ENDPOINT_SOCKET,
            get_jwt_svid,
            get_x509_svid,
            get_mtls_ssl_context,
        )
        assert isinstance(SPIFFE_ENABLED, bool)
        assert isinstance(SPIFFE_ENDPOINT_SOCKET, str)
        assert callable(get_jwt_svid)
        assert callable(get_x509_svid)
        assert callable(get_mtls_ssl_context)

    def test_import_identity_mapper(self):
        """identity_mapper module imports with IdentityMapper class."""
        from slurm_mcp.identity_mapper import IdentityMapper, get_identity_mapper
        assert IdentityMapper is not None
        assert callable(get_identity_mapper)

    def test_import_jwt_bridge(self):
        """jwt_bridge module imports with JWTBridge class."""
        from slurm_mcp.jwt_bridge import JWTBridge, JWTBridgeError, get_jwt_bridge
        assert JWTBridge is not None
        assert issubclass(JWTBridgeError, Exception)
        assert callable(get_jwt_bridge)

    def test_import_package_init(self):
        """Package __init__ exports app and main."""
        from slurm_mcp import app, main, __version__
        assert app is not None
        assert callable(main)
        assert isinstance(__version__, str)

    def test_no_auth_import(self):
        """Importing slurm_mcp.auth should fail (module removed)."""
        with pytest.raises(ImportError):
            importlib.import_module("slurm_mcp.auth")

    # --- HPC Cluster Modules (shared + per-cluster) ---

    def test_import_transport_abc(self):
        """Shared transport ABC and dataclasses import."""
        from slurm_mcp.transport import ClusterInfo, JobResult, SlurmTransport
        assert SlurmTransport is not None
        assert JobResult is not None
        assert ClusterInfo is not None

    def test_import_fabric_transport(self):
        """FabricSSHTransport imports with SSHConfig protocol."""
        from slurm_mcp.fabric_transport import FabricSSHTransport, SSHConfig
        assert FabricSSHTransport is not None
        assert SSHConfig is not None

    def test_import_slurm_parsers(self):
        """Shared parsers import all functions."""
        from slurm_mcp.slurm_parsers import (
            build_sbatch_options,
            parse_sacct_json,
            parse_sbatch_output,
            parse_scancel_output,
            parse_sinfo_json,
            parse_squeue_json,
        )
        assert callable(parse_sbatch_output)
        assert callable(build_sbatch_options)

    def test_import_ssh_keys(self):
        """SSH key lifecycle module imports."""
        from slurm_mcp.ssh_keys import (
            check_key_status,
            generate_key_pair,
            get_cluster_key_configs,
            load_clusters_config,
            test_connectivity,
        )
        assert callable(check_key_status)
        assert callable(generate_key_pair)

    def test_import_ssh_key_models(self):
        """SSH key Pydantic models import."""
        from slurm_mcp.ssh_key_models import (
            SSHKeyCheckRequest,
            SSHKeyCheckResponse,
            SSHKeyGenerateRequest,
            SSHKeyGenerateResponse,
        )
        assert SSHKeyCheckRequest is not None
        assert SSHKeyGenerateResponse is not None

    def test_import_deception_config(self):
        """Deception cluster config imports."""
        from slurm_mcp.deception.config import DeceptionConfig, deception_config
        assert DeceptionConfig is not None
        assert deception_config is not None

    def test_import_deception_models(self):
        """Deception Pydantic models import."""
        from slurm_mcp.deception.models import (
            DeceptionJobSpec,
            DeceptionJobSubmissionRequest,
            DeceptionJobListFilters,
        )
        assert DeceptionJobSpec is not None

    def test_import_tahoma_config(self):
        """Tahoma cluster config imports."""
        from slurm_mcp.tahoma.config import TahomaConfig, tahoma_config
        assert TahomaConfig is not None
        assert tahoma_config is not None

    def test_import_tahoma_models(self):
        """Tahoma Pydantic models import."""
        from slurm_mcp.tahoma.models import (
            TahomaJobSpec,
            TahomaJobSubmissionRequest,
            TahomaJobListFilters,
        )
        assert TahomaJobSpec is not None


class TestDependencyAvailability:
    """Verify required third-party packages are importable."""

    @pytest.mark.parametrize(
        "module_name",
        [
            "fastmcp",
            "httpx",
            "pydantic",
            "pydantic_settings",
            "fabric",
            "yaml",
        ],
    )
    def test_dependency_importable(self, module_name):
        """Required dependency should be importable."""
        mod = importlib.import_module(module_name)
        assert mod is not None

    def test_pyjwt_importable(self):
        """PyJWT should be importable (for JWTTokenManager)."""
        import jwt
        assert jwt is not None
        assert hasattr(jwt, "encode")
        assert hasattr(jwt, "decode")
