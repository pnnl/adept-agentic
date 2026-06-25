"""E2E tests for workspace management tools across all cluster targets.

Tests workspace_list_files, workspace_upload_file, workspace_download_file,
and workspace_read_file against:
  - Built-in (local Docker Slurm cluster via docker exec)
  - Deception (SSH to deception.pnl.gov — opt-in, requires key + network)
  - Tahoma (SSH to tahoma.emsl.pnl.gov — opt-in, requires key + password + network)

Guards:
  - Built-in tests require SLURM_CLUSTER_RUNNING=1 (local Docker Slurm stack)
  - Deception tests require DECEPTION_E2E_ENABLED=true + SSH key + network
  - Tahoma tests require TAHOMA_E2E_ENABLED=true + SSH key + password + network

Usage:
    # Built-in workspace tests (local stack must be running)
    SLURM_CLUSTER_RUNNING=1 pytest tests/e2e/test_workspace_tools_e2e.py::TestWorkspaceBuiltIn -v

    # Deception workspace tests (opt-in)
    DECEPTION_E2E_ENABLED=true pytest tests/e2e/test_workspace_tools_e2e.py::TestWorkspaceDeception -v

    # Tahoma workspace tests (opt-in)
    TAHOMA_E2E_ENABLED=true pytest tests/e2e/test_workspace_tools_e2e.py::TestWorkspaceTahoma -v

    # Via Makefile:
    make test-workspace-e2e
"""

import asyncio
import os
import socket
import subprocess
import tempfile
import uuid

import pytest

# ---------------------------------------------------------------------------
# Guard flags
# ---------------------------------------------------------------------------

SLURM_CLUSTER_RUNNING = os.environ.get("SLURM_CLUSTER_RUNNING", "") == "1"
DECEPTION_E2E_ENABLED = os.getenv("DECEPTION_E2E_ENABLED", "false").lower() == "true"
TAHOMA_E2E_ENABLED = os.getenv("TAHOMA_E2E_ENABLED", "false").lower() == "true"

TEST_SESSION_ID = f"e2e_workspace_{uuid.uuid4().hex[:8]}"


def _can_reach(host: str, port: int = 22) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=3.0)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


skip_no_slurm = pytest.mark.skipif(
    not SLURM_CLUSTER_RUNNING,
    reason="SLURM_CLUSTER_RUNNING not set (local Slurm stack not running)",
)

skip_deception = pytest.mark.skipif(
    not DECEPTION_E2E_ENABLED,
    reason="DECEPTION_E2E_ENABLED not set to 'true' (opt-in required)",
)

skip_deception_network = pytest.mark.skipif(
    not _can_reach("deception.pnl.gov") if DECEPTION_E2E_ENABLED else True,
    reason="Cannot reach deception.pnl.gov:22",
)

skip_tahoma = pytest.mark.skipif(
    not TAHOMA_E2E_ENABLED,
    reason="TAHOMA_E2E_ENABLED not set to 'true' (opt-in required)",
)

skip_tahoma_network = pytest.mark.skipif(
    not _can_reach("tahoma.emsl.pnl.gov") if TAHOMA_E2E_ENABLED else True,
    reason="Cannot reach tahoma.emsl.pnl.gov:22",
)


# ---------------------------------------------------------------------------
# Built-In Cluster Workspace Tests
# ---------------------------------------------------------------------------


@skip_no_slurm
class TestWorkspaceBuiltIn:
    """Workspace tool E2E for the built-in local Docker Slurm cluster.

    Since the workspace tools operate over SSH and the built-in cluster
    uses docker exec (not SSH), these tests validate the workspace lifecycle
    by directly exercising the Slurm containers:
      - Create a workspace directory on slurmctld
      - Write a file
      - List files
      - Read file content
      - Download (copy out)

    This validates the workspace directory convention (~/adept-workspace/{session_id}/)
    independent of SSH transport.
    """

    @pytest.fixture(autouse=True)
    def setup_workspace(self):
        """Create and clean up workspace directory on slurmctld."""
        workspace = f"/home/slurm/adept-workspace/{TEST_SESSION_ID}"
        subprocess.run(
            ["docker", "exec", "slurmctld", "mkdir", "-p", workspace],
            check=True,
            timeout=10,
        )
        yield workspace
        subprocess.run(
            ["docker", "exec", "slurmctld", "rm", "-rf", workspace],
            timeout=10,
        )

    def test_workspace_create_and_list(self, setup_workspace):
        """Create a file in workspace and list it."""
        workspace = setup_workspace
        test_content = f"echo 'E2E test {TEST_SESSION_ID}'"
        test_file = f"{workspace}/test_script.sh"

        result = subprocess.run(
            ["docker", "exec", "slurmctld", "bash", "-c",
             f"echo '{test_content}' > {test_file}"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

        result = subprocess.run(
            ["docker", "exec", "slurmctld", "ls", "-la", workspace],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "test_script.sh" in result.stdout

    def test_workspace_read_file_content(self, setup_workspace):
        """Write and read file content from workspace."""
        workspace = setup_workspace
        expected = "Hello from ADEPT workspace E2E test"
        test_file = f"{workspace}/output.txt"

        subprocess.run(
            ["docker", "exec", "slurmctld", "bash", "-c",
             f"echo '{expected}' > {test_file}"],
            check=True, timeout=10,
        )

        result = subprocess.run(
            ["docker", "exec", "slurmctld", "cat", test_file],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert expected in result.stdout

    def test_workspace_subdirectory(self, setup_workspace):
        """Create and list files in a subdirectory."""
        workspace = setup_workspace
        subdir = f"{workspace}/output"

        subprocess.run(
            ["docker", "exec", "slurmctld", "mkdir", "-p", subdir],
            check=True, timeout=10,
        )
        subprocess.run(
            ["docker", "exec", "slurmctld", "bash", "-c",
             f"echo 'results' > {subdir}/results.csv"],
            check=True, timeout=10,
        )

        result = subprocess.run(
            ["docker", "exec", "slurmctld", "ls", subdir],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "results.csv" in result.stdout

    def test_workspace_isolation(self, setup_workspace):
        """Verify workspace is isolated per session_id."""
        workspace = setup_workspace
        other_session = f"/home/slurm/adept-workspace/other_session_{uuid.uuid4().hex[:8]}"

        subprocess.run(
            ["docker", "exec", "slurmctld", "mkdir", "-p", other_session],
            check=True, timeout=10,
        )
        subprocess.run(
            ["docker", "exec", "slurmctld", "bash", "-c",
             f"echo 'other' > {other_session}/private.txt"],
            check=True, timeout=10,
        )

        result = subprocess.run(
            ["docker", "exec", "slurmctld", "ls", workspace],
            capture_output=True, text=True, timeout=10,
        )
        assert "private.txt" not in result.stdout

        subprocess.run(
            ["docker", "exec", "slurmctld", "rm", "-rf", other_session],
            timeout=10,
        )


# ---------------------------------------------------------------------------
# Deception Cluster Workspace Tests
# ---------------------------------------------------------------------------


@skip_deception
@skip_deception_network
class TestWorkspaceDeception:
    """Workspace tool E2E for Deception cluster (SSH transport).

    Full lifecycle: upload -> list -> read -> download.
    Requires SSH key provisioned at the path in deception config.
    """

    @pytest.fixture
    def transport(self):
        from slurm_mcp.deception.config import deception_config
        from slurm_mcp.fabric_transport import FabricSSHTransport

        if not deception_config.resolved_ssh_key_path.exists():
            pytest.skip("SSH key not provisioned for Deception")
        t = FabricSSHTransport(deception_config)
        yield t
        try:
            loop = asyncio.get_running_loop()
            loop.run_until_complete(t.close())
        except RuntimeError:
            asyncio.run(t.close())

    @pytest.fixture
    def session_id(self):
        return TEST_SESSION_ID

    @pytest.fixture(autouse=True)
    def cleanup_workspace(self, transport, session_id):
        """Clean up the test workspace after tests complete."""
        yield
        transport._run(f"rm -rf ~/adept-workspace/{session_id}", warn=True)

    @pytest.mark.asyncio
    async def test_workspace_list_empty(self, transport, session_id):
        """Listing a non-existent workspace returns empty/not-found."""
        from slurm_mcp.workspace_tools import (
            WorkspaceListRequest,
            workspace_list_files,
        )

        fn = workspace_list_files.fn if hasattr(workspace_list_files, "fn") else workspace_list_files
        req = WorkspaceListRequest(cluster="deception", session_id=session_id)
        result = await fn(req)
        assert result["status"] in ("empty", "success")
        assert result["file_count"] == 0

    @pytest.mark.asyncio
    async def test_workspace_upload_and_list(self, transport, session_id):
        """Upload a file to workspace and verify it appears in listing."""
        from slurm_mcp.workspace_tools import (
            WorkspaceListRequest,
            WorkspaceUploadRequest,
            workspace_list_files,
            workspace_upload_file,
        )

        upload_fn = workspace_upload_file.fn if hasattr(workspace_upload_file, "fn") else workspace_upload_file
        list_fn = workspace_list_files.fn if hasattr(workspace_list_files, "fn") else workspace_list_files

        shared_dir = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        session_dir = os.path.join(shared_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)

        test_file = os.path.join(session_dir, "test_input.txt")
        with open(test_file, "w") as f:
            f.write(f"E2E test data for Deception: {session_id}\n")

        try:
            req = WorkspaceUploadRequest(
                cluster="deception",
                session_id=session_id,
                local_path=f"{session_id}/test_input.txt",
            )
            result = await upload_fn(req)
            assert result["status"] == "uploaded", f"Upload failed: {result}"
            assert result["size_bytes"] > 0

            list_req = WorkspaceListRequest(cluster="deception", session_id=session_id)
            list_result = await list_fn(list_req)
            assert list_result["status"] == "success"
            assert list_result["file_count"] >= 1
            filenames = [f["name"] for f in list_result["files"]]
            assert "test_input.txt" in filenames
        finally:
            os.unlink(test_file)
            os.rmdir(session_dir)

    @pytest.mark.asyncio
    async def test_workspace_read_file(self, transport, session_id):
        """Upload a file and read its content back."""
        from slurm_mcp.workspace_tools import (
            WorkspaceReadFileRequest,
            WorkspaceUploadRequest,
            workspace_read_file,
            workspace_upload_file,
        )

        upload_fn = workspace_upload_file.fn if hasattr(workspace_upload_file, "fn") else workspace_upload_file
        read_fn = workspace_read_file.fn if hasattr(workspace_read_file, "fn") else workspace_read_file

        shared_dir = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        session_dir = os.path.join(shared_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)

        expected_content = f"Line 1: Hello from E2E\nLine 2: session={session_id}\n"
        test_file = os.path.join(session_dir, "readable.txt")
        with open(test_file, "w") as f:
            f.write(expected_content)

        try:
            upload_req = WorkspaceUploadRequest(
                cluster="deception",
                session_id=session_id,
                local_path=f"{session_id}/readable.txt",
            )
            await upload_fn(upload_req)

            read_req = WorkspaceReadFileRequest(
                cluster="deception",
                session_id=session_id,
                remote_filename="readable.txt",
            )
            result = await read_fn(read_req)
            assert result["status"] == "success", f"Read failed: {result}"
            assert "Hello from E2E" in result["content"]
            assert result["line_count"] >= 2
        finally:
            os.unlink(test_file)
            os.rmdir(session_dir)

    @pytest.mark.asyncio
    async def test_workspace_download_file(self, transport, session_id):
        """Upload a file, then download it back and verify content."""
        from slurm_mcp.workspace_tools import (
            WorkspaceDownloadRequest,
            WorkspaceUploadRequest,
            workspace_download_file,
            workspace_upload_file,
        )

        upload_fn = workspace_upload_file.fn if hasattr(workspace_upload_file, "fn") else workspace_upload_file
        download_fn = workspace_download_file.fn if hasattr(workspace_download_file, "fn") else workspace_download_file

        shared_dir = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        session_dir = os.path.join(shared_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)

        original_content = f"Download test content: {session_id}\n"
        test_file = os.path.join(session_dir, "download_test.txt")
        with open(test_file, "w") as f:
            f.write(original_content)

        try:
            upload_req = WorkspaceUploadRequest(
                cluster="deception",
                session_id=session_id,
                local_path=f"{session_id}/download_test.txt",
            )
            await upload_fn(upload_req)

            os.unlink(test_file)

            download_req = WorkspaceDownloadRequest(
                cluster="deception",
                session_id=session_id,
                remote_filename="download_test.txt",
                local_filename="downloaded_output.txt",
            )
            result = await download_fn(download_req)
            assert result["status"] == "downloaded", f"Download failed: {result}"
            assert result["size_bytes"] > 0

            downloaded_path = os.path.join(shared_dir, result["local_path"])
            assert os.path.isfile(downloaded_path)
            with open(downloaded_path) as f:
                assert original_content in f.read()

            os.unlink(downloaded_path)
        finally:
            if os.path.exists(test_file):
                os.unlink(test_file)
            if os.path.isdir(session_dir):
                for f in os.listdir(session_dir):
                    os.unlink(os.path.join(session_dir, f))
                os.rmdir(session_dir)


# ---------------------------------------------------------------------------
# Tahoma Cluster Workspace Tests
# ---------------------------------------------------------------------------


@skip_tahoma
@skip_tahoma_network
class TestWorkspaceTahoma:
    """Workspace tool E2E for Tahoma cluster (SSH transport with 2FA).

    Full lifecycle: upload -> list -> read -> download.
    Requires SSH key AND TAHOMA_PASSWORD environment variable.
    """

    @pytest.fixture
    def transport(self):
        from slurm_mcp.fabric_transport import FabricSSHTransport
        from slurm_mcp.tahoma.config import tahoma_config

        if not tahoma_config.resolved_ssh_key_path.exists():
            pytest.skip("SSH key not provisioned for Tahoma")
        if not tahoma_config.password:
            pytest.skip("TAHOMA_PASSWORD not set (required for 2FA)")
        t = FabricSSHTransport(tahoma_config)
        yield t
        try:
            loop = asyncio.get_running_loop()
            loop.run_until_complete(t.close())
        except RuntimeError:
            asyncio.run(t.close())

    @pytest.fixture
    def session_id(self):
        return TEST_SESSION_ID

    @pytest.fixture(autouse=True)
    def cleanup_workspace(self, transport, session_id):
        """Clean up the test workspace after tests complete."""
        yield
        transport._run(f"rm -rf ~/adept-workspace/{session_id}", warn=True)

    @pytest.mark.asyncio
    async def test_workspace_list_empty(self, transport, session_id):
        """Listing a non-existent workspace returns empty."""
        from slurm_mcp.workspace_tools import (
            WorkspaceListRequest,
            workspace_list_files,
        )

        fn = workspace_list_files.fn if hasattr(workspace_list_files, "fn") else workspace_list_files
        req = WorkspaceListRequest(cluster="tahoma", session_id=session_id)
        result = await fn(req)
        assert result["status"] in ("empty", "success")
        assert result["file_count"] == 0

    @pytest.mark.asyncio
    async def test_workspace_upload_and_list(self, transport, session_id):
        """Upload a file to Tahoma workspace and verify listing."""
        from slurm_mcp.workspace_tools import (
            WorkspaceListRequest,
            WorkspaceUploadRequest,
            workspace_list_files,
            workspace_upload_file,
        )

        upload_fn = workspace_upload_file.fn if hasattr(workspace_upload_file, "fn") else workspace_upload_file
        list_fn = workspace_list_files.fn if hasattr(workspace_list_files, "fn") else workspace_list_files

        shared_dir = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        session_dir = os.path.join(shared_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)

        test_file = os.path.join(session_dir, "tahoma_input.txt")
        with open(test_file, "w") as f:
            f.write(f"E2E test data for Tahoma: {session_id}\n")

        try:
            req = WorkspaceUploadRequest(
                cluster="tahoma",
                session_id=session_id,
                local_path=f"{session_id}/tahoma_input.txt",
            )
            result = await upload_fn(req)
            assert result["status"] == "uploaded", f"Upload failed: {result}"
            assert result["size_bytes"] > 0

            list_req = WorkspaceListRequest(cluster="tahoma", session_id=session_id)
            list_result = await list_fn(list_req)
            assert list_result["status"] == "success"
            assert list_result["file_count"] >= 1
            filenames = [f["name"] for f in list_result["files"]]
            assert "tahoma_input.txt" in filenames
        finally:
            os.unlink(test_file)
            os.rmdir(session_dir)

    @pytest.mark.asyncio
    async def test_workspace_read_file(self, transport, session_id):
        """Upload and read file content on Tahoma."""
        from slurm_mcp.workspace_tools import (
            WorkspaceReadFileRequest,
            WorkspaceUploadRequest,
            workspace_read_file,
            workspace_upload_file,
        )

        upload_fn = workspace_upload_file.fn if hasattr(workspace_upload_file, "fn") else workspace_upload_file
        read_fn = workspace_read_file.fn if hasattr(workspace_read_file, "fn") else workspace_read_file

        shared_dir = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        session_dir = os.path.join(shared_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)

        expected_content = f"Tahoma E2E content\nsession={session_id}\n"
        test_file = os.path.join(session_dir, "tahoma_read.txt")
        with open(test_file, "w") as f:
            f.write(expected_content)

        try:
            upload_req = WorkspaceUploadRequest(
                cluster="tahoma",
                session_id=session_id,
                local_path=f"{session_id}/tahoma_read.txt",
            )
            await upload_fn(upload_req)

            read_req = WorkspaceReadFileRequest(
                cluster="tahoma",
                session_id=session_id,
                remote_filename="tahoma_read.txt",
            )
            result = await read_fn(read_req)
            assert result["status"] == "success", f"Read failed: {result}"
            assert "Tahoma E2E content" in result["content"]
            assert result["line_count"] >= 2
        finally:
            os.unlink(test_file)
            os.rmdir(session_dir)

    @pytest.mark.asyncio
    async def test_workspace_download_file(self, transport, session_id):
        """Upload, then download and verify content from Tahoma."""
        from slurm_mcp.workspace_tools import (
            WorkspaceDownloadRequest,
            WorkspaceUploadRequest,
            workspace_download_file,
            workspace_upload_file,
        )

        upload_fn = workspace_upload_file.fn if hasattr(workspace_upload_file, "fn") else workspace_upload_file
        download_fn = workspace_download_file.fn if hasattr(workspace_download_file, "fn") else workspace_download_file

        shared_dir = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        session_dir = os.path.join(shared_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)

        original_content = f"Tahoma download test: {session_id}\n"
        test_file = os.path.join(session_dir, "tahoma_dl.txt")
        with open(test_file, "w") as f:
            f.write(original_content)

        try:
            upload_req = WorkspaceUploadRequest(
                cluster="tahoma",
                session_id=session_id,
                local_path=f"{session_id}/tahoma_dl.txt",
            )
            await upload_fn(upload_req)

            os.unlink(test_file)

            download_req = WorkspaceDownloadRequest(
                cluster="tahoma",
                session_id=session_id,
                remote_filename="tahoma_dl.txt",
                local_filename="tahoma_downloaded.txt",
            )
            result = await download_fn(download_req)
            assert result["status"] == "downloaded", f"Download failed: {result}"
            assert result["size_bytes"] > 0

            downloaded_path = os.path.join(shared_dir, result["local_path"])
            assert os.path.isfile(downloaded_path)
            with open(downloaded_path) as f:
                assert original_content in f.read()

            os.unlink(downloaded_path)
        finally:
            if os.path.exists(test_file):
                os.unlink(test_file)
            if os.path.isdir(session_dir):
                for f in os.listdir(session_dir):
                    os.unlink(os.path.join(session_dir, f))
                os.rmdir(session_dir)
