"""Unit tests for TahomaRESTTransport.

Tests the REST transport implementation against mocked slurmrestd responses.
Validates HTTP method routing, payload construction, error handling, and
response parsing without requiring a live slurmrestd.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)

from slurm_mcp.tahoma.rest_transport import (
    TahomaRESTTransport,
    _match_job_state,
    _parse_memory_mb,
    _parse_time_limit_minutes,
)


class TestHelperFunctions:
    """Test pure utility functions used by REST transport."""

    def test_parse_time_limit_hhmmss(self):
        assert _parse_time_limit_minutes("01:00:00") == 60
        assert _parse_time_limit_minutes("04:30:00") == 270
        assert _parse_time_limit_minutes("00:10:00") == 10

    def test_parse_time_limit_hhmm(self):
        assert _parse_time_limit_minutes("02:30") == 150

    def test_parse_memory_mb_gigabytes(self):
        assert _parse_memory_mb("64G") == 65536
        assert _parse_memory_mb("1G") == 1024
        assert _parse_memory_mb("0.5G") == 512

    def test_parse_memory_mb_megabytes(self):
        assert _parse_memory_mb("4096M") == 4096
        assert _parse_memory_mb("512m") == 512

    def test_parse_memory_mb_terabytes(self):
        assert _parse_memory_mb("1T") == 1048576

    def test_parse_memory_mb_plain_number(self):
        assert _parse_memory_mb("2048") == 2048

    def test_match_job_state_string(self):
        assert _match_job_state("RUNNING", "RUNNING") is True
        assert _match_job_state("running", "RUNNING") is True
        assert _match_job_state("PENDING", "RUNNING") is False

    def test_match_job_state_list(self):
        assert _match_job_state(["RUNNING"], "RUNNING") is True
        assert _match_job_state(["PENDING", "RUNNING"], "RUNNING") is True
        assert _match_job_state(["PENDING"], "RUNNING") is False

    def test_match_job_state_none(self):
        assert _match_job_state(None, "RUNNING") is False


class TestTahomaRESTTransportInit:
    """Test transport initialization and config adapter."""

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.rest_api_url = "http://tahoma-rest:6820"
        config.rest_api_version = "v0.0.41"
        config.rest_timeout = 30
        config.jwt_key = ""
        config.service_jwt = "test-token-123"
        config.username = "rigo160"
        config.default_partition = "normal"
        config.default_account = "myalloc"
        config.working_directory = "/scratch/rigo160"
        config.resolved_working_directory = "/scratch/rigo160"
        return config

    def test_init_creates_transport(self, mock_config):
        transport = TahomaRESTTransport(mock_config)
        assert transport._config is mock_config
        assert transport._active_client is None

    @pytest.mark.asyncio
    async def test_ping_returns_false_on_connection_error(self, mock_config):
        """When slurmrestd is unreachable, ping returns False."""
        mock_config.rest_api_url = "http://unreachable:6820"
        transport = TahomaRESTTransport(mock_config)

        with patch.object(transport, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=Exception("Connection refused"))
            mock_get.return_value = mock_client

            result = await transport.ping()
            assert result is False

    @pytest.mark.asyncio
    async def test_ping_returns_true_on_success(self, mock_config):
        transport = TahomaRESTTransport(mock_config)

        with patch.object(transport, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value={"meta": {"slurm": {}}})
            mock_get.return_value = mock_client

            result = await transport.ping()
            assert result is True

    @pytest.mark.asyncio
    async def test_submit_job_success(self, mock_config):
        transport = TahomaRESTTransport(mock_config)

        with patch.object(transport, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value={"job_id": 12345})
            mock_get.return_value = mock_client

            result = await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="test_job",
                nodes=2,
                ntasks=4,
                time_limit="02:00:00",
            )
            assert result.success is True
            assert result.job_id == "12345"
            assert "12345" in result.output

            call_args = mock_client.request.call_args
            assert call_args[0][0] == "POST"
            assert "/job/submit" in call_args[0][1]
            payload = call_args[1]["json"]
            assert payload["job"]["name"] == "test_job"
            assert payload["job"]["nodes"] == "2"
            assert payload["job"]["partition"] == "normal"

    @pytest.mark.asyncio
    async def test_submit_job_no_job_id_in_response(self, mock_config):
        transport = TahomaRESTTransport(mock_config)

        with patch.object(transport, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value={"errors": ["bad"]})
            mock_get.return_value = mock_client

            result = await transport.submit_job(
                script="#!/bin/bash\necho hello",
                job_name="failing_job",
            )
            assert result.success is False
            assert "No job_id" in result.error

    @pytest.mark.asyncio
    async def test_get_job_status_found(self, mock_config):
        transport = TahomaRESTTransport(mock_config)

        with patch.object(transport, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(
                return_value={
                    "jobs": [
                        {
                            "job_id": 9876,
                            "job_state": ["COMPLETED"],
                            "nodes": "t001",
                        }
                    ]
                }
            )
            mock_get.return_value = mock_client

            result = await transport.get_job_status("9876")
            assert result.success is True
            assert result.job_id == "9876"
            assert result.raw_data["job_state"] == ["COMPLETED"]

    @pytest.mark.asyncio
    async def test_get_job_status_not_found(self, mock_config):
        transport = TahomaRESTTransport(mock_config)

        with patch.object(transport, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value={"jobs": []})
            mock_get.return_value = mock_client

            result = await transport.get_job_status("99999")
            assert result.success is False
            assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_cancel_job_success(self, mock_config):
        transport = TahomaRESTTransport(mock_config)

        with patch.object(transport, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value={})
            mock_get.return_value = mock_client

            result = await transport.cancel_job("5555")
            assert result.success is True
            assert result.job_id == "5555"

    @pytest.mark.asyncio
    async def test_list_jobs_with_filters(self, mock_config):
        transport = TahomaRESTTransport(mock_config)

        with patch.object(transport, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(
                return_value={
                    "jobs": [
                        {"job_id": 1, "user_name": "rigo160", "job_state": "RUNNING"},
                        {"job_id": 2, "user_name": "alice", "job_state": "RUNNING"},
                        {"job_id": 3, "user_name": "rigo160", "job_state": "PENDING"},
                    ]
                }
            )
            mock_get.return_value = mock_client

            jobs = await transport.list_jobs(user="rigo160", state="RUNNING")
            assert len(jobs) == 1
            assert jobs[0]["job_id"] == 1

    @pytest.mark.asyncio
    async def test_get_cluster_info(self, mock_config):
        transport = TahomaRESTTransport(mock_config)

        with patch.object(transport, "_get_client") as mock_get:
            mock_client = AsyncMock()

            async def mock_request(method, endpoint, **kw):
                if "nodes" in endpoint:
                    return {"nodes": [{"name": "t001"}, {"name": "t002"}]}
                elif "partitions" in endpoint:
                    return {"partitions": [{"name": "normal"}]}
                elif "jobs" in endpoint:
                    return {"jobs": [{"job_id": 1}]}
                return {}

            mock_client.request = AsyncMock(side_effect=mock_request)
            mock_get.return_value = mock_client

            info = await transport.get_cluster_info()
            assert len(info.nodes) == 2
            assert len(info.partitions) == 1
            assert len(info.jobs) == 1

    @pytest.mark.asyncio
    async def test_close(self, mock_config):
        transport = TahomaRESTTransport(mock_config)
        transport._active_client = AsyncMock()
        transport._active_client.__aexit__ = AsyncMock()

        await transport.close()
        assert transport._active_client is None
