"""Unit tests for Deception cluster MCP tools (mocked transport).

Note: @app.tool wraps async functions in FunctionTool objects. Tests must
call tool.fn(...) to invoke the underlying async function directly.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slurm_mcp.transport import ClusterInfo, JobResult


@pytest.fixture(autouse=True)
def reset_transport():
    """Reset the module-level _transport between tests."""
    import slurm_mcp.deception.tools as tools_mod

    tools_mod._transport = None
    yield
    tools_mod._transport = None


@pytest.fixture
def mock_transport():
    """Create an AsyncMock satisfying SlurmTransport interface."""
    t = AsyncMock()
    t.ping = AsyncMock(return_value=True)
    t.submit_job = AsyncMock(
        return_value=JobResult(success=True, job_id="99999", output="Submitted batch job 99999")
    )
    t.get_job_status = AsyncMock(
        return_value=JobResult(
            success=True, job_id="99999", output="", raw_data={"job_state": "RUNNING"}
        )
    )
    t.cancel_job = AsyncMock(
        return_value=JobResult(success=True, job_id="99999", output="")
    )
    t.list_jobs = AsyncMock(return_value=[{"job_id": 1}, {"job_id": 2}])
    t.get_cluster_info = AsyncMock(
        return_value=ClusterInfo(
            nodes=[{"name": "node001"}, {"name": "node002"}],
            jobs=[
                {"job_id": 1, "job_state": "RUNNING"},
                {"job_id": 2, "job_state": "PENDING"},
            ],
            partitions=[{"partition": "compute"}],
        )
    )
    return t


class TestDeceptionPing:
    """Tests for deception_ping tool."""

    @pytest.mark.asyncio
    async def test_ping_connected(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_ping

        result = await deception_ping.fn()
        assert result["status"] == "connected"
        assert result["cluster"] == "deception"

    @pytest.mark.asyncio
    async def test_ping_unreachable(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        mock_transport.ping.return_value = False
        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_ping

        result = await deception_ping.fn()
        assert result["status"] == "unreachable"

    @pytest.mark.asyncio
    async def test_ping_exception(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        mock_transport.ping.side_effect = Exception("Network error")
        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_ping

        result = await deception_ping.fn()
        assert result["status"] == "error"
        assert "Network error" in result["message"]


class TestDeceptionSubmitJob:
    """Tests for deception_submit_job tool."""

    @pytest.mark.asyncio
    async def test_submit_success(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.models import DeceptionJobSpec, DeceptionJobSubmissionRequest
        from slurm_mcp.deception.tools import deception_submit_job

        request = DeceptionJobSubmissionRequest(
            job_spec=DeceptionJobSpec(job_name="test_hello", nodes=1, time_limit="00:05:00"),
            script="#!/bin/bash\necho hello",
        )
        result = await deception_submit_job.fn(request=request)
        assert result["status"] == "submitted"
        assert result["job_id"] == "99999"
        assert result["cluster"] == "deception"

    @pytest.mark.asyncio
    async def test_submit_failure(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        mock_transport.submit_job.return_value = JobResult(
            success=False, error="Invalid partition", output=""
        )
        tools_mod._transport = mock_transport
        from slurm_mcp.deception.models import DeceptionJobSpec, DeceptionJobSubmissionRequest
        from slurm_mcp.deception.tools import deception_submit_job

        request = DeceptionJobSubmissionRequest(
            job_spec=DeceptionJobSpec(job_name="bad_job"),
            script="#!/bin/bash\nexit 1",
        )
        result = await deception_submit_job.fn(request=request)
        assert result["status"] == "error"
        assert "Invalid partition" in result["message"]


class TestDeceptionGetJobDetails:
    """Tests for deception_get_job_details tool."""

    @pytest.mark.asyncio
    async def test_found(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_get_job_details

        result = await deception_get_job_details.fn(job_id="99999")
        assert result["status"] == "found"
        assert result["job_id"] == "99999"
        assert result["job_data"]["job_state"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        mock_transport.get_job_status.return_value = JobResult(
            success=False, job_id="11111", error="Job 11111 not found"
        )
        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_get_job_details

        result = await deception_get_job_details.fn(job_id="11111")
        assert result["status"] == "not_found"
        assert "not found" in result["message"]


class TestDeceptionCancelJob:
    """Tests for deception_cancel_job tool."""

    @pytest.mark.asyncio
    async def test_cancel_success(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_cancel_job

        result = await deception_cancel_job.fn(job_id="99999")
        assert result["status"] == "cancelled"
        assert result["job_id"] == "99999"

    @pytest.mark.asyncio
    async def test_cancel_failure(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        mock_transport.cancel_job.return_value = JobResult(
            success=False, job_id="99999", error="Job already completed"
        )
        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_cancel_job

        result = await deception_cancel_job.fn(job_id="99999")
        assert result["status"] == "error"
        assert "already completed" in result["message"]


class TestDeceptionListJobs:
    """Tests for deception_list_jobs tool."""

    @pytest.mark.asyncio
    async def test_list_no_filters(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_list_jobs

        result = await deception_list_jobs.fn()
        assert result["status"] == "success"
        assert result["cluster"] == "deception"
        assert result["job_count"] == 2

    @pytest.mark.asyncio
    async def test_list_with_filters(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.models import DeceptionJobListFilters
        from slurm_mcp.deception.tools import deception_list_jobs

        filters = DeceptionJobListFilters(user="rigo160", state="RUNNING")
        result = await deception_list_jobs.fn(filters=filters)
        mock_transport.list_jobs.assert_called_with(user="rigo160", state="RUNNING")
        assert result["status"] == "success"


class TestDeceptionGetClusterSummary:
    """Tests for deception_get_cluster_summary tool."""

    @pytest.mark.asyncio
    async def test_summary(self, mock_transport):
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_get_cluster_summary

        result = await deception_get_cluster_summary.fn()
        assert result["status"] == "success"
        assert result["cluster"] == "deception"
        assert result["node_count"] == 2
        assert result["job_count"] == 2
        assert result["partition_count"] == 1
        assert result["queue_summary"]["running"] == 1
        assert result["queue_summary"]["pending"] == 1


class TestLogToolCallDecorator:
    """Tests for the _log_tool_call timing/logging decorator."""

    @pytest.mark.asyncio
    async def test_decorator_logs_entry_and_exit(self, mock_transport, caplog):
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_ping

        with caplog.at_level(logging.INFO, logger="slurm_mcp.deception.tools"):
            result = await deception_ping.fn()

        assert result["status"] == "connected"
        log_text = caplog.text
        assert "[TOOL] deception_ping called" in log_text
        assert "[TOOL] deception_ping completed" in log_text
        assert "elapsed=" in log_text

    @pytest.mark.asyncio
    async def test_decorator_logs_on_exception(self, mock_transport, caplog):
        import slurm_mcp.deception.tools as tools_mod

        mock_transport.ping.side_effect = Exception("Network error")
        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_ping

        with caplog.at_level(logging.INFO, logger="slurm_mcp.deception.tools"):
            result = await deception_ping.fn()

        # deception_ping catches exceptions and returns error dict
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_decorator_measures_elapsed_time(self, mock_transport, caplog):
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_get_job_details

        with caplog.at_level(logging.INFO, logger="slurm_mcp.deception.tools"):
            await deception_get_job_details.fn(job_id="99999")

        # Verify elapsed time is reported (any positive float)
        assert "elapsed=0." in caplog.text or "elapsed=1." in caplog.text

    @pytest.mark.asyncio
    async def test_decorator_logs_kwargs(self, mock_transport, caplog):
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.tools import deception_get_job_details

        with caplog.at_level(logging.INFO, logger="slurm_mcp.deception.tools"):
            await deception_get_job_details.fn(job_id="12345")

        assert "12345" in caplog.text


class TestMcpSessionIdFallback:
    """Regression (Session 67): mcp_session_id auto-injects when request.session_id is None."""

    @pytest.mark.asyncio
    async def test_submit_uses_mcp_session_id_when_request_has_none(self, mock_transport):
        """When request.session_id is None, mcp_session_id fills in."""
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.models import DeceptionJobSpec, DeceptionJobSubmissionRequest
        from slurm_mcp.deception.tools import deception_submit_job

        request = DeceptionJobSubmissionRequest(
            job_spec=DeceptionJobSpec(job_name="test_inject", nodes=1, time_limit="00:05:00"),
            script="#!/bin/bash\necho hello",
            session_id=None,
        )
        result = await deception_submit_job.fn(request=request, mcp_session_id="injected_abc")
        assert result["status"] == "submitted"
        assert result["workspace"] == "~/adept-workspace/injected_abc"
        mock_transport.submit_job.assert_called_once()
        call_kwargs = mock_transport.submit_job.call_args[1]
        assert call_kwargs["session_id"] == "injected_abc"

    @pytest.mark.asyncio
    async def test_submit_explicit_session_id_wins_over_mcp(self, mock_transport):
        """When request.session_id is set, it takes precedence over mcp_session_id."""
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.models import DeceptionJobSpec, DeceptionJobSubmissionRequest
        from slurm_mcp.deception.tools import deception_submit_job

        request = DeceptionJobSubmissionRequest(
            job_spec=DeceptionJobSpec(job_name="test_explicit", nodes=1, time_limit="00:05:00"),
            script="#!/bin/bash\necho hello",
            session_id="explicit_456",
        )
        result = await deception_submit_job.fn(request=request, mcp_session_id="injected_abc")
        assert result["status"] == "submitted"
        assert result["workspace"] == "~/adept-workspace/explicit_456"
        call_kwargs = mock_transport.submit_job.call_args[1]
        assert call_kwargs["session_id"] == "explicit_456"

    @pytest.mark.asyncio
    async def test_submit_no_session_id_at_all(self, mock_transport):
        """When both session_id and mcp_session_id are None, no workspace is returned."""
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.models import DeceptionJobSpec, DeceptionJobSubmissionRequest
        from slurm_mcp.deception.tools import deception_submit_job

        request = DeceptionJobSubmissionRequest(
            job_spec=DeceptionJobSpec(job_name="test_none", nodes=1, time_limit="00:05:00"),
            script="#!/bin/bash\necho hello",
            session_id=None,
        )
        result = await deception_submit_job.fn(request=request, mcp_session_id=None)
        assert result["status"] == "submitted"
        assert "workspace" not in result
        call_kwargs = mock_transport.submit_job.call_args[1]
        assert call_kwargs["session_id"] is None

    @pytest.mark.asyncio
    async def test_submit_mcp_session_id_logged(self, mock_transport, caplog):
        """When mcp_session_id fills in, an info-level log is emitted."""
        import slurm_mcp.deception.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.deception.models import DeceptionJobSpec, DeceptionJobSubmissionRequest
        from slurm_mcp.deception.tools import deception_submit_job

        request = DeceptionJobSubmissionRequest(
            job_spec=DeceptionJobSpec(job_name="test_log", nodes=1, time_limit="00:05:00"),
            script="#!/bin/bash\necho hello",
            session_id=None,
        )
        with caplog.at_level(logging.INFO, logger="slurm_mcp.deception.tools"):
            await deception_submit_job.fn(request=request, mcp_session_id="logged_xyz")

        assert "auto-injected from mcp_session_id=logged_xyz" in caplog.text
