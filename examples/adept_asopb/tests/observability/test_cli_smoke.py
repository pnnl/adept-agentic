"""CLI smoke tests for token utilization commands.

Exercises the Click CLI against the live Langfuse backend.
Only runs when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.
"""

import json
import os
import tempfile

import pytest
from click.testing import CliRunner

from asopb.observability.cli import token_usage_cli


LANGFUSE_AVAILABLE = bool(
    os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
)


def _extract_json(output: str) -> str:
    """Extract JSON object from CLI output that may have Rich console prefix lines."""
    start = output.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in output: {output[:200]}")
    end = output.rfind("}") + 1
    return output[start:end]


@pytest.mark.integration
@pytest.mark.skipif(not LANGFUSE_AVAILABLE, reason="LANGFUSE_PUBLIC_KEY/SECRET_KEY not set")
class TestTokenUsageCLISmoke:
    """Smoke tests verifying CLI commands work end-to-end with live Langfuse."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def db_path(self, tmp_path):
        """Temporary SQLite database for test isolation."""
        return str(tmp_path / "test_token_utilization.db")

    def test_backends_command(self, runner):
        """Verify 'backends' lists available backends without error."""
        result = runner.invoke(token_usage_cli, ["backends"])
        assert result.exit_code == 0
        assert "langfuse" in result.output.lower()
        assert "aws" in result.output.lower()
        assert "azure" in result.output.lower()
        assert "gcp" in result.output.lower()

    def test_aggregate_text_format(self, runner):
        """Verify 'aggregate' produces text output from live Langfuse."""
        result = runner.invoke(token_usage_cli, [
            "aggregate",
            "--backend", "langfuse",
            "--endpoint", os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
            "--public-key", os.environ["LANGFUSE_PUBLIC_KEY"],
            "--secret-key", os.environ["LANGFUSE_SECRET_KEY"],
            "--format", "text",
            "--no-save",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "total generations" in result.output.lower()

    def test_aggregate_json_format(self, runner):
        """Verify 'aggregate --format json' produces valid JSON."""
        result = runner.invoke(token_usage_cli, [
            "aggregate",
            "--backend", "langfuse",
            "--endpoint", os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
            "--public-key", os.environ["LANGFUSE_PUBLIC_KEY"],
            "--secret-key", os.environ["LANGFUSE_SECRET_KEY"],
            "--format", "json",
            "--no-save",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        json_str = _extract_json(result.output)
        data = json.loads(json_str)
        assert "total_generations" in data
        assert "dast_probe_count" in data
        assert "total_cost" in data
        assert data["total_generations"] > 0

    def test_aggregate_with_date_filter(self, runner):
        """Verify --from-date filter is respected."""
        result = runner.invoke(token_usage_cli, [
            "aggregate",
            "--backend", "langfuse",
            "--endpoint", os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
            "--public-key", os.environ["LANGFUSE_PUBLIC_KEY"],
            "--secret-key", os.environ["LANGFUSE_SECRET_KEY"],
            "--from-date", "2026-05-26",
            "--format", "json",
            "--no-save",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        json_str = _extract_json(result.output)
        data = json.loads(json_str)
        assert data["total_generations"] > 0

    def test_aggregate_with_cost_model(self, runner):
        """Verify --cost-model option works for different models."""
        result = runner.invoke(token_usage_cli, [
            "aggregate",
            "--backend", "langfuse",
            "--endpoint", os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
            "--public-key", os.environ["LANGFUSE_PUBLIC_KEY"],
            "--secret-key", os.environ["LANGFUSE_SECRET_KEY"],
            "--cost-model", "bedrock-claude-sonnet-4",
            "--format", "json",
            "--no-save",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        json_str = _extract_json(result.output)
        data = json.loads(json_str)
        assert data["cost_model_name"] == "bedrock-claude-sonnet-4"

    def test_aggregate_with_save(self, runner, db_path, monkeypatch):
        """Verify --save persists to SQLite and 'trends' retrieves it."""
        monkeypatch.setenv("ASOPB_TOKEN_DB", db_path)

        result = runner.invoke(token_usage_cli, [
            "aggregate",
            "--backend", "langfuse",
            "--endpoint", os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
            "--public-key", os.environ["LANGFUSE_PUBLIC_KEY"],
            "--secret-key", os.environ["LANGFUSE_SECRET_KEY"],
            "--format", "text",
            "--save",
        ])
        assert result.exit_code == 0, f"Aggregate failed: {result.output}"
        assert "Saved to SQLite" in result.output

        # Now verify trends shows the saved run
        result = runner.invoke(token_usage_cli, ["trends", "--last", "5"])
        assert result.exit_code == 0, f"Trends failed: {result.output}"
        assert "langfuse" in result.output.lower()

    def test_history_command(self, runner, db_path, monkeypatch):
        """Verify 'history' lists runs after an aggregate."""
        monkeypatch.setenv("ASOPB_TOKEN_DB", db_path)

        # First create a run
        runner.invoke(token_usage_cli, [
            "aggregate",
            "--backend", "langfuse",
            "--endpoint", os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
            "--public-key", os.environ["LANGFUSE_PUBLIC_KEY"],
            "--secret-key", os.environ["LANGFUSE_SECRET_KEY"],
            "--save",
        ])

        result = runner.invoke(token_usage_cli, ["history", "--limit", "5"])
        assert result.exit_code == 0, f"History failed: {result.output}"
        assert "run_" in result.output

    def test_show_command(self, runner, db_path, monkeypatch):
        """Verify 'show' displays a specific run."""
        monkeypatch.setenv("ASOPB_TOKEN_DB", db_path)

        # First create a run via aggregate
        agg_result = runner.invoke(token_usage_cli, [
            "aggregate",
            "--backend", "langfuse",
            "--endpoint", os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
            "--public-key", os.environ["LANGFUSE_PUBLIC_KEY"],
            "--secret-key", os.environ["LANGFUSE_SECRET_KEY"],
            "--save",
        ])
        assert agg_result.exit_code == 0

        # Extract run_id from output
        for line in agg_result.output.splitlines():
            if "run_" in line:
                run_id = line.split("run_")[1].split("[")[0].strip()
                run_id = "run_" + run_id
                break
        else:
            pytest.fail("Could not find run_id in aggregate output")

        result = runner.invoke(token_usage_cli, ["show", run_id])
        assert result.exit_code == 0, f"Show failed: {result.output}"
        assert "langfuse" in result.output.lower() or "Langfuse" in result.output

    def test_aggregate_output_to_file(self, runner, tmp_path):
        """Verify --output writes report to file."""
        output_file = str(tmp_path / "report.json")

        result = runner.invoke(token_usage_cli, [
            "aggregate",
            "--backend", "langfuse",
            "--endpoint", os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
            "--public-key", os.environ["LANGFUSE_PUBLIC_KEY"],
            "--secret-key", os.environ["LANGFUSE_SECRET_KEY"],
            "--format", "json",
            "--output", output_file,
            "--no-save",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "Report written to" in result.output

        with open(output_file) as f:
            data = json.loads(f.read())
        assert data["total_generations"] > 0

    def test_aggregate_invalid_backend(self, runner):
        """Verify invalid backend name produces clean error."""
        result = runner.invoke(token_usage_cli, [
            "aggregate",
            "--backend", "nonexistent",
        ])
        assert result.exit_code != 0

    def test_trends_empty_database(self, runner, db_path, monkeypatch):
        """Verify 'trends' handles empty database gracefully."""
        monkeypatch.setenv("ASOPB_TOKEN_DB", db_path)
        result = runner.invoke(token_usage_cli, ["trends"])
        assert result.exit_code == 0
        assert "No historical runs found" in result.output

    def test_show_nonexistent_run(self, runner, db_path, monkeypatch):
        """Verify 'show' with nonexistent run_id produces clean error."""
        monkeypatch.setenv("ASOPB_TOKEN_DB", db_path)
        result = runner.invoke(token_usage_cli, ["show", "run_nonexistent_12345678"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()
