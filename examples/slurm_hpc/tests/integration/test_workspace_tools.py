"""Integration tests for workspace management tools with real SSH.

These tests make REAL SSH calls to deception.pnl.gov. They are guarded by:
1. Network reachability probe (socket connect to port 22)
2. SSH key existence check (key must be provisioned)

The test creates a unique session workspace, exercises list/upload/read/download,
then cleans up the remote directory. All operations are scoped to a throw-away
session ID to avoid polluting the cluster.
"""

import os
import socket
import tempfile
import uuid

import pytest


# --- Network probe ---

def _can_reach(host: str, port: int = 22, timeout: float = 3.0) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


DECEPTION_REACHABLE = _can_reach("deception.pnl.gov", 22)

skip_deception = pytest.mark.skipif(
    not DECEPTION_REACHABLE,
    reason="Cannot reach deception.pnl.gov:22 (not on PNNL network)",
)


def _deception_key_exists() -> bool:
    from slurm_mcp.deception.config import deception_config
    return deception_config.resolved_ssh_key_path.exists()


# --- Fixtures ---

@pytest.fixture(scope="module")
def session_id():
    """Generate a unique session ID for workspace isolation."""
    return f"integration_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="module")
def ssh_transport():
    """Create a real FabricSSHTransport to Deception (module-scoped)."""
    from slurm_mcp.deception.config import deception_config
    from slurm_mcp.fabric_transport import FabricSSHTransport

    if not deception_config.resolved_ssh_key_path.exists():
        pytest.skip("SSH key not provisioned for Deception")

    transport = FabricSSHTransport(deception_config)
    yield transport


@pytest.fixture(scope="module")
def workspace_dir(session_id):
    return f"~/adept-workspace/{session_id}"


# --- Test class ---

@skip_deception
class TestWorkspaceToolsReal:
    """Integration tests for workspace tools using real SSH to Deception."""

    @pytest.mark.asyncio
    async def test_list_empty_workspace(self, ssh_transport, session_id):
        """Listing a non-existent workspace returns empty status."""
        from slurm_mcp.workspace_tools import (
            WorkspaceListRequest,
            workspace_list_files,
        )

        if not _deception_key_exists():
            pytest.skip("SSH key not provisioned")

        fn = workspace_list_files.fn if hasattr(workspace_list_files, "fn") else workspace_list_files
        req = WorkspaceListRequest(cluster="deception", session_id=session_id)
        result = await fn(req)

        assert result["status"] == "empty"
        assert result["file_count"] == 0

    @pytest.mark.asyncio
    async def test_upload_and_list(self, ssh_transport, session_id, tmp_path):
        """Upload a file then verify it appears in listing."""
        from slurm_mcp.workspace_tools import (
            WorkspaceListRequest,
            WorkspaceUploadRequest,
            workspace_list_files,
            workspace_upload_file,
        )

        if not _deception_key_exists():
            pytest.skip("SSH key not provisioned")

        # Create a local test file in the shared uploads area
        shared_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        session_upload_dir = os.path.join(shared_dir, session_id)
        os.makedirs(session_upload_dir, exist_ok=True)

        test_content = f"integration test data {uuid.uuid4().hex}\n"
        test_file = os.path.join(session_upload_dir, "test_input.txt")
        with open(test_file, "w") as f:
            f.write(test_content)

        try:
            # Upload
            upload_fn = workspace_upload_file.fn if hasattr(workspace_upload_file, "fn") else workspace_upload_file
            req = WorkspaceUploadRequest(
                cluster="deception",
                session_id=session_id,
                local_path=f"{session_id}/test_input.txt",
            )
            result = await upload_fn(req)

            assert result["status"] == "uploaded", f"Upload failed: {result}"
            assert result["size_bytes"] == len(test_content)

            # List
            list_fn = workspace_list_files.fn if hasattr(workspace_list_files, "fn") else workspace_list_files
            list_req = WorkspaceListRequest(cluster="deception", session_id=session_id)
            list_result = await list_fn(list_req)

            assert list_result["status"] == "success"
            assert list_result["file_count"] >= 1
            filenames = [f["name"] for f in list_result["files"]]
            assert "test_input.txt" in filenames

        finally:
            # Cleanup local
            if os.path.exists(test_file):
                os.unlink(test_file)
            if os.path.isdir(session_upload_dir):
                os.rmdir(session_upload_dir)

    @pytest.mark.asyncio
    async def test_read_uploaded_file(self, ssh_transport, session_id):
        """Read a previously uploaded file and verify content."""
        from slurm_mcp.workspace_tools import (
            WorkspaceReadFileRequest,
            workspace_read_file,
        )

        if not _deception_key_exists():
            pytest.skip("SSH key not provisioned")

        read_fn = workspace_read_file.fn if hasattr(workspace_read_file, "fn") else workspace_read_file
        req = WorkspaceReadFileRequest(
            cluster="deception",
            session_id=session_id,
            remote_filename="test_input.txt",
        )
        result = await read_fn(req)

        assert result["status"] == "success"
        assert "integration test data" in result["content"]
        assert result["line_count"] >= 1

    @pytest.mark.asyncio
    async def test_read_with_max_lines(self, ssh_transport, session_id):
        """Read with max_lines limits output."""
        from slurm_mcp.workspace_tools import (
            WorkspaceReadFileRequest,
            workspace_read_file,
        )

        if not _deception_key_exists():
            pytest.skip("SSH key not provisioned")

        read_fn = workspace_read_file.fn if hasattr(workspace_read_file, "fn") else workspace_read_file
        req = WorkspaceReadFileRequest(
            cluster="deception",
            session_id=session_id,
            remote_filename="test_input.txt",
            max_lines=1,
        )
        result = await read_fn(req)

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_download_file(self, ssh_transport, session_id):
        """Download a remote file back to local shared uploads."""
        from slurm_mcp.workspace_tools import (
            WorkspaceDownloadRequest,
            workspace_download_file,
        )

        if not _deception_key_exists():
            pytest.skip("SSH key not provisioned")

        shared_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")

        download_fn = workspace_download_file.fn if hasattr(workspace_download_file, "fn") else workspace_download_file
        req = WorkspaceDownloadRequest(
            cluster="deception",
            session_id=session_id,
            remote_filename="test_input.txt",
            local_filename="downloaded_test.txt",
        )
        result = await download_fn(req)

        assert result["status"] == "downloaded", f"Download failed: {result}"
        assert result["size_bytes"] > 0

        # Verify the file arrived locally
        local_path = os.path.join(shared_dir, session_id, "downloaded_test.txt")
        assert os.path.isfile(local_path)
        with open(local_path) as f:
            content = f.read()
        assert "integration test data" in content

        # Cleanup
        os.unlink(local_path)

    @pytest.mark.asyncio
    async def test_list_nonexistent_subpath(self, ssh_transport, session_id):
        """Listing a nonexistent subpath returns empty."""
        from slurm_mcp.workspace_tools import (
            WorkspaceListRequest,
            workspace_list_files,
        )

        if not _deception_key_exists():
            pytest.skip("SSH key not provisioned")

        list_fn = workspace_list_files.fn if hasattr(workspace_list_files, "fn") else workspace_list_files
        req = WorkspaceListRequest(
            cluster="deception",
            session_id=session_id,
            subpath="nonexistent_dir",
        )
        result = await list_fn(req)

        assert result["status"] == "empty"

    @pytest.mark.asyncio
    async def test_cleanup_workspace(self, ssh_transport, session_id, workspace_dir):
        """Cleanup: remove the test workspace directory from Deception."""
        if not _deception_key_exists():
            pytest.skip("SSH key not provisioned")

        result = ssh_transport._run(
            f"rm -rf {workspace_dir}",
            warn=True,
        )
        assert not result.failed, f"Cleanup failed: {result.stderr}"
