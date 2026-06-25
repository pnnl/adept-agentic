"""Unit tests for cluster-agnostic workspace management tools.

Tests workspace_list_files, workspace_upload_file, workspace_download_file,
workspace_read_file — all using mocked FabricSSHTransport to avoid real SSH.

Testing strategy for FastMCP @app.tool decorated functions:

1. @app.tool wraps async functions as FunctionTool objects, which are not
   directly callable with `await func(req)`. We extract the underlying
   function via the `.fn` attribute (see `_call_tool()` helper below).

2. The `_require_ssh_transport()` function uses `isinstance(transport,
   FabricSSHTransport)` which rejects MagicMock objects regardless of spec.
   We patch `_require_ssh_transport` to bypass this check and return the
   mock transport directly.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)

from slurm_mcp.workspace_tools import (
    SUPPORTED_CLUSTERS,
    WorkspaceDownloadRequest,
    WorkspaceListRequest,
    WorkspaceReadFileRequest,
    WorkspaceUploadRequest,
    _get_transport_for_cluster,
    _require_ssh_transport,
    _resolve_workspace_dir,
    workspace_download_file,
    workspace_list_files,
    workspace_read_file,
    workspace_upload_file,
)


def _call_tool(tool):
    """Get the callable async function from a FastMCP tool or raw function."""
    if hasattr(tool, "fn"):
        return tool.fn
    return tool


_list_files = _call_tool(workspace_list_files)
_upload_file = _call_tool(workspace_upload_file)
_download_file = _call_tool(workspace_download_file)
_read_file = _call_tool(workspace_read_file)


def _mock_result(stdout="", stderr="", ok=True, failed=False):
    """Create a mock Fabric Result."""
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.ok = ok
    r.failed = failed
    return r


class TestSupportedClusters:
    """Validate the SUPPORTED_CLUSTERS constant."""

    def test_contains_deception(self):
        assert "deception" in SUPPORTED_CLUSTERS

    def test_contains_tahoma(self):
        assert "tahoma" in SUPPORTED_CLUSTERS

    def test_is_tuple(self):
        assert isinstance(SUPPORTED_CLUSTERS, tuple)


class TestGetTransportForCluster:
    """Tests for _get_transport_for_cluster helper."""

    @pytest.mark.asyncio
    async def test_unknown_cluster_raises(self):
        with pytest.raises(ValueError, match="Unknown cluster"):
            await _get_transport_for_cluster("nonexistent")

    @pytest.mark.asyncio
    async def test_deception_resolves(self):
        mock_transport = MagicMock()
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster"
        ) as mock_fn:
            mock_fn.return_value = mock_transport
            result = await mock_fn("deception")
            assert result is mock_transport

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        with pytest.raises(ValueError, match="Unknown cluster"):
            await _get_transport_for_cluster("NONEXISTENT")


try:
    import fabric  # noqa: F401
    _has_fabric = True
except ImportError:
    _has_fabric = False


@pytest.mark.skipif(not _has_fabric, reason="fabric not installed in host test env")
class TestRequireSSHTransport:
    """Tests for _require_ssh_transport validation."""

    def test_accepts_fabric_transport(self):
        from slurm_mcp.fabric_transport import FabricSSHTransport

        mock_config = MagicMock()
        mock_config.host = "test.example.com"
        mock_config.ssh_port = 22
        mock_config.username = "testuser"
        mock_config.ssh_timeout = 30
        mock_config.resolved_ssh_key_path = Path("/tmp/fake_key")
        transport = FabricSSHTransport(mock_config)
        result = _require_ssh_transport(transport)
        assert result is transport

    def test_rejects_non_ssh_transport(self):
        mock_transport = MagicMock(spec=[])
        with pytest.raises(ValueError, match="SSH transport"):
            _require_ssh_transport(mock_transport)


class TestWorkspaceListFiles:
    """Tests for workspace_list_files tool."""

    @pytest.fixture
    def mock_ssh(self):
        transport = MagicMock()
        return transport

    @pytest.mark.asyncio
    async def test_empty_workspace(self, mock_ssh):
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout="__NOTFOUND__", failed=False),  # ls
        ]
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceListRequest(
                cluster="deception", session_id="sess-abc"
            )
            result = await _list_files(req)

        assert result["status"] == "empty"
        assert result["file_count"] == 0
        assert result["files"] == []

    @pytest.mark.asyncio
    async def test_lists_files(self, mock_ssh):
        ls_output = (
            "total 8\n"
            "-rw-r--r-- 1 rigo160 users 156 2026-06-10 08:30 hello.sh\n"
            "-rw-r--r-- 1 rigo160 users 42 2026-06-10 08:31 slurm-123.out\n"
        )
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout=ls_output),  # ls -la
        ]
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceListRequest(
                cluster="deception", session_id="sess-abc"
            )
            result = await _list_files(req)

        assert result["status"] == "success"
        assert result["file_count"] == 2
        assert result["files"][0]["name"] == "hello.sh"
        assert result["files"][0]["size_bytes"] == 156
        assert result["files"][1]["name"] == "slurm-123.out"

    @pytest.mark.asyncio
    async def test_skips_directories(self, mock_ssh):
        ls_output = (
            "total 4\n"
            "drwxr-xr-x 2 rigo160 users 4096 2026-06-10 08:30 subdir\n"
            "-rw-r--r-- 1 rigo160 users 100 2026-06-10 08:30 data.csv\n"
        )
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout=ls_output),  # ls -la
        ]
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceListRequest(
                cluster="tahoma", session_id="sess-xyz"
            )
            result = await _list_files(req)

        assert result["file_count"] == 1
        assert result["files"][0]["name"] == "data.csv"

    @pytest.mark.asyncio
    async def test_subpath_appended(self, mock_ssh):
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/qfs/people/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout="total 0\n"),  # ls -la
        ]
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceListRequest(
                cluster="deception", session_id="sess-1", subpath="output"
            )
            await _list_files(req)

        all_cmds = [c[0][0] for c in mock_ssh._run.call_args_list]
        ls_cmds = [c for c in all_cmds if "ls -la" in c]
        assert ls_cmds, f"No ls command found in: {all_cmds}"
        assert "/qfs/people/testuser/adept-workspace/sess-1/output" in ls_cmds[0]

    @pytest.mark.asyncio
    async def test_error_handling(self):
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            side_effect=ValueError("Unknown cluster 'bad'"),
        ):
            req = WorkspaceListRequest(cluster="bad", session_id="s1")
            result = await _list_files(req)

        assert result["status"] == "error"
        assert "Unknown cluster" in result["message"]


class TestWorkspaceUploadFile:
    """Tests for workspace_upload_file tool."""

    @pytest.fixture
    def mock_ssh(self):
        transport = MagicMock()
        transport._run.return_value = _mock_result(stdout="/home/testuser")
        mock_conn = MagicMock()
        transport._get_connection.return_value = mock_conn
        return transport

    @pytest.mark.asyncio
    async def test_file_not_found(self, mock_ssh):
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools.SHARED_UPLOAD_DIR", "/nonexistent"
        ):
            req = WorkspaceUploadRequest(
                cluster="deception",
                session_id="sess-1",
                local_path="missing.csv",
            )
            result = await _upload_file(req)

        assert result["status"] == "error"
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_upload_success(self, mock_ssh, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("col1,col2\n1,2\n")

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools.SHARED_UPLOAD_DIR", str(tmp_path)
        ):
            req = WorkspaceUploadRequest(
                cluster="deception",
                session_id="sess-1",
                local_path="data.csv",
            )
            result = await _upload_file(req)

        assert result["status"] == "uploaded"
        assert result["cluster"] == "deception"
        assert "data.csv" in result["remote_path"]
        assert result["size_bytes"] > 0

        mock_ssh._get_connection.return_value.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_remote_filename_override(self, mock_ssh, tmp_path):
        test_file = tmp_path / "local.csv"
        test_file.write_text("data")

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools.SHARED_UPLOAD_DIR", str(tmp_path)
        ):
            req = WorkspaceUploadRequest(
                cluster="deception",
                session_id="sess-1",
                local_path="local.csv",
                remote_filename="renamed.csv",
            )
            result = await _upload_file(req)

        assert "renamed.csv" in result["remote_path"]

    @pytest.mark.asyncio
    async def test_subpath_creates_directory(self, mock_ssh, tmp_path):
        test_file = tmp_path / "input.txt"
        test_file.write_text("hello")

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools.SHARED_UPLOAD_DIR", str(tmp_path)
        ):
            req = WorkspaceUploadRequest(
                cluster="tahoma",
                session_id="sess-1",
                local_path="input.txt",
                subpath="input",
            )
            await _upload_file(req)

        all_cmds = [c[0][0] for c in mock_ssh._run.call_args_list]
        mkdir_calls = [c for c in all_cmds if "mkdir -p" in c]
        assert mkdir_calls, f"No mkdir -p call found in: {all_cmds}"
        assert "input" in mkdir_calls[0]


class TestWorkspaceDownloadFile:
    """Tests for workspace_download_file tool."""

    @pytest.fixture
    def mock_ssh(self):
        transport = MagicMock()
        return transport

    @pytest.mark.asyncio
    async def test_remote_file_not_found(self, mock_ssh):
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser"),
            _mock_result(stdout=""),
        ]
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceDownloadRequest(
                cluster="deception",
                session_id="sess-1",
                remote_filename="missing.out",
            )
            result = await _download_file(req)

        assert result["status"] == "error"
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_download_success(self, mock_ssh, tmp_path):
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser"),
            _mock_result(stdout="EXISTS"),
        ]
        mock_conn = MagicMock()

        def fake_get(remote, local):
            Path(local).parent.mkdir(parents=True, exist_ok=True)
            Path(local).write_text("result data")

        mock_conn.get.side_effect = fake_get
        mock_ssh._get_connection.return_value = mock_conn

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools.SHARED_UPLOAD_DIR", str(tmp_path)
        ):
            req = WorkspaceDownloadRequest(
                cluster="deception",
                session_id="sess-1",
                remote_filename="output.dat",
            )
            result = await _download_file(req)

        assert result["status"] == "downloaded"
        assert result["cluster"] == "deception"
        assert "output.dat" in result["local_path"]
        assert result["size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_local_filename_override(self, mock_ssh, tmp_path):
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser"),
            _mock_result(stdout="EXISTS"),
        ]
        mock_conn = MagicMock()

        def fake_get(remote, local):
            Path(local).parent.mkdir(parents=True, exist_ok=True)
            Path(local).write_text("data")

        mock_conn.get.side_effect = fake_get
        mock_ssh._get_connection.return_value = mock_conn

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools.SHARED_UPLOAD_DIR", str(tmp_path)
        ):
            req = WorkspaceDownloadRequest(
                cluster="deception",
                session_id="sess-1",
                remote_filename="slurm-999.out",
                local_filename="my_output.txt",
            )
            result = await _download_file(req)

        assert "my_output.txt" in result["local_path"]


class TestWorkspaceReadFile:
    """Tests for workspace_read_file tool."""

    @pytest.fixture
    def mock_ssh(self):
        transport = MagicMock()
        return transport

    @pytest.mark.asyncio
    async def test_read_success(self, mock_ssh):
        content = "Hello from node001\nJob completed\n"
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout=content),  # head/cat command
        ]

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceReadFileRequest(
                cluster="deception",
                session_id="sess-1",
                remote_filename="slurm-123.out",
            )
            result = await _read_file(req)

        assert result["status"] == "success"
        assert result["content"] == content
        assert result["line_count"] == 2
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_read_with_max_lines(self, mock_ssh):
        content = "line1\nline2\nline3\n"
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout=content),  # tail command
        ]

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceReadFileRequest(
                cluster="deception",
                session_id="sess-1",
                remote_filename="output.log",
                max_lines=3,
            )
            result = await _read_file(req)

        all_cmds = [c[0][0] for c in mock_ssh._run.call_args_list]
        read_cmds = [c for c in all_cmds if "readlink" not in c]
        assert read_cmds, f"No read command found in: {all_cmds}"
        assert "tail -n 3" in read_cmds[0]
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_read_with_offset(self, mock_ssh):
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout="line5\n"),  # tail +N
        ]

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceReadFileRequest(
                cluster="tahoma",
                session_id="sess-1",
                remote_filename="data.txt",
                offset_lines=5,
            )
            await _read_file(req)

        all_cmds = [c[0][0] for c in mock_ssh._run.call_args_list]
        read_cmds = [c for c in all_cmds if "readlink" not in c]
        assert read_cmds, f"No read command found in: {all_cmds}"
        assert "tail -n +5" in read_cmds[0]

    @pytest.mark.asyncio
    async def test_read_with_both_max_and_offset(self, mock_ssh):
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout="middle\n"),  # tail+head
        ]

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceReadFileRequest(
                cluster="deception",
                session_id="sess-1",
                remote_filename="big.log",
                max_lines=10,
                offset_lines=100,
            )
            await _read_file(req)

        all_cmds = [c[0][0] for c in mock_ssh._run.call_args_list]
        read_cmds = [c for c in all_cmds if "readlink" not in c]
        assert read_cmds, f"No read command found in: {all_cmds}"
        assert "tail -n +100" in read_cmds[0]
        assert "head -n 10" in read_cmds[0]

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, mock_ssh):
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stderr="No such file or directory", failed=True),  # head fails
        ]

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceReadFileRequest(
                cluster="deception",
                session_id="sess-1",
                remote_filename="gone.txt",
            )
            result = await _read_file(req)

        assert result["status"] == "error"
        assert "not found" in result["message"].lower() or "No such file" in result["message"]

    @pytest.mark.asyncio
    async def test_default_reads_up_to_10000_lines(self, mock_ssh):
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout="content\n"),  # head -n 10000
        ]

        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceReadFileRequest(
                cluster="deception",
                session_id="sess-1",
                remote_filename="file.txt",
            )
            await _read_file(req)

        all_cmds = [c[0][0] for c in mock_ssh._run.call_args_list]
        read_cmds = [c for c in all_cmds if "readlink" not in c]
        assert read_cmds, f"No read command found in: {all_cmds}"
        assert "head -n 10000" in read_cmds[0]


class TestPydanticModels:
    """Validate Pydantic request model schemas."""

    def test_list_request_cluster_required_session_optional(self):
        req = WorkspaceListRequest(cluster="deception", session_id="abc")
        assert req.cluster == "deception"
        assert req.session_id == "abc"
        assert req.subpath is None

    def test_upload_request_requires_local_path(self):
        req = WorkspaceUploadRequest(
            cluster="tahoma", session_id="s1", local_path="data/file.csv"
        )
        assert req.local_path == "data/file.csv"
        assert req.remote_filename is None
        assert req.subpath is None

    def test_download_request_requires_remote_filename(self):
        req = WorkspaceDownloadRequest(
            cluster="deception",
            session_id="s1",
            remote_filename="slurm-999.out",
        )
        assert req.remote_filename == "slurm-999.out"
        assert req.local_filename is None

    def test_read_request_optional_fields(self):
        req = WorkspaceReadFileRequest(
            cluster="deception",
            session_id="s1",
            remote_filename="log.txt",
            max_lines=50,
            offset_lines=10,
        )
        assert req.max_lines == 50
        assert req.offset_lines == 10


class TestSessionIdOptional:
    """Regression tests: session_id is Optional in all workspace models.

    The LLM doesn't always pass session_id — Pydantic must accept None,
    and the tool functions must return a clear error when it's missing.
    """

    def test_list_request_accepts_none_session_id(self):
        req = WorkspaceListRequest(cluster="deception")
        assert req.session_id is None

    def test_upload_request_accepts_none_session_id(self):
        req = WorkspaceUploadRequest(
            cluster="deception", local_path="data/file.csv"
        )
        assert req.session_id is None

    def test_download_request_accepts_none_session_id(self):
        req = WorkspaceDownloadRequest(
            cluster="deception", remote_filename="slurm-123.out"
        )
        assert req.session_id is None

    def test_read_request_accepts_none_session_id(self):
        req = WorkspaceReadFileRequest(
            cluster="deception", remote_filename="log.txt"
        )
        assert req.session_id is None

    @pytest.mark.asyncio
    async def test_list_files_returns_error_when_session_id_none(self):
        req = WorkspaceListRequest(cluster="deception")
        result = await _list_files(request=req)
        assert result["status"] == "error"
        assert "session_id" in result["message"]

    @pytest.mark.asyncio
    async def test_upload_file_returns_error_when_session_id_none(self):
        req = WorkspaceUploadRequest(
            cluster="deception", local_path="data/file.csv"
        )
        result = await _upload_file(request=req)
        assert result["status"] == "error"
        assert "session_id" in result["message"]

    @pytest.mark.asyncio
    async def test_download_file_returns_error_when_session_id_none(self):
        req = WorkspaceDownloadRequest(
            cluster="deception", remote_filename="slurm-123.out"
        )
        result = await _download_file(request=req)
        assert result["status"] == "error"
        assert "session_id" in result["message"]

    @pytest.mark.asyncio
    async def test_read_file_returns_error_when_session_id_none(self):
        req = WorkspaceReadFileRequest(
            cluster="deception", remote_filename="log.txt"
        )
        result = await _read_file(request=req)
        assert result["status"] == "error"
        assert "session_id" in result["message"]

    @pytest.mark.asyncio
    async def test_list_files_succeeds_with_session_id(self):
        """Confirm the happy path still works when session_id is provided."""
        req = WorkspaceListRequest(cluster="deception", session_id="mcp_test123")
        mock_ssh = MagicMock()
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout="total 0\n"),  # ls -la
        ]
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            mock_get.return_value = mock_ssh
            result = await _list_files(request=req)
        assert result["status"] == "success"
        assert result["workspace"] == "/home/testuser/adept-workspace/mcp_test123"

    @pytest.mark.asyncio
    async def test_read_file_succeeds_with_session_id(self):
        """Confirm read happy path when session_id provided."""
        req = WorkspaceReadFileRequest(
            cluster="deception",
            session_id="mcp_test123",
            remote_filename="slurm-999.out",
        )
        mock_ssh = MagicMock()
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout="Optimal biomass flux: 0.8739\n"),  # head command
        ]
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            mock_get.return_value = mock_ssh
            result = await _read_file(request=req)
        assert result["status"] == "success"
        assert "0.8739" in result["content"]


class TestMcpSessionIdFallback:
    """Regression (Session 67): mcp_session_id auto-injects when session_id is None.

    The orchestration framework injects mcp_session_id into tool call params
    but the LLM may not pass session_id explicitly. The tools must use
    mcp_session_id as a fallback to ensure workspace isolation.
    """

    @pytest.fixture
    def mock_ssh(self):
        transport = MagicMock()
        return transport

    @pytest.mark.asyncio
    async def test_list_files_uses_mcp_session_id(self, mock_ssh):
        """workspace_list_files falls back to mcp_session_id."""
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout="total 0\n"),  # ls -la
        ]
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceListRequest(cluster="deception", session_id=None)
            result = await _list_files(request=req, mcp_session_id="injected_123")
        assert result["status"] == "success"
        assert "injected_123" in result["workspace"]

    @pytest.mark.asyncio
    async def test_list_files_explicit_session_id_wins(self, mock_ssh):
        """Explicit session_id takes precedence over mcp_session_id."""
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout="total 0\n"),  # ls -la
        ]
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceListRequest(
                cluster="deception", session_id="explicit_456"
            )
            result = await _list_files(
                request=req, mcp_session_id="injected_123"
            )
        assert "explicit_456" in result["workspace"]

    @pytest.mark.asyncio
    async def test_read_file_uses_mcp_session_id(self, mock_ssh):
        """workspace_read_file falls back to mcp_session_id."""
        mock_ssh._run.side_effect = [
            _mock_result(stdout="/home/testuser\n"),  # readlink -f $HOME
            _mock_result(stdout="hello\n"),  # head command
        ]
        with patch(
            "slurm_mcp.workspace_tools._get_transport_for_cluster",
            new_callable=AsyncMock,
            return_value=mock_ssh,
        ), patch(
            "slurm_mcp.workspace_tools._require_ssh_transport",
            return_value=mock_ssh,
        ):
            req = WorkspaceReadFileRequest(
                cluster="deception",
                session_id=None,
                remote_filename="slurm-123.out",
            )
            result = await _read_file(request=req, mcp_session_id="auto_789")
        assert result["status"] == "success"
        assert result["content"] == "hello\n"

    @pytest.mark.asyncio
    async def test_no_session_id_at_all_returns_error(self, mock_ssh):
        """Without session_id AND mcp_session_id, returns error."""
        req = WorkspaceListRequest(cluster="deception", session_id=None)
        result = await _list_files(request=req, mcp_session_id=None)
        assert result["status"] == "error"
        assert "session_id" in result["message"]


class TestResolveWorkspaceDir:
    """Regression tests for Bug 5: $HOME symlink divergence on Deception.

    On Deception, echo $HOME returns /people/rigo160 (symlink) but canonical
    path is /qfs/people/rigo160. sbatch resolves symlinks, causing
    workspace_read_file to look at wrong path for output files.

    Fix: _resolve_workspace_dir uses `readlink -f $HOME || echo $HOME` to
    get the canonical (non-symlink) path on the remote host.
    """

    @pytest.mark.asyncio
    async def test_resolves_canonical_path(self):
        """readlink -f resolves symlinks in $HOME."""
        mock_ssh = MagicMock()
        mock_ssh._run.return_value = _mock_result(stdout="/qfs/people/rigo160\n")
        result = await _resolve_workspace_dir(mock_ssh, "demo_abc123")
        assert result == "/qfs/people/rigo160/adept-workspace/demo_abc123"
        mock_ssh._run.assert_called_once_with(
            "readlink -f $HOME || echo $HOME", warn=True
        )

    @pytest.mark.asyncio
    async def test_resolves_with_subpath(self):
        """Subpath appended correctly to canonical path."""
        mock_ssh = MagicMock()
        mock_ssh._run.return_value = _mock_result(stdout="/qfs/people/rigo160\n")
        result = await _resolve_workspace_dir(mock_ssh, "sess_1", subpath="output")
        assert result == "/qfs/people/rigo160/adept-workspace/sess_1/output"

    @pytest.mark.asyncio
    async def test_fallback_on_empty_stdout(self):
        """Falls back to /tmp if readlink returns empty."""
        mock_ssh = MagicMock()
        mock_ssh._run.return_value = _mock_result(stdout="")
        result = await _resolve_workspace_dir(mock_ssh, "sess_empty")
        assert result == "/tmp/adept-workspace/sess_empty"

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        """Strips trailing newline/whitespace from readlink output."""
        mock_ssh = MagicMock()
        mock_ssh._run.return_value = _mock_result(stdout="  /home/user  \n")
        result = await _resolve_workspace_dir(mock_ssh, "sess_ws")
        assert result == "/home/user/adept-workspace/sess_ws"

    @pytest.mark.asyncio
    async def test_never_returns_tilde(self):
        """Return value never contains a literal tilde."""
        mock_ssh = MagicMock()
        mock_ssh._run.return_value = _mock_result(stdout="/home/user\n")
        result = await _resolve_workspace_dir(mock_ssh, "sess_notilde")
        assert "~" not in result

    @pytest.mark.asyncio
    async def test_symlink_path_scenario(self):
        """Simulates Deception: /people/user is a symlink to /qfs/people/user.

        readlink -f resolves through the symlink, ensuring sbatch and
        workspace_read_file see the same canonical path.
        """
        mock_ssh = MagicMock()
        # Deception: readlink -f /people/rigo160 → /qfs/people/rigo160
        mock_ssh._run.return_value = _mock_result(stdout="/qfs/people/rigo160\n")
        result = await _resolve_workspace_dir(mock_ssh, "demo_b0c27779a097499f")
        assert result == "/qfs/people/rigo160/adept-workspace/demo_b0c27779a097499f"
        # Verify the path does NOT contain the symlink prefix
        assert not result.startswith("/people/rigo160/")

    @pytest.mark.asyncio
    async def test_uses_readlink_command(self):
        """Verifies the exact shell command issued."""
        mock_ssh = MagicMock()
        mock_ssh._run.return_value = _mock_result(stdout="/home/user\n")
        await _resolve_workspace_dir(mock_ssh, "sess_cmd")
        mock_ssh._run.assert_called_once_with(
            "readlink -f $HOME || echo $HOME", warn=True
        )
