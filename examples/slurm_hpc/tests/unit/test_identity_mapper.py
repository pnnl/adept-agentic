"""
Unit Tests: Identity Mapper
============================

Tests for identity_mapper.py — Globus/ADEPT -> Slurm username mapping.
All tests run offline (no services required).
"""

import json
import os
import sys

import pytest

SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)

from slurm_mcp.identity_mapper import IdentityMapper


@pytest.fixture
def mapping_file(tmp_path):
    """Create a temporary identity mapping file."""
    data = {
        "mappings": {
            "alice@pnnl.gov": "alice",
            "bob@anl.gov": "bob",
            "globus-uuid-123": "charlie",
            "kc-sub-456": "dave",
            "admin": "root",
        }
    }
    path = tmp_path / "identity_map.json"
    path.write_text(json.dumps(data))
    return str(path)


@pytest.fixture
def mapper(mapping_file):
    """Create an IdentityMapper with test mappings."""
    return IdentityMapper(mapping_file=mapping_file, fallback_user="nobody")


class TestIdentityMapperInit:
    """Validate IdentityMapper initialization."""

    def test_loads_mapping_file(self, mapping_file):
        """Loads mappings from JSON file."""
        mapper = IdentityMapper(mapping_file=mapping_file)
        assert len(mapper._static_map) == 5

    def test_missing_file_is_not_error(self, tmp_path):
        """Missing mapping file logs info, does not raise."""
        mapper = IdentityMapper(
            mapping_file=str(tmp_path / "nonexistent.json"),
            fallback_user="root",
        )
        assert len(mapper._static_map) == 0

    def test_invalid_json_is_not_error(self, tmp_path):
        """Invalid JSON logs warning, does not raise."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json{{{")
        mapper = IdentityMapper(mapping_file=str(bad_file))
        assert len(mapper._static_map) == 0


class TestIdentityMapperResolve:
    """Validate the 6-priority identity resolution chain."""

    def test_priority_1_slurm_username_claim(self, mapper):
        """Direct slurm_username claim takes highest priority."""
        result = mapper.resolve(slurm_username_claim="explicit_user")
        assert result == "explicit_user"

    def test_priority_2_globus_identity(self, mapper):
        """Globus UUID maps to Slurm username via static map."""
        result = mapper.resolve(globus_identity="globus-uuid-123")
        assert result == "charlie"

    def test_priority_3_email(self, mapper):
        """Email maps to Slurm username via static map."""
        result = mapper.resolve(preferred_username="alice@pnnl.gov")
        assert result == "alice"

    def test_priority_4_keycloak_sub(self, mapper):
        """Keycloak sub maps to Slurm username via static map."""
        result = mapper.resolve(sub="kc-sub-456")
        assert result == "dave"

    def test_priority_5_email_prefix(self, mapper):
        """Unknown email extracts prefix as username."""
        result = mapper.resolve(preferred_username="unknown@example.org")
        assert result == "unknown"

    def test_priority_6_fallback(self, mapper):
        """No identity info falls back to configured user."""
        result = mapper.resolve()
        assert result == "nobody"

    def test_claim_overrides_static_map(self, mapper):
        """slurm_username claim wins even when email has a static mapping."""
        result = mapper.resolve(
            slurm_username_claim="override_user",
            preferred_username="alice@pnnl.gov",
        )
        assert result == "override_user"

    def test_globus_overrides_email(self, mapper):
        """Globus identity wins over email mapping."""
        result = mapper.resolve(
            globus_identity="globus-uuid-123",
            preferred_username="alice@pnnl.gov",
        )
        assert result == "charlie"

    def test_email_overrides_sub(self, mapper):
        """Email mapping wins over Keycloak sub mapping."""
        result = mapper.resolve(
            preferred_username="bob@anl.gov",
            sub="kc-sub-456",
        )
        assert result == "bob"


class TestIdentityMapperSingleton:
    """Validate singleton accessor."""

    def test_get_identity_mapper_returns_instance(self, monkeypatch):
        """get_identity_mapper returns an IdentityMapper."""
        monkeypatch.setenv("SLURM_SERVICE_USER", "testuser")

        import slurm_mcp.identity_mapper as mod
        from slurm_mcp.identity_mapper import get_identity_mapper

        # Reset singleton to force fresh creation
        mod._mapper = None

        mapper = get_identity_mapper()
        assert isinstance(mapper, IdentityMapper)

        # Cleanup
        mod._mapper = None
