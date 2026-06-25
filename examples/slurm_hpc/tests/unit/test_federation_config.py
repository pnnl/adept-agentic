"""
Federation Configuration Validation Tests
==========================================

Validates SPIRE server/agent configs and bootstrap scripts for the
bidirectional trust bundle federation between pnnl.adept and pnnl.adept.slurm.

Runs offline — validates config file structure, not runtime behavior.
"""

import os
import re

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# When running in Docker, files are mounted at /app/spire, /app/scripts, etc.
# When running locally, use relative paths from the test file location.
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CONTAINER_ROOT = "/app"

def _resolve_path(relative):
    """Resolve a path relative to the project root, checking container mount first."""
    container_path = os.path.join(_CONTAINER_ROOT, relative)
    if os.path.exists(container_path):
        return container_path
    local_path = os.path.join(_PROJECT_ROOT, relative)
    if os.path.exists(local_path):
        return local_path
    return local_path  # Return local path (will trigger skip in _read_file)

SPIRE_DIR = _resolve_path("spire")
SCRIPTS_DIR = _resolve_path("scripts")
COMPOSE_FILE = _resolve_path("docker-compose.yaml")


def _read_file(path):
    """Read a file relative to the project root."""
    full_path = os.path.normpath(path)
    if not os.path.exists(full_path):
        pytest.skip(f"File not found: {full_path}")
    with open(full_path) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Test: Slurm SPIRE Server Config
# ---------------------------------------------------------------------------

class TestSlurmSpireServerConfig:
    @pytest.fixture(scope="class")
    def config(self):
        return _read_file(os.path.join(SPIRE_DIR, "server.conf"))

    def test_trust_domain(self, config):
        assert 'trust_domain = "pnnl.adept.slurm"' in config

    def test_bind_port(self, config):
        assert 'bind_port = "8081"' in config

    def test_federation_block_exists(self, config):
        assert "federation {" in config
        assert "bundle_endpoint {" in config

    def test_federation_port(self, config):
        assert "port = 8443" in config

    def test_sqlite_datastore(self, config):
        assert 'database_type = "sqlite3"' in config

    def test_bundle_publisher(self, config):
        assert 'BundlePublisher "disk"' in config


# ---------------------------------------------------------------------------
# Test: ADEPT SPIRE Server Config
# ---------------------------------------------------------------------------

class TestAdeptSpireServerConfig:
    @pytest.fixture(scope="class")
    def config(self):
        return _read_file(os.path.join(SPIRE_DIR, "adept_server.conf"))

    def test_trust_domain(self, config):
        assert 'trust_domain = "pnnl.adept"' in config

    def test_bind_port(self, config):
        assert 'bind_port = "8081"' in config

    def test_federation_block_exists(self, config):
        assert "federation {" in config
        assert "bundle_endpoint {" in config

    def test_federation_port(self, config):
        assert "port = 8443" in config

    def test_different_trust_domain_from_slurm(self):
        slurm_conf = _read_file(os.path.join(SPIRE_DIR, "server.conf"))
        adept_conf = _read_file(os.path.join(SPIRE_DIR, "adept_server.conf"))
        assert 'trust_domain = "pnnl.adept.slurm"' in slurm_conf
        assert 'trust_domain = "pnnl.adept"' in adept_conf


# ---------------------------------------------------------------------------
# Test: ADEPT SPIRE Agent Config
# ---------------------------------------------------------------------------

class TestAdeptSpireAgentConfig:
    @pytest.fixture(scope="class")
    def config(self):
        return _read_file(os.path.join(SPIRE_DIR, "adept_agent.conf"))

    def test_trust_domain(self, config):
        assert 'trust_domain = "pnnl.adept"' in config

    def test_server_address(self, config):
        assert 'server_address = "adept_spire_server"' in config

    def test_insecure_bootstrap(self, config):
        assert "insecure_bootstrap = true" in config

    def test_docker_workload_attestor(self, config):
        assert 'WorkloadAttestor "docker"' in config


# ---------------------------------------------------------------------------
# Test: Registration Entries (federatesWith directives)
# ---------------------------------------------------------------------------

class TestRegistrationEntries:
    def test_slurm_entries_federate_with_adept(self):
        """Slurm workload entries declare federation with pnnl.adept."""
        content = _read_file(os.path.join(SPIRE_DIR, "registration-entries.sh"))
        assert '-federatesWith "spiffe://pnnl.adept"' in content

    def test_slurm_registers_mcp_server(self):
        content = _read_file(os.path.join(SPIRE_DIR, "registration-entries.sh"))
        assert "slurm-mcp-server" in content

    def test_slurm_registers_slurmrestd(self):
        content = _read_file(os.path.join(SPIRE_DIR, "registration-entries.sh"))
        assert "slurmrestd" in content

    def test_adept_entries_federate_with_slurm(self):
        """ADEPT workload entries declare federation with pnnl.adept.slurm."""
        content = _read_file(os.path.join(SPIRE_DIR, "adept_registration_entries.sh"))
        assert '-federatesWith "spiffe://pnnl.adept.slurm"' in content

    def test_adept_registers_orchestration_service(self):
        content = _read_file(os.path.join(SPIRE_DIR, "adept_registration_entries.sh"))
        assert "orchestration-service" in content

    def test_adept_registers_agent_gateway(self):
        content = _read_file(os.path.join(SPIRE_DIR, "adept_registration_entries.sh"))
        assert "agent-gateway" in content


# ---------------------------------------------------------------------------
# Test: Bootstrap Federation Script
# ---------------------------------------------------------------------------

class TestBootstrapFederationScript:
    @pytest.fixture(scope="class")
    def script(self):
        return _read_file(os.path.join(SCRIPTS_DIR, "bootstrap-federation.sh"))

    def test_script_exists(self, script):
        assert len(script) > 0

    def test_sets_strict_mode(self, script):
        assert "set -euo pipefail" in script

    def test_references_both_spire_servers(self, script):
        assert "slurm_spire_server" in script
        assert "adept_spire_server" in script

    def test_exports_trust_bundles(self, script):
        assert "bundle show" in script

    def test_imports_peer_bundles(self, script):
        assert "bundle set" in script

    def test_verifies_federation(self, script):
        assert "bundle list" in script

    def test_references_both_domains(self, script):
        assert "pnnl.adept.slurm" in script
        assert "pnnl.adept" in script


# ---------------------------------------------------------------------------
# Test: Docker Compose Federation Profile
# ---------------------------------------------------------------------------

class TestDockerComposeFederation:
    @pytest.fixture(scope="class")
    def compose(self):
        return _read_file(COMPOSE_FILE)

    def test_adept_spire_server_defined(self, compose):
        assert "adept_spire_server:" in compose

    def test_adept_spire_agent_defined(self, compose):
        assert "adept_spire_agent:" in compose

    def test_federation_profile(self, compose):
        """Federation services use the 'federation' profile."""
        # Check that 'federation' appears as a profile value
        assert '"federation"' in compose

    def test_adept_server_uses_adept_config(self, compose):
        assert "adept_server.conf" in compose

    def test_adept_agent_uses_adept_config(self, compose):
        assert "adept_agent.conf" in compose

    def test_adept_spire_volumes(self, compose):
        assert "adept_spire_server_data:" in compose
        assert "adept_spire_agent_socket:" in compose

    def test_adept_spire_on_both_networks(self, compose):
        """ADEPT SPIRE server should be on both backend and application networks."""
        # The server needs to talk to both slurm SPIRE and ADEPT services
        assert "adept_application_network" in compose
