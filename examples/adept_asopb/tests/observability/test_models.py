"""Unit tests for observability data models."""

import pytest
from datetime import datetime

from asopb.observability.models import (
    AggregationFilters,
    CostModel,
    DateBreakdown,
    GenerationRecord,
    ModelBreakdown,
    UtilizationReport,
    COST_MODELS,
)


class TestGenerationRecord:
    def test_date_key_with_timestamp(self):
        record = GenerationRecord(
            id="test-1", model="gpt-4o", input_tokens=100, output_tokens=50,
            total_tokens=150, timestamp=datetime(2026, 5, 28, 12, 0, 0),
        )
        assert record.date_key == "2026-05-28"

    def test_date_key_without_timestamp(self):
        record = GenerationRecord(
            id="test-2", model="gpt-4o", input_tokens=100, output_tokens=50,
            total_tokens=150,
        )
        assert record.date_key == "unknown"


class TestCostModel:
    def test_compute_basic(self):
        model = CostModel("test", input_cost_per_million=1.0, output_cost_per_million=4.0)
        cost = model.compute(1_000_000, 500_000)
        assert cost == pytest.approx(3.0)  # 1.0 + 2.0

    def test_compute_zero_tokens(self):
        model = CostModel("test", input_cost_per_million=10.0, output_cost_per_million=40.0)
        assert model.compute(0, 0) == 0.0

    def test_azure_o4_mini_exists(self):
        assert "azure-o4-mini" in COST_MODELS
        m = COST_MODELS["azure-o4-mini"]
        assert m.input_cost_per_million == 1.10
        assert m.output_cost_per_million == 4.40


class TestAggregationFilters:
    def test_matches_no_filters(self):
        f = AggregationFilters()
        record = GenerationRecord(
            id="r1", model="gpt-4o", input_tokens=500, output_tokens=100,
            total_tokens=600, timestamp=datetime(2026, 5, 20),
        )
        assert f.matches(record) is True

    def test_matches_from_date(self):
        f = AggregationFilters(from_date="2026-05-25")
        old = GenerationRecord(
            id="r1", model="gpt-4o", input_tokens=500, output_tokens=100,
            total_tokens=600, timestamp=datetime(2026, 5, 20),
        )
        new = GenerationRecord(
            id="r2", model="gpt-4o", input_tokens=500, output_tokens=100,
            total_tokens=600, timestamp=datetime(2026, 5, 26),
        )
        assert f.matches(old) is False
        assert f.matches(new) is True

    def test_matches_model_filter(self):
        f = AggregationFilters(model="azure")
        azure_rec = GenerationRecord(
            id="r1", model="AzureChatOpenAI", input_tokens=500, output_tokens=100,
            total_tokens=600,
        )
        bedrock_rec = GenerationRecord(
            id="r2", model="ChatLiteLLM", input_tokens=500, output_tokens=100,
            total_tokens=600,
        )
        assert f.matches(azure_rec) is True
        assert f.matches(bedrock_rec) is False

    def test_matches_min_input_tokens(self):
        f = AggregationFilters(min_input_tokens=1000)
        small = GenerationRecord(id="r1", model="m", input_tokens=500, output_tokens=50, total_tokens=550)
        large = GenerationRecord(id="r2", model="m", input_tokens=2000, output_tokens=50, total_tokens=2050)
        assert f.matches(small) is False
        assert f.matches(large) is True

    def test_to_dict(self):
        f = AggregationFilters(from_date="2026-05-01", model="gpt")
        d = f.to_dict()
        assert d["from_date"] == "2026-05-01"
        assert d["model"] == "gpt"
        assert d["dast_fingerprint_threshold"] == 15000


class TestUtilizationReport:
    def _make_report(self):
        return UtilizationReport(
            generated_at=datetime(2026, 5, 28, 20, 0, 0),
            backend_name="Langfuse",
            total_generations=100,
            dast_probe_count=80,
            regular_call_count=20,
            dast_input_tokens=1_600_000,
            dast_output_tokens=32_000,
            dast_total_tokens=1_632_000,
            regular_input_tokens=40_000,
            regular_output_tokens=10_000,
            regular_total_tokens=50_000,
            cost_model_name="azure-o4-mini",
            dast_cost=1.9008,
            regular_cost=0.088,
            by_model=[ModelBreakdown(model="AzureChatOpenAI", count=100, input_tokens=1_640_000, output_tokens=42_000, total_tokens=1_682_000, cost=1.9888)],
            by_date=[DateBreakdown(date="2026-05-28", count=100, input_tokens=1_640_000, output_tokens=42_000, total_tokens=1_682_000, cost=1.9888)],
        )

    def test_total_cost(self):
        report = self._make_report()
        assert report.total_cost == pytest.approx(1.9888)

    def test_avg_input_per_probe(self):
        report = self._make_report()
        assert report.avg_input_per_probe == 20000

    def test_to_dict(self):
        report = self._make_report()
        d = report.to_dict()
        assert d["backend_name"] == "Langfuse"
        assert d["dast_probe_count"] == 80
        assert "by_model" in d
        assert "by_date" in d

    def test_to_json(self):
        report = self._make_report()
        j = report.to_json()
        assert '"backend_name": "Langfuse"' in j

    def test_format_text(self):
        report = self._make_report()
        text = report.format_text()
        assert "TOKEN UTILIZATION REPORT" in text
        assert "Langfuse" in text
        assert "DAST" in text
