"""Unit tests for shared Slurm CLI output parsers."""

import json

import pytest

from slurm_mcp.slurm_parsers import (
    build_sbatch_options,
    parse_sacct_json,
    parse_sbatch_output,
    parse_scancel_output,
    parse_sinfo_json,
    parse_squeue_json,
)


class TestParseSbatchOutput:
    """Tests for parse_sbatch_output()."""

    def test_standard_output(self):
        assert parse_sbatch_output("Submitted batch job 12345\n") == "12345"

    def test_large_job_id(self):
        assert parse_sbatch_output("Submitted batch job 9876543210") == "9876543210"

    def test_extra_whitespace(self):
        assert parse_sbatch_output("  Submitted batch job 99999  \n") == "99999"

    def test_invalid_output_raises(self):
        with pytest.raises(ValueError, match="Could not parse"):
            parse_sbatch_output("Error: invalid partition")

    def test_empty_output_raises(self):
        with pytest.raises(ValueError, match="Could not parse"):
            parse_sbatch_output("")


class TestParseSqueueJson:
    """Tests for parse_squeue_json()."""

    def test_empty_queue(self):
        data = json.dumps({"jobs": []})
        assert parse_squeue_json(data) == []

    def test_single_job(self):
        data = json.dumps({"jobs": [{"job_id": 123, "job_state": "RUNNING"}]})
        result = parse_squeue_json(data)
        assert len(result) == 1
        assert result[0]["job_id"] == 123
        assert result[0]["job_state"] == "RUNNING"

    def test_multiple_jobs(self):
        data = json.dumps({"jobs": [
            {"job_id": 1, "job_state": "PENDING"},
            {"job_id": 2, "job_state": "RUNNING"},
            {"job_id": 3, "job_state": "COMPLETED"},
        ]})
        result = parse_squeue_json(data)
        assert len(result) == 3

    def test_missing_jobs_key(self):
        data = json.dumps({"meta": {}})
        assert parse_squeue_json(data) == []


class TestParseSinfoJson:
    """Tests for parse_sinfo_json()."""

    def test_basic_structure(self):
        data = json.dumps({"nodes": [{"name": "node001"}], "sinfo": [{"partition": "compute"}]})
        result = parse_sinfo_json(data)
        assert "nodes" in result
        assert "sinfo" in result


class TestParseSacctJson:
    """Tests for parse_sacct_json()."""

    def test_completed_job(self):
        data = json.dumps({"jobs": [{"job_id": 456, "state": {"current": "COMPLETED"}}]})
        result = parse_sacct_json(data)
        assert len(result) == 1
        assert result[0]["job_id"] == 456

    def test_empty_history(self):
        data = json.dumps({"jobs": []})
        assert parse_sacct_json(data) == []


class TestParseScancelOutput:
    """Tests for parse_scancel_output()."""

    def test_success_empty_stderr(self):
        assert parse_scancel_output("", "") is True

    def test_failure_with_error(self):
        assert parse_scancel_output("", "scancel: error: Kill job error") is False

    def test_stdout_ignored(self):
        assert parse_scancel_output("some output", "") is True


class TestBuildSbatchOptions:
    """Tests for build_sbatch_options()."""

    def test_minimal_options(self):
        result = build_sbatch_options(job_name="test")
        assert "--job-name=test" in result
        assert "--nodes=1" in result
        assert "--ntasks=1" in result
        assert "--cpus-per-task=1" in result
        assert "--time=01:00:00" in result

    def test_full_options(self):
        result = build_sbatch_options(
            job_name="big_job",
            partition="gpu",
            account="myalloc",
            nodes=4,
            ntasks=16,
            cpus_per_task=8,
            memory="64G",
            time_limit="24:00:00",
            working_directory="/scratch/user",
            array="0-99%10",
        )
        assert "--job-name=big_job" in result
        assert "--partition=gpu" in result
        assert "--account=myalloc" in result
        assert "--nodes=4" in result
        assert "--ntasks=16" in result
        assert "--cpus-per-task=8" in result
        assert "--mem=64G" in result
        assert "--time=24:00:00" in result
        assert "--chdir=/scratch/user" in result
        assert "--array=0-99%10" in result

    def test_none_optional_fields_excluded(self):
        result = build_sbatch_options(job_name="test")
        assert "--partition" not in result
        assert "--account" not in result
        assert "--mem" not in result
        assert "--chdir" not in result
        assert "--array" not in result
        assert "--output" not in result
        assert "--error" not in result

    def test_output_path_included_when_set(self):
        result = build_sbatch_options(
            job_name="test",
            output_path="~/adept-workspace/session123/slurm-%j.out",
            error_path="~/adept-workspace/session123/slurm-%j.err",
        )
        assert "--output=~/adept-workspace/session123/slurm-%j.out" in result
        assert "--error=~/adept-workspace/session123/slurm-%j.err" in result

    def test_output_path_omitted_when_none(self):
        result = build_sbatch_options(
            job_name="test",
            output_path=None,
            error_path=None,
        )
        assert "--output" not in result
        assert "--error" not in result
