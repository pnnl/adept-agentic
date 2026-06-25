"""
Unit Tests: Pydantic Models
============================

Tests for JobSpec, JobSubmissionRequest, and JobListFilters validation.
"""

import os
import sys

import pytest
from pydantic import ValidationError

SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)

from slurm_mcp.models import JobSpec, JobSubmissionRequest, JobListFilters


class TestJobSpec:
    """Validate JobSpec model field validation."""

    def test_default_values(self):
        """JobSpec with no arguments uses sane defaults."""
        spec = JobSpec()
        assert spec.current_working_directory == "/data"
        assert spec.environment == ["PATH=/bin:/usr/bin:/usr/local/bin:."]
        assert spec.name is None
        assert spec.nodes is None
        assert spec.partition is None

    def test_valid_job_name(self):
        """Valid job names are accepted."""
        spec = JobSpec(name="my-test-job_42")
        assert spec.name == "my-test-job_42"

    def test_invalid_job_name_rejected(self):
        """Job names with spaces or special chars are rejected."""
        with pytest.raises(ValidationError):
            JobSpec(name="my job!")

    def test_valid_node_count(self):
        """Single node and range formats are accepted."""
        assert JobSpec(nodes="1").nodes == "1"
        assert JobSpec(nodes="1-4").nodes == "1-4"
        assert JobSpec(nodes="12").nodes == "12"

    def test_invalid_node_count_rejected(self):
        """Non-numeric node specs are rejected."""
        with pytest.raises(ValidationError):
            JobSpec(nodes="abc")

    def test_time_limit_bounds(self):
        """Time limit must be 1-10080 minutes."""
        assert JobSpec(time_limit=1).time_limit == 1
        assert JobSpec(time_limit=10080).time_limit == 10080
        with pytest.raises(ValidationError):
            JobSpec(time_limit=0)
        with pytest.raises(ValidationError):
            JobSpec(time_limit=10081)

    def test_cpus_per_task_bounds(self):
        """CPUs must be 1-128."""
        assert JobSpec(cpus_per_task=1).cpus_per_task == 1
        assert JobSpec(cpus_per_task=128).cpus_per_task == 128
        with pytest.raises(ValidationError):
            JobSpec(cpus_per_task=0)
        with pytest.raises(ValidationError):
            JobSpec(cpus_per_task=129)

    def test_memory_format(self):
        """Memory accepts various formats."""
        assert JobSpec(memory="4G").memory == "4G"
        assert JobSpec(memory="512M").memory == "512M"
        assert JobSpec(memory="1024K").memory == "1024K"
        assert JobSpec(memory="8").memory == "8"

    def test_invalid_memory_rejected(self):
        """Invalid memory formats are rejected."""
        with pytest.raises(ValidationError):
            JobSpec(memory="lots")

    def test_serialization_exclude_none(self):
        """model_dump(exclude_none=True) omits unset optional fields."""
        spec = JobSpec(name="test", partition="normal")
        dumped = spec.model_dump(exclude_none=True)
        assert "name" in dumped
        assert "partition" in dumped
        assert "nodes" not in dumped
        assert "time_limit" not in dumped
        assert "current_working_directory" in dumped  # Has default value


class TestJobSubmissionRequest:
    """Validate JobSubmissionRequest model."""

    def test_valid_submission(self):
        """Valid submission with job spec and script."""
        req = JobSubmissionRequest(
            job=JobSpec(name="test", partition="normal"),
            script="#!/bin/bash\necho hello",
        )
        assert req.job.name == "test"
        assert "#!/bin/bash" in req.script

    def test_script_required(self):
        """Script field is required."""
        with pytest.raises(ValidationError):
            JobSubmissionRequest(job=JobSpec())

    def test_job_required(self):
        """Job field is required."""
        with pytest.raises(ValidationError):
            JobSubmissionRequest(script="#!/bin/bash\necho hello")


class TestJobListFilters:
    """Validate JobListFilters model."""

    def test_default_values(self):
        """Defaults: limit=20, offset=0, everything else None."""
        filters = JobListFilters()
        assert filters.limit == 20
        assert filters.offset == 0
        assert filters.state is None
        assert filters.user is None
        assert filters.partition is None

    def test_state_filter(self):
        """Multiple states can be specified."""
        filters = JobListFilters(state=["RUNNING", "PENDING"])
        assert len(filters.state) == 2

    def test_valid_user_filter(self):
        """Valid usernames accepted."""
        filters = JobListFilters(user="alice")
        assert filters.user == "alice"

    def test_invalid_user_rejected(self):
        """Usernames with special chars rejected."""
        with pytest.raises(ValidationError):
            JobListFilters(user="alice@domain")

    def test_limit_bounds(self):
        """Limit must be 1-1000."""
        assert JobListFilters(limit=1).limit == 1
        assert JobListFilters(limit=1000).limit == 1000
        with pytest.raises(ValidationError):
            JobListFilters(limit=0)
        with pytest.raises(ValidationError):
            JobListFilters(limit=1001)
