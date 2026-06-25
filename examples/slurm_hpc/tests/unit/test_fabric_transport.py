"""Unit tests for FabricSSHTransport with mocked Fabric Connection."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

pytest.importorskip("fabric", reason="fabric not installed in host test env")

from slurm_mcp.fabric_transport import FabricSSHTransport  # noqa: E402
from slurm_mcp.transport import ClusterInfo, JobResult  # noqa: E402


class FakeConfig:
    """Minimal config satisfying the SSHConfig protocol."""

    host = "test-cluster.example.com"
    ssh_port = 22
    username = "testuser"
    ssh_timeout = 30
    default_partition = "compute"
    default_account = "testalloc"

    @property
    def resolved_ssh_key_path(self):
        return Path("/tmp/fake_test_key")

    @property
    def resolved_working_directory(self):
        return "/scratch/testuser"


@pytest.fixture
def config():
    return FakeConfig()


@pytest.fixture
def transport(config):
    return FabricSSHTransport(config)


def _mock_result(stdout="", stderr="", ok=True, failed=False):
    """Create a mock Fabric Result."""
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.ok = ok
    r.failed = failed
    r.return_code = 0 if ok else 1
    return r


def _find_cmd(mock_run, keyword):
    """Find the first SSH command containing `keyword` from call_args_list.

    Returns the full command string. Raises AssertionError if not found.
    This avoids brittle call_args_list[N][0][0] positional indexing that
    breaks when internal call ordering changes.
    """
    all_cmds = [c[0][0] for c in mock_run.call_args_list]
    matches = [c for c in all_cmds if keyword in c]
    assert matches, f"No command containing {keyword!r} in: {all_cmds}"
    return matches[0]


class TestFabricSSHTransportInit:
    """Tests for initialization."""

    def test_config_stored(self, transport, config):
        assert transport._config is config

    def test_no_connection_on_init(self, transport):
        assert transport._conn is None


class TestPing:
    """Tests for ping() method."""

    @pytest.mark.asyncio
    async def test_ping_success(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.return_value = _mock_result(stdout="Slurmctld(primary) at", ok=True)
            result = await transport.ping()
            assert result is True
            mock_run.assert_called_once_with("scontrol ping", timeout=10, warn=True)

    @pytest.mark.asyncio
    async def test_ping_failure(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.return_value = _mock_result(ok=False)
            result = await transport.ping()
            assert result is False

    @pytest.mark.asyncio
    async def test_ping_exception(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = Exception("Connection refused")
            result = await transport.ping()
            assert result is False


class TestSubmitJob:
    """Tests for submit_job() method."""

    @pytest.mark.asyncio
    async def test_submit_success(self, transport):
        with patch.object(transport, "_run") as mock_run:
            # First call writes script, second runs sbatch, third cleans up
            mock_run.side_effect = [
                _mock_result(),  # cat > script
                _mock_result(stdout="Submitted batch job 98765\n"),  # sbatch
                _mock_result(),  # rm cleanup
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="test_job",
                partition="gpu",
                nodes=2,
                ntasks=4,
                time_limit="02:00:00",
            )
            assert result.success is True
            assert result.job_id == "98765"

    @pytest.mark.asyncio
    async def test_submit_failure(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(),  # cat > script
                _mock_result(
                    stdout="",
                    stderr="sbatch: error: invalid partition",
                    ok=False,
                    failed=True,
                ),  # sbatch fails
                _mock_result(),  # rm cleanup
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="bad_job",
            )
            assert result.success is False
            assert "invalid partition" in (result.error or "")

    @pytest.mark.asyncio
    async def test_submit_uses_defaults(self, transport, config):
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(),
                _mock_result(stdout="Submitted batch job 11111\n"),
                _mock_result(),
            ]
            await transport.submit_job(script="#!/bin/bash\necho hi", job_name="defaults")

            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert f"--partition={config.default_partition}" in sbatch_call
            assert f"--account={config.default_account}" in sbatch_call
            assert f"--chdir={config.resolved_working_directory}" in sbatch_call

    @pytest.mark.asyncio
    async def test_submit_override_defaults(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(),
                _mock_result(stdout="Submitted batch job 22222\n"),
                _mock_result(),
            ]
            await transport.submit_job(
                script="#!/bin/bash\necho hi",
                job_name="override",
                partition="gpu",
                account="special",
                working_directory="/custom/dir",
            )
            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert "--partition=gpu" in sbatch_call
            assert "--account=special" in sbatch_call
            assert "--chdir=/custom/dir" in sbatch_call

    @pytest.mark.asyncio
    async def test_submit_cleanup_even_on_failure(self, transport):
        with patch.object(transport, "_run") as mock_run:
            from invoke.exceptions import CommandTimedOut

            mock_run.side_effect = [
                _mock_result(),  # cat > script
                CommandTimedOut(_mock_result(), 30),  # sbatch times out
                _mock_result(),  # rm cleanup still runs
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\nsleep 999", job_name="timeout_job"
            )
            assert result.success is False
            assert mock_run.call_count == 3  # cleanup still happened


class TestGetJobStatus:
    """Tests for get_job_status() method."""

    @pytest.mark.asyncio
    async def test_found_in_squeue(self, transport):
        job_data = {"job_id": 55555, "job_state": "RUNNING", "nodes": "node01"}
        with patch.object(transport, "_run") as mock_run:
            mock_run.return_value = _mock_result(
                stdout=json.dumps({"jobs": [job_data]}), ok=True
            )
            result = await transport.get_job_status("55555")
            assert result.success is True
            assert result.job_id == "55555"
            assert result.raw_data == job_data

    @pytest.mark.asyncio
    async def test_found_in_sacct_fallback(self, transport):
        sacct_data = {"job_id": 55555, "state": {"current": "COMPLETED"}}
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout=json.dumps({"jobs": []}), ok=True),  # squeue empty
                _mock_result(
                    stdout=json.dumps({"jobs": [sacct_data]}), ok=True
                ),  # sacct has it
            ]
            result = await transport.get_job_status("55555")
            assert result.success is True
            assert result.raw_data == sacct_data

    @pytest.mark.asyncio
    async def test_not_found(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout=json.dumps({"jobs": []}), ok=True),  # squeue empty
                _mock_result(stdout=json.dumps({"jobs": []}), ok=True),  # sacct empty
            ]
            result = await transport.get_job_status("99999")
            assert result.success is False
            assert "not found" in result.error


class TestCancelJob:
    """Tests for cancel_job() method."""

    @pytest.mark.asyncio
    async def test_cancel_success(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.return_value = _mock_result(stdout="", stderr="")
            result = await transport.cancel_job("12345")
            assert result.success is True
            assert result.job_id == "12345"

    @pytest.mark.asyncio
    async def test_cancel_error(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.return_value = _mock_result(
                stdout="", stderr="scancel: error: Kill job error on job id 12345"
            )
            result = await transport.cancel_job("12345")
            assert result.success is False


class TestListJobs:
    """Tests for list_jobs() method."""

    @pytest.mark.asyncio
    async def test_list_no_filters(self, transport):
        jobs = [{"job_id": 1}, {"job_id": 2}]
        with patch.object(transport, "_run") as mock_run:
            mock_run.return_value = _mock_result(
                stdout=json.dumps({"jobs": jobs}), ok=True
            )
            result = await transport.list_jobs()
            assert len(result) == 2
            mock_run.assert_called_once_with("squeue --json", warn=True)

    @pytest.mark.asyncio
    async def test_list_with_user_filter(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.return_value = _mock_result(
                stdout=json.dumps({"jobs": []}), ok=True
            )
            await transport.list_jobs(user="rigo160")
            mock_run.assert_called_once_with(
                "squeue --json --user=rigo160", warn=True
            )

    @pytest.mark.asyncio
    async def test_list_with_state_filter(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.return_value = _mock_result(
                stdout=json.dumps({"jobs": []}), ok=True
            )
            await transport.list_jobs(state="RUNNING")
            mock_run.assert_called_once_with(
                "squeue --json --states=RUNNING", warn=True
            )

    @pytest.mark.asyncio
    async def test_list_failure_returns_empty(self, transport):
        with patch.object(transport, "_run") as mock_run:
            mock_run.return_value = _mock_result(
                stdout="", stderr="error", ok=False, failed=True
            )
            result = await transport.list_jobs()
            assert result == []


class TestGetClusterInfo:
    """Tests for get_cluster_info() method."""

    @pytest.mark.asyncio
    async def test_full_info(self, transport):
        sinfo_data = {
            "nodes": [{"name": "node001"}, {"name": "node002"}],
            "sinfo": [{"partition": "compute"}],
        }
        squeue_data = {"jobs": [{"job_id": 1, "job_state": "RUNNING"}]}

        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout=json.dumps(sinfo_data), ok=True),
                _mock_result(stdout=json.dumps(squeue_data), ok=True),
            ]
            info = await transport.get_cluster_info()
            assert isinstance(info, ClusterInfo)
            assert len(info.nodes) == 2
            assert len(info.partitions) == 1
            assert len(info.jobs) == 1

    @pytest.mark.asyncio
    async def test_partial_failure_sinfo(self, transport):
        from invoke.exceptions import CommandTimedOut

        squeue_data = {"jobs": [{"job_id": 1}]}
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                CommandTimedOut(_mock_result(), 30),  # sinfo fails
                _mock_result(stdout=json.dumps(squeue_data), ok=True),  # squeue ok
            ]
            info = await transport.get_cluster_info()
            assert info.nodes == []
            assert info.partitions == []
            assert len(info.jobs) == 1


class TestClose:
    """Tests for close() method."""

    @pytest.mark.asyncio
    async def test_close_with_connection(self, transport):
        mock_conn = MagicMock()
        transport._conn = mock_conn
        await transport.close()
        mock_conn.close.assert_called_once()
        assert transport._conn is None

    @pytest.mark.asyncio
    async def test_close_without_connection(self, transport):
        await transport.close()
        assert transport._conn is None


class TestSubmitJobWorkspaceCWD:
    """Regression tests: submit_job sets CWD to workspace when session_id provided.

    Bug: workspace_read_file reads from $HOME/adept-workspace/{session_id}/ but
    Slurm writes slurm-%j.out to the job's --chdir directory. When these
    don't match, the agent can't read job output.

    Fix: When session_id is provided, resolve $HOME via `readlink -f` and set
    --chdir to the canonical absolute workspace path so Slurm output lands
    where workspace_read_file expects it.
    """

    @pytest.mark.asyncio
    async def test_session_id_sets_chdir_to_workspace(self, transport):
        """With session_id, --chdir should be resolved-$HOME/adept-workspace/{session_id}."""
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout="/qfs/people/testuser\n"),  # readlink -f $HOME
                _mock_result(),  # mkdir -p workspace
                _mock_result(),  # cat > script
                _mock_result(stdout="Submitted batch job 99999\n"),  # sbatch
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="fba_test",
                session_id="response_abc123def456",
            )
            assert result.success is True
            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert "--chdir=/qfs/people/testuser/adept-workspace/response_abc123def456" in sbatch_call

    @pytest.mark.asyncio
    async def test_session_id_injects_output_path(self, transport):
        """With session_id, --output should route to workspace with canonical path."""
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout="/qfs/people/testuser\n"),  # readlink -f $HOME
                _mock_result(),  # mkdir -p workspace
                _mock_result(),  # cat > script
                _mock_result(stdout="Submitted batch job 44444\n"),  # sbatch
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="output_test",
                session_id="response_out123",
            )
            assert result.success is True
            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert "--output=/qfs/people/testuser/adept-workspace/response_out123/slurm-%j.out" in sbatch_call
            assert "--error=/qfs/people/testuser/adept-workspace/response_out123/slurm-%j.err" in sbatch_call

    @pytest.mark.asyncio
    async def test_no_session_id_omits_output_path(self, transport):
        """Without session_id, --output/--error should NOT be injected."""
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(),  # cat > script
                _mock_result(stdout="Submitted batch job 55555\n"),  # sbatch
                _mock_result(),  # rm cleanup
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="no_output",
            )
            assert result.success is True
            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert "--output=" not in sbatch_call
            assert "--error=" not in sbatch_call

    @pytest.mark.asyncio
    async def test_no_session_id_uses_config_workdir(self, transport, config):
        """Without session_id, --chdir should use config default."""
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(),  # cat > script
                _mock_result(stdout="Submitted batch job 11111\n"),  # sbatch
                _mock_result(),  # rm cleanup
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="no_session",
            )
            assert result.success is True
            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert f"--chdir={config.resolved_working_directory}" in sbatch_call
            assert "adept-workspace" not in sbatch_call

    @pytest.mark.asyncio
    async def test_explicit_workdir_overrides_workspace(self, transport):
        """Explicit working_directory takes precedence over workspace."""
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout="/qfs/people/testuser\n"),  # readlink -f $HOME
                _mock_result(),  # mkdir -p workspace
                _mock_result(),  # cat > script
                _mock_result(stdout="Submitted batch job 22222\n"),  # sbatch
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="custom_dir",
                session_id="response_xyz789",
                working_directory="/custom/override",
            )
            assert result.success is True
            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert "--chdir=/custom/override" in sbatch_call

    @pytest.mark.asyncio
    async def test_session_id_persists_script_in_workspace(self, transport):
        """With session_id, script is written to workspace (not /tmp)."""
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout="/qfs/people/testuser\n"),  # readlink -f $HOME
                _mock_result(),  # mkdir -p workspace
                _mock_result(),  # cat > script in workspace
                _mock_result(stdout="Submitted batch job 33333\n"),  # sbatch
            ]
            await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="persist_test",
                session_id="response_persist123",
            )
            mkdir_call = _find_cmd(mock_run, "mkdir -p")
            assert "/qfs/people/testuser/adept-workspace/response_persist123" in mkdir_call
            write_call = _find_cmd(mock_run, "cat >")
            assert "/qfs/people/testuser/adept-workspace/response_persist123/" in write_call
            assert "/tmp/" not in write_call


class TestSubmitJobSymlinkResolution:
    """Regression tests for Bug 5: $HOME symlink divergence on Deception.

    On Deception, echo $HOME returns /people/rigo160 (symlink) but the
    canonical path is /qfs/people/rigo160. sbatch resolves symlinks when
    writing output, so workspace_read_file must use the same canonical path.

    Fix: Use `readlink -f $HOME || echo $HOME` instead of `echo $HOME`.
    """

    @pytest.mark.asyncio
    async def test_readlink_resolves_symlink(self, transport):
        """readlink -f $HOME resolves /people/user -> /qfs/people/user."""
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout="/qfs/people/rigo160\n"),  # readlink -f $HOME
                _mock_result(),  # mkdir -p
                _mock_result(),  # cat > script
                _mock_result(stdout="Submitted batch job 864588\n"),  # sbatch
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="symlink_test",
                session_id="demo_b0c27779a097499f",
            )
            assert result.success is True
            readlink_call = _find_cmd(mock_run, "readlink")
            assert "readlink -f $HOME" in readlink_call
            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert "/qfs/people/rigo160/adept-workspace/demo_b0c27779a097499f" in sbatch_call
            assert "~/" not in sbatch_call
            assert "/people/rigo160/" not in sbatch_call or "/qfs/people/rigo160/" in sbatch_call

    @pytest.mark.asyncio
    async def test_readlink_fallback_when_unavailable(self, transport):
        """If readlink -f fails, falls back to echo $HOME output."""
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout="/home/fallback_user\n"),  # readlink fails, echo $HOME
                _mock_result(),  # mkdir -p
                _mock_result(),  # cat > script
                _mock_result(stdout="Submitted batch job 12345\n"),  # sbatch
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\necho test",
                job_name="fallback_test",
                session_id="sess_fallback",
            )
            assert result.success is True
            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert "--chdir=/home/fallback_user/adept-workspace/sess_fallback" in sbatch_call

    @pytest.mark.asyncio
    async def test_never_uses_tilde_in_paths(self, transport):
        """No sbatch argument should ever contain a literal tilde."""
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout="/qfs/people/testuser\n"),  # readlink -f $HOME
                _mock_result(),  # mkdir -p
                _mock_result(),  # cat > script
                _mock_result(stdout="Submitted batch job 77777\n"),  # sbatch
            ]
            await transport.submit_job(
                script="#!/bin/bash\necho no_tilde",
                job_name="tilde_check",
                session_id="sess_notilde",
            )
            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert "~/" not in sbatch_call
            assert "~/adept-workspace" not in sbatch_call

    @pytest.mark.asyncio
    async def test_empty_readlink_uses_tmp(self, transport):
        """If readlink returns empty string, fall back to /tmp."""
        with patch.object(transport, "_run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout="\n"),  # empty readlink result
                _mock_result(),  # mkdir -p
                _mock_result(),  # cat > script
                _mock_result(stdout="Submitted batch job 88888\n"),  # sbatch
            ]
            result = await transport.submit_job(
                script="#!/bin/bash\necho empty_home",
                job_name="empty_home_test",
                session_id="sess_empty",
            )
            assert result.success is True
            sbatch_call = _find_cmd(mock_run, "sbatch")
            assert "--chdir=/tmp/adept-workspace/sess_empty" in sbatch_call


class TestTransportLogging:
    """Tests for debug/info logging in FabricSSHTransport."""

    def test_run_logs_command_at_debug(self, transport, caplog):
        """_run() should log the command at DEBUG level."""
        with patch.object(transport, "_get_connection") as mock_gc:
            mock_conn = MagicMock()
            mock_result = _mock_result(stdout="hello", stderr="")
            mock_result.return_code = 0
            mock_conn.run.return_value = mock_result
            mock_gc.return_value = mock_conn

            with caplog.at_level(logging.DEBUG, logger="slurm_mcp.fabric_transport"):
                transport._run("echo hello")

            assert "SSH exec:" in caplog.text
            assert "echo hello" in caplog.text
            assert "SSH result:" in caplog.text

    def test_get_connection_logs_info_on_connect(self, transport, caplog):
        """_get_connection() should log an info message on new connection."""
        with patch("slurm_mcp.fabric_transport.Connection") as MockConn:
            mock_conn = MagicMock()
            mock_conn.is_connected = False
            MockConn.return_value = mock_conn
            # Make key path not exist to test the warning path
            with patch.object(
                type(transport._config), "resolved_ssh_key_path",
                new_callable=lambda: property(lambda self: Path("/nonexistent/key")),
            ):
                with caplog.at_level(logging.DEBUG, logger="slurm_mcp.fabric_transport"):
                    transport._get_connection()

            assert "SSH key not found" in caplog.text or "Connecting:" in caplog.text

    def test_get_connection_logs_key_exists(self, transport, caplog, tmp_path):
        """_get_connection() should log SSH key path when key exists."""
        key_file = tmp_path / "test_key"
        key_file.write_text("fake key")

        with patch("slurm_mcp.fabric_transport.Connection") as MockConn:
            mock_conn = MagicMock()
            mock_conn.is_connected = False
            MockConn.return_value = mock_conn
            with patch.object(
                type(transport._config), "resolved_ssh_key_path",
                new_callable=lambda: property(lambda self: key_file),
            ):
                with caplog.at_level(logging.DEBUG, logger="slurm_mcp.fabric_transport"):
                    transport._get_connection()

            assert "SSH key:" in caplog.text
            assert "exists=True" in caplog.text
