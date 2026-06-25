"""Unit tests for Tahoma cluster MCP tools (mocked transport).

Note: @app.tool wraps async functions in FunctionTool objects. Tests must
call tool.fn(...) to invoke the underlying async function directly.
"""

from unittest.mock import AsyncMock

import pytest

from slurm_mcp.transport import ClusterInfo, JobResult


@pytest.fixture(autouse=True)
def reset_transport():
    """Reset the module-level _transport between tests."""
    import slurm_mcp.tahoma.tools as tools_mod

    tools_mod._transport = None
    yield
    tools_mod._transport = None


@pytest.fixture
def mock_transport():
    """Create an AsyncMock satisfying SlurmTransport interface."""
    t = AsyncMock()
    t.ping = AsyncMock(return_value=True)
    t.submit_job = AsyncMock(
        return_value=JobResult(success=True, job_id="77777", output="Submitted batch job 77777")
    )
    t.get_job_status = AsyncMock(
        return_value=JobResult(
            success=True, job_id="77777", output="", raw_data={"job_state": "COMPLETED"}
        )
    )
    t.cancel_job = AsyncMock(
        return_value=JobResult(success=True, job_id="77777", output="")
    )
    t.list_jobs = AsyncMock(return_value=[{"job_id": 10}, {"job_id": 20}, {"job_id": 30}])
    t.get_cluster_info = AsyncMock(
        return_value=ClusterInfo(
            nodes=[{"name": f"tahoma{i:03d}"} for i in range(5)],
            jobs=[
                {"job_id": 10, "job_state": "RUNNING"},
                {"job_id": 20, "job_state": "RUNNING"},
                {"job_id": 30, "job_state": "PENDING"},
            ],
            partitions=[{"partition": "normal"}, {"partition": "gpu"}],
        )
    )
    return t


class TestTahomaPing:
    """Tests for tahoma_ping tool."""

    @pytest.mark.asyncio
    async def test_ping_connected(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.tools import tahoma_ping

        result = await tahoma_ping.fn()
        assert result["status"] == "connected"
        assert result["cluster"] == "tahoma"

    @pytest.mark.asyncio
    async def test_ping_unreachable(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        mock_transport.ping.return_value = False
        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.tools import tahoma_ping

        result = await tahoma_ping.fn()
        assert result["status"] == "unreachable"

    @pytest.mark.asyncio
    async def test_ping_error(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        mock_transport.ping.side_effect = RuntimeError("Connection timeout")
        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.tools import tahoma_ping

        result = await tahoma_ping.fn()
        assert result["status"] == "error"
        assert "timeout" in result["message"].lower()


class TestTahomaSubmitJob:
    """Tests for tahoma_submit_job tool."""

    @pytest.mark.asyncio
    async def test_submit_success(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.models import TahomaJobSpec, TahomaJobSubmissionRequest
        from slurm_mcp.tahoma.tools import tahoma_submit_job

        request = TahomaJobSubmissionRequest(
            job_spec=TahomaJobSpec(job_name="tahoma_test", nodes=2, time_limit="04:00:00"),
            script="#!/bin/bash\nmodule load python\npython script.py",
        )
        result = await tahoma_submit_job.fn(request=request)
        assert result["status"] == "submitted"
        assert result["job_id"] == "77777"
        assert result["cluster"] == "tahoma"

    @pytest.mark.asyncio
    async def test_submit_failure(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        mock_transport.submit_job.return_value = JobResult(
            success=False, error="QOSMaxJobsPerUserLimit", output=""
        )
        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.models import TahomaJobSpec, TahomaJobSubmissionRequest
        from slurm_mcp.tahoma.tools import tahoma_submit_job

        request = TahomaJobSubmissionRequest(
            job_spec=TahomaJobSpec(job_name="toomany"),
            script="#!/bin/bash\nexit 0",
        )
        result = await tahoma_submit_job.fn(request=request)
        assert result["status"] == "error"
        assert "QOSMaxJobsPerUser" in result["message"]


class TestTahomaGetJobDetails:
    """Tests for tahoma_get_job_details tool."""

    @pytest.mark.asyncio
    async def test_found(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.tools import tahoma_get_job_details

        result = await tahoma_get_job_details.fn(job_id="77777")
        assert result["status"] == "found"
        assert result["cluster"] == "tahoma"
        assert result["job_data"]["job_state"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_not_found(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        mock_transport.get_job_status.return_value = JobResult(
            success=False, job_id="00000", error="Job 00000 not found in squeue or sacct"
        )
        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.tools import tahoma_get_job_details

        result = await tahoma_get_job_details.fn(job_id="00000")
        assert result["status"] == "not_found"
        assert "not found" in result["message"]


class TestTahomaCancelJob:
    """Tests for tahoma_cancel_job tool."""

    @pytest.mark.asyncio
    async def test_cancel_success(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.tools import tahoma_cancel_job

        result = await tahoma_cancel_job.fn(job_id="77777")
        assert result["status"] == "cancelled"
        assert result["job_id"] == "77777"
        assert result["cluster"] == "tahoma"


class TestTahomaListJobs:
    """Tests for tahoma_list_jobs tool."""

    @pytest.mark.asyncio
    async def test_list_all(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.tools import tahoma_list_jobs

        result = await tahoma_list_jobs.fn()
        assert result["status"] == "success"
        assert result["cluster"] == "tahoma"
        assert result["job_count"] == 3

    @pytest.mark.asyncio
    async def test_list_with_filters(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.models import TahomaJobListFilters
        from slurm_mcp.tahoma.tools import tahoma_list_jobs

        filters = TahomaJobListFilters(user="rigo160", state="PENDING")
        result = await tahoma_list_jobs.fn(filters=filters)
        mock_transport.list_jobs.assert_called_with(user="rigo160", state="PENDING")


class TestTahomaGetClusterSummary:
    """Tests for tahoma_get_cluster_summary tool."""

    @pytest.mark.asyncio
    async def test_summary(self, mock_transport):
        import slurm_mcp.tahoma.tools as tools_mod

        tools_mod._transport = mock_transport
        from slurm_mcp.tahoma.tools import tahoma_get_cluster_summary

        result = await tahoma_get_cluster_summary.fn()
        assert result["status"] == "success"
        assert result["cluster"] == "tahoma"
        assert result["node_count"] == 5
        assert result["job_count"] == 3
        assert result["partition_count"] == 2
        assert result["queue_summary"]["running"] == 2
        assert result["queue_summary"]["pending"] == 1
