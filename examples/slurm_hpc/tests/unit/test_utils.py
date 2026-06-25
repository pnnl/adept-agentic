"""
Unit Tests: Output Formatting Utilities
========================================

Tests for format_job_details and format_job_list functions.
"""

import os
import sys

import pytest

SLURM_MCP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "slurm_mcp_server"
)
if SLURM_MCP_DIR not in sys.path:
    sys.path.insert(0, SLURM_MCP_DIR)

from slurm_mcp.utils import format_job_details, format_job_list
from slurm_mcp.config import SlurmConfig


@pytest.fixture
def config():
    """Minimal config for emoji lookups."""
    return SlurmConfig(_env_file=None)


class TestFormatJobDetails:
    """Validate format_job_details markdown output."""

    def test_basic_output(self, sample_job_data, config):
        """Output contains job ID, name, state, and user."""
        result = format_job_details(sample_job_data, "42", config)
        assert "42" in result
        assert "test_job" in result
        assert "COMPLETED" in result
        assert "testuser" in result

    def test_markdown_headers(self, sample_job_data, config):
        """Output contains expected markdown headers."""
        result = format_job_details(sample_job_data, "42", config)
        assert "# Job Details" in result
        assert "## Status" in result
        assert "## Resources" in result
        assert "## Timing" in result
        assert "## Files" in result

    def test_exit_code_shown(self, sample_job_data, config):
        """Exit code section appears for completed jobs."""
        result = format_job_details(sample_job_data, "42", config)
        assert "Exit Code" in result
        assert "0" in result
        assert "Success" in result

    def test_failed_exit_code(self, sample_job_data, config):
        """Failed exit code shows 'Failed' status."""
        sample_job_data["exit_code"] = {"number": 1}
        result = format_job_details(sample_job_data, "42", config)
        assert "Failed" in result

    def test_missing_fields_handled(self, config):
        """Minimal job data doesn't crash."""
        minimal_job = {
            "job_state": ["PENDING"],
            "name": "minimal",
        }
        result = format_job_details(minimal_job, "1", config)
        assert "minimal" in result
        assert "PENDING" in result

    def test_timestamp_formatting(self, sample_job_data, config):
        """Timestamps are human-readable."""
        result = format_job_details(sample_job_data, "42", config)
        # Should contain date-like format
        assert "Submitted" in result
        assert "Started" in result
        assert "Ended" in result

    def test_batch_script_shown(self, sample_job_data, config):
        """Batch script section appears when present."""
        sample_job_data["batch_script"] = "#!/bin/bash\necho hello"
        result = format_job_details(sample_job_data, "42", config)
        assert "Job Script" in result
        assert "echo hello" in result

    def test_state_reason_shown(self, sample_job_data, config):
        """State reason appears when present."""
        sample_job_data["state_reason"] = "Resources"
        result = format_job_details(sample_job_data, "42", config)
        assert "State Reason" in result
        assert "Resources" in result

    def test_custom_prefix(self, sample_job_data, config):
        """Custom resource_prefix changes the header."""
        result = format_job_details(
            sample_job_data, "42", config, resource_prefix="Custom Header"
        )
        assert "# Custom Header" in result


class TestFormatJobList:
    """Validate format_job_list markdown table output."""

    def test_basic_output(self, sample_jobs_list, config):
        """Output contains all jobs in table format."""
        result = format_job_list(sample_jobs_list, config)
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" in result
        assert "alice" in result
        assert "bob" in result

    def test_table_headers(self, sample_jobs_list, config):
        """Output contains table header row."""
        result = format_job_list(sample_jobs_list, config)
        assert "Job ID" in result
        assert "Name" in result
        assert "User" in result
        assert "State" in result
        assert "Partition" in result

    def test_job_count(self, sample_jobs_list, config):
        """Output shows total job count."""
        result = format_job_list(sample_jobs_list, config)
        assert "3" in result

    def test_empty_list(self, config):
        """Empty list shows no-jobs message."""
        result = format_job_list([], config)
        assert "0" in result
        assert "No jobs found" in result

    def test_states_shown(self, sample_jobs_list, config):
        """Job states appear in output."""
        result = format_job_list(sample_jobs_list, config)
        assert "RUNNING" in result
        assert "PENDING" in result
        assert "COMPLETED" in result
