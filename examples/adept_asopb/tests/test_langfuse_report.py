"""
Tests for ASOPB Langfuse Report Generator.

Covers:
- DomainStats aggregation and cost estimation
- EvalSessionReport generation and formatting
- LangfuseReportGenerator with mocked API responses
- Local trace file parsing (offline mode)
- CLI argument handling
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asopb.config import LangfuseConfig
from asopb.llm.langfuse_report import (
    DomainStats,
    EvalSessionReport,
    LangfuseReportGenerator,
)


class TestDomainStats:
    """Test DomainStats dataclass and computed properties."""

    def test_empty_stats(self):
        stats = DomainStats(domain_id="D4")
        assert stats.call_count == 0
        assert stats.total_tokens == 0
        assert stats.avg_latency_ms == 0.0
        assert stats.estimated_cost_usd == 0.0

    def test_total_tokens(self):
        stats = DomainStats(domain_id="D5", total_input_tokens=1000, total_output_tokens=500)
        assert stats.total_tokens == 1500

    def test_avg_latency(self):
        stats = DomainStats(domain_id="D2", call_count=4, total_latency_ms=2000.0)
        assert stats.avg_latency_ms == 500.0

    def test_cost_estimation(self):
        stats = DomainStats(
            domain_id="D8",
            total_input_tokens=1_000_000,
            total_output_tokens=100_000,
        )
        # $3/1M input + $15/1M output = $3 + $1.50 = $4.50
        assert stats.estimated_cost_usd == pytest.approx(4.5, rel=0.01)

    def test_to_dict(self):
        stats = DomainStats(
            domain_id="D4",
            call_count=3,
            total_input_tokens=900,
            total_output_tokens=300,
            total_latency_ms=1500.0,
            models_used={"claude-3-sonnet": 3},
            phases={"design_assessment": 2, "implementation_grading": 1},
            tiers={"T1": 2, "T2": 1},
            errors=0,
        )
        d = stats.to_dict()
        assert d["domain_id"] == "D4"
        assert d["call_count"] == 3
        assert d["total_tokens"] == 1200
        assert d["avg_latency_ms"] == 500.0
        assert d["models_used"] == {"claude-3-sonnet": 3}


class TestEvalSessionReport:
    """Test EvalSessionReport structure and formatting."""

    def test_empty_report(self):
        report = EvalSessionReport(session_id="asopb-eval-test123")
        assert report.session_id == "asopb-eval-test123"
        assert report.trace_count == 0
        assert report.total_tokens == 0
        assert report.estimated_cost_usd == 0.0
        assert report.generated_at != ""

    def test_total_tokens(self):
        report = EvalSessionReport(
            session_id="test",
            total_input_tokens=5000,
            total_output_tokens=2000,
        )
        assert report.total_tokens == 7000

    def test_avg_latency(self):
        report = EvalSessionReport(
            session_id="test",
            generation_count=10,
            total_latency_ms=5000.0,
        )
        assert report.avg_latency_ms == 500.0

    def test_cost_from_domains(self):
        report = EvalSessionReport(session_id="test")
        report.domains["D4"] = DomainStats(
            domain_id="D4",
            total_input_tokens=500_000,
            total_output_tokens=50_000,
        )
        report.domains["D8"] = DomainStats(
            domain_id="D8",
            total_input_tokens=500_000,
            total_output_tokens=50_000,
        )
        # Each domain: $1.5 + $0.75 = $2.25, total $4.50
        assert report.estimated_cost_usd == pytest.approx(4.5, rel=0.01)

    def test_to_dict_structure(self):
        report = EvalSessionReport(
            session_id="asopb-eval-abc",
            trace_count=5,
            generation_count=8,
            total_input_tokens=4000,
            total_output_tokens=2000,
            models={"claude-3-sonnet": 5, "claude-3-opus": 3},
            phases={"design_assessment": 5, "summary": 3},
        )
        d = report.to_dict()
        assert d["session_id"] == "asopb-eval-abc"
        assert d["summary"]["trace_count"] == 5
        assert d["summary"]["generation_count"] == 8
        assert d["summary"]["total_tokens"] == 6000
        assert "claude-3-sonnet" in d["summary"]["models"]

    def test_to_json(self):
        report = EvalSessionReport(session_id="test-json")
        output = report.to_json()
        parsed = json.loads(output)
        assert parsed["session_id"] == "test-json"

    def test_to_text_formatting(self):
        report = EvalSessionReport(
            session_id="asopb-eval-textfmt",
            trace_count=3,
            generation_count=6,
            total_input_tokens=3000,
            total_output_tokens=1500,
            total_latency_ms=3000.0,
            models={"claude-3-sonnet": 6},
            phases={"design_assessment": 4, "report_generation": 2},
        )
        report.domains["D4"] = DomainStats(
            domain_id="D4",
            call_count=4,
            total_input_tokens=2000,
            total_output_tokens=1000,
            total_latency_ms=2000.0,
        )
        report.domains["D8"] = DomainStats(
            domain_id="D8",
            call_count=2,
            total_input_tokens=1000,
            total_output_tokens=500,
            total_latency_ms=1000.0,
        )

        text = report.to_text()
        assert "ASOPB Langfuse Evaluation Report" in text
        assert "asopb-eval-textfmt" in text
        assert "Traces:" in text
        assert "D4" in text
        assert "D8" in text
        assert "MODELS USED" in text
        assert "claude-3-sonnet" in text


class TestLangfuseReportGeneratorInit:
    """Test LangfuseReportGenerator initialization."""

    def test_init_with_config(self):
        config = LangfuseConfig(
            enabled=True,
            public_key="pk-test",
            secret_key="sk-test",
            host="http://localhost:3000",
        )
        gen = LangfuseReportGenerator(config)
        assert gen.config.public_key == "pk-test"
        assert not gen._initialized

    def test_init_default_config(self):
        gen = LangfuseReportGenerator()
        assert gen.config is not None
        assert gen._session is None


class TestLangfuseReportGeneratorAPI:
    """Test LangfuseReportGenerator with mocked API responses."""

    @pytest.fixture
    def generator(self):
        config = LangfuseConfig(
            enabled=True,
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
            host="http://langfuse-test:3000",
        )
        return LangfuseReportGenerator(config)

    def test_list_sessions_filters_asopb(self, generator):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "asopb-eval-abc123", "traces": 5},
                {"id": "other-session-xyz", "traces": 2},
                {"id": "asopb-eval-def456", "traces": 8},
            ]
        }

        with patch("requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.get.return_value = mock_response
            MockSession.return_value = mock_session
            generator._session = mock_session
            generator._host = "http://langfuse-test:3000"
            generator._initialized = True

            sessions = generator.list_sessions()
            assert len(sessions) == 2
            assert sessions[0]["id"] == "asopb-eval-abc123"
            assert sessions[1]["id"] == "asopb-eval-def456"

    def test_generate_session_report_basic(self, generator):
        traces_response = MagicMock()
        traces_response.status_code = 200
        traces_response.json.return_value = {
            "data": [
                {
                    "id": "trace-1",
                    "metadata": {
                        "asopb_domain": "D4",
                        "asopb_control": "D4.1",
                        "asopb_tier": "T1",
                        "asopb_phase": "design_assessment",
                        "session_id": "asopb-eval-test",
                    },
                    "timestamp": "2026-05-22T01:00:00Z",
                },
            ]
        }

        observations_response = MagicMock()
        observations_response.status_code = 200
        observations_response.json.return_value = {
            "data": [
                {
                    "type": "GENERATION",
                    "model": "claude-3-sonnet",
                    "usage": {"input": 500, "output": 200},
                    "latency": 1200,
                    "startTime": "2026-05-22T01:00:01Z",
                    "level": "DEFAULT",
                    "statusMessage": None,
                },
            ]
        }

        mock_session = MagicMock()

        def mock_get(url, **kwargs):
            if "/traces" in url and "traceId" not in str(kwargs):
                return traces_response
            return observations_response

        mock_session.get.side_effect = mock_get
        generator._session = mock_session
        generator._host = "http://langfuse-test:3000"
        generator._initialized = True

        report = generator.generate_session_report("asopb-eval-test")

        assert report is not None
        assert report.session_id == "asopb-eval-test"
        assert report.trace_count == 1
        assert report.generation_count == 1
        assert report.total_input_tokens == 500
        assert report.total_output_tokens == 200
        assert "D4" in report.domains
        assert report.domains["D4"].call_count == 1
        assert report.models.get("claude-3-sonnet") == 1

    def test_generate_returns_none_without_credentials(self):
        config = LangfuseConfig(enabled=True, public_key=None, secret_key=None)
        gen = LangfuseReportGenerator(config)
        report = gen.generate_session_report("test-session")
        assert report is None


class TestLangfuseReportGeneratorLocal:
    """Test offline/local trace file parsing."""

    def test_generate_from_local_traces(self, tmp_path):
        traces_file = tmp_path / "traces.json"
        traces_file.write_text(json.dumps({
            "data": [
                {
                    "id": "trace-local-1",
                    "metadata": {
                        "session_id": "asopb-eval-local",
                        "asopb_domain": "D5",
                        "asopb_phase": "design_assessment",
                    },
                    "observations": [
                        {
                            "type": "GENERATION",
                            "model": "claude-3-opus",
                            "usage": {"input": 800, "output": 400},
                            "latency": 2000,
                        }
                    ],
                },
                {
                    "id": "trace-local-2",
                    "metadata": {
                        "session_id": "asopb-eval-local",
                        "asopb_domain": "D8",
                        "asopb_phase": "implementation_grading",
                    },
                    "observations": [
                        {
                            "type": "GENERATION",
                            "model": "claude-3-sonnet",
                            "usage": {"input": 600, "output": 300},
                            "latency": 1500,
                        },
                        {
                            "type": "SPAN",
                            "name": "not-a-generation",
                        },
                    ],
                },
            ]
        }))

        gen = LangfuseReportGenerator()
        report = gen.generate_from_local_traces(traces_file)

        assert report is not None
        assert report.session_id == "asopb-eval-local"
        assert report.trace_count == 2
        assert report.generation_count == 2
        assert report.total_input_tokens == 1400
        assert report.total_output_tokens == 700
        assert "D5" in report.domains
        assert "D8" in report.domains
        assert report.domains["D5"].call_count == 1
        assert report.domains["D8"].call_count == 1
        assert report.models["claude-3-opus"] == 1
        assert report.models["claude-3-sonnet"] == 1

    def test_generate_from_missing_file(self, tmp_path):
        gen = LangfuseReportGenerator()
        report = gen.generate_from_local_traces(tmp_path / "nonexistent.json")
        assert report is None

    def test_generate_from_list_format(self, tmp_path):
        """Support traces as a plain JSON array (alternative export format)."""
        traces_file = tmp_path / "traces_list.json"
        traces_file.write_text(json.dumps([
            {
                "id": "trace-arr-1",
                "metadata": {"asopb_domain": "D2", "session_id": "asopb-eval-arr"},
                "observations": [
                    {"type": "GENERATION", "model": "gpt-4o", "usage": {"input": 100, "output": 50}, "latency": 500}
                ],
            }
        ]))

        gen = LangfuseReportGenerator()
        report = gen.generate_from_local_traces(traces_file)
        assert report is not None
        assert report.trace_count == 1
        assert report.generation_count == 1
        assert "D2" in report.domains
