"""Integration tests for HPC cluster SSH connectivity.

These tests require actual network access to the clusters.
They are guarded by socket probes — if the cluster is unreachable,
tests are skipped automatically.
"""

import socket
import subprocess

import pytest

# --- Network probe helpers ---


def _can_reach(host: str, port: int = 22, timeout: float = 3.0) -> bool:
    """Check if a TCP connection can be established."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


DECEPTION_REACHABLE = _can_reach("deception.pnl.gov", 22)
TAHOMA_REACHABLE = _can_reach("tahoma.emsl.pnl.gov", 22)

skip_deception = pytest.mark.skipif(
    not DECEPTION_REACHABLE,
    reason="Cannot reach deception.pnl.gov:22 (not on PNNL network)",
)
skip_tahoma = pytest.mark.skipif(
    not TAHOMA_REACHABLE,
    reason="Cannot reach tahoma.emsl.pnl.gov:22 (not on PNNL network)",
)


# --- Deception Integration Tests ---


@skip_deception
class TestDeceptionConnectivity:
    """Integration tests requiring network access to Deception."""

    def test_ssh_key_check(self):
        """Verify key status can be checked against the real config."""
        from slurm_mcp.ssh_keys import check_key_status

        status = check_key_status("deception")
        # May or may not have keys — just verify no crash
        assert status.cluster == "deception"
        assert isinstance(status.private_key_exists, bool)

    @pytest.mark.asyncio
    async def test_ping_via_transport(self):
        """Verify Fabric SSH transport can ping Deception's slurmctld."""
        from slurm_mcp.deception.config import deception_config
        from slurm_mcp.fabric_transport import FabricSSHTransport

        if not deception_config.resolved_ssh_key_path.exists():
            pytest.skip("SSH key not provisioned for Deception")

        transport = FabricSSHTransport(deception_config)
        try:
            result = await transport.ping()
            assert result is True
        finally:
            await transport.close()

    @pytest.mark.asyncio
    async def test_cluster_info(self):
        """Verify sinfo --json returns parseable data."""
        from slurm_mcp.deception.config import deception_config
        from slurm_mcp.fabric_transport import FabricSSHTransport

        if not deception_config.resolved_ssh_key_path.exists():
            pytest.skip("SSH key not provisioned for Deception")

        transport = FabricSSHTransport(deception_config)
        try:
            info = await transport.get_cluster_info()
            assert len(info.nodes) >= 0  # May be empty if cluster is down
            assert isinstance(info.partitions, list)
        finally:
            await transport.close()

    @pytest.mark.asyncio
    async def test_list_jobs_read_only(self):
        """Verify squeue --json works (read-only, no side effects)."""
        from slurm_mcp.deception.config import deception_config
        from slurm_mcp.fabric_transport import FabricSSHTransport

        if not deception_config.resolved_ssh_key_path.exists():
            pytest.skip("SSH key not provisioned for Deception")

        transport = FabricSSHTransport(deception_config)
        try:
            jobs = await transport.list_jobs()
            assert isinstance(jobs, list)
        finally:
            await transport.close()


# --- Tahoma Integration Tests ---


@skip_tahoma
class TestTahomaConnectivity:
    """Integration tests requiring network access to Tahoma."""

    def test_ssh_key_check(self):
        """Verify key status can be checked against the real config."""
        from slurm_mcp.ssh_keys import check_key_status

        status = check_key_status("tahoma")
        assert status.cluster == "tahoma"
        assert isinstance(status.private_key_exists, bool)

    @pytest.mark.asyncio
    async def test_ping_via_transport(self):
        """Verify Fabric SSH transport can ping Tahoma's slurmctld."""
        from slurm_mcp.tahoma.config import tahoma_config
        from slurm_mcp.fabric_transport import FabricSSHTransport

        if not tahoma_config.resolved_ssh_key_path.exists():
            pytest.skip("SSH key not provisioned for Tahoma")
        if not tahoma_config.password:
            pytest.skip("Tahoma requires 2FA (TAHOMA_PASSWORD not set)")

        transport = FabricSSHTransport(tahoma_config)
        try:
            result = await transport.ping()
            assert result is True
        finally:
            await transport.close()

    @pytest.mark.asyncio
    async def test_list_jobs_read_only(self):
        """Verify squeue --json works (read-only, no side effects)."""
        from slurm_mcp.tahoma.config import tahoma_config
        from slurm_mcp.fabric_transport import FabricSSHTransport

        if not tahoma_config.resolved_ssh_key_path.exists():
            pytest.skip("SSH key not provisioned for Tahoma")
        if not tahoma_config.password:
            pytest.skip("Tahoma requires 2FA (TAHOMA_PASSWORD not set)")

        transport = FabricSSHTransport(tahoma_config)
        try:
            jobs = await transport.list_jobs()
            assert isinstance(jobs, list)
        finally:
            await transport.close()
