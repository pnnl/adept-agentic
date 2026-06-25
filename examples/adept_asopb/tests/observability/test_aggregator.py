"""Unit tests for the aggregation engine."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from asopb.observability.aggregator import TokenUtilizationAggregator
from asopb.observability.backends.base import BackendConfig, ObservabilityBackend
from asopb.observability.models import AggregationFilters, CostModel, GenerationRecord


class MockBackend(ObservabilityBackend):
    """In-memory backend for testing."""

    def __init__(self, records: list[GenerationRecord]):
        super().__init__(BackendConfig())
        self._records = records

    @property
    def name(self) -> str:
        return "Mock"

    def validate_config(self) -> None:
        pass

    def fetch_generations(self, page_limit=50) -> list[GenerationRecord]:
        return self._records


def _make_records():
    return [
        # DAST probes (>=15000 input tokens)
        GenerationRecord(
            id="dast-1", model="AzureChatOpenAI", input_tokens=20000, output_tokens=400,
            total_tokens=20400, timestamp=datetime(2026, 5, 26),
        ),
        GenerationRecord(
            id="dast-2", model="AzureChatOpenAI", input_tokens=22000, output_tokens=350,
            total_tokens=22350, timestamp=datetime(2026, 5, 26),
        ),
        GenerationRecord(
            id="dast-3", model="ChatLiteLLM", input_tokens=18000, output_tokens=500,
            total_tokens=18500, timestamp=datetime(2026, 5, 28),
        ),
        # Regular calls (<15000 input tokens)
        GenerationRecord(
            id="reg-1", model="AzureChatOpenAI", input_tokens=2000, output_tokens=800,
            total_tokens=2800, timestamp=datetime(2026, 5, 26),
        ),
        GenerationRecord(
            id="reg-2", model="AzureChatOpenAI", input_tokens=500, output_tokens=200,
            total_tokens=700, timestamp=datetime(2026, 5, 28),
        ),
    ]


class TestTokenUtilizationAggregator:
    def test_aggregate_classifies_dast_vs_regular(self):
        backend = MockBackend(_make_records())
        aggregator = TokenUtilizationAggregator(backend)
        report = aggregator.aggregate()

        assert report.dast_probe_count == 3
        assert report.regular_call_count == 2
        assert report.total_generations == 5

    def test_aggregate_sums_tokens(self):
        backend = MockBackend(_make_records())
        aggregator = TokenUtilizationAggregator(backend)
        report = aggregator.aggregate()

        assert report.dast_input_tokens == 60000  # 20000 + 22000 + 18000
        assert report.dast_output_tokens == 1250  # 400 + 350 + 500
        assert report.regular_input_tokens == 2500  # 2000 + 500
        assert report.regular_output_tokens == 1000  # 800 + 200

    def test_aggregate_computes_cost(self):
        backend = MockBackend(_make_records())
        aggregator = TokenUtilizationAggregator(backend)
        report = aggregator.aggregate(cost_model="azure-o4-mini")

        # DAST: 60000/1M * 1.10 + 1250/1M * 4.40 = 0.066 + 0.0055 = 0.0715
        assert report.dast_cost == pytest.approx(0.0715, abs=0.001)
        assert report.cost_model_name == "azure-o4-mini"

    def test_aggregate_with_custom_cost_model(self):
        backend = MockBackend(_make_records())
        aggregator = TokenUtilizationAggregator(backend)
        custom = CostModel("custom", 10.0, 50.0)
        report = aggregator.aggregate(cost_model=custom)
        assert report.cost_model_name == "custom"
        assert report.dast_cost > 0

    def test_aggregate_by_model_breakdown(self):
        backend = MockBackend(_make_records())
        aggregator = TokenUtilizationAggregator(backend)
        report = aggregator.aggregate()

        models = {m.model: m for m in report.by_model}
        assert "AzureChatOpenAI" in models
        assert "ChatLiteLLM" in models
        assert models["AzureChatOpenAI"].count == 4  # 2 dast + 2 regular
        assert models["ChatLiteLLM"].count == 1

    def test_aggregate_by_date_breakdown(self):
        backend = MockBackend(_make_records())
        aggregator = TokenUtilizationAggregator(backend)
        report = aggregator.aggregate()

        dates = {d.date: d for d in report.by_date}
        assert "2026-05-26" in dates
        assert "2026-05-28" in dates
        assert dates["2026-05-26"].count == 3
        assert dates["2026-05-28"].count == 2

    def test_aggregate_with_date_filter(self):
        backend = MockBackend(_make_records())
        aggregator = TokenUtilizationAggregator(backend)
        filters = AggregationFilters(from_date="2026-05-27")
        report = aggregator.aggregate(filters=filters)

        assert report.total_generations == 2  # Only 2026-05-28 records

    def test_aggregate_with_model_filter(self):
        backend = MockBackend(_make_records())
        aggregator = TokenUtilizationAggregator(backend)
        filters = AggregationFilters(model="LiteLLM")
        report = aggregator.aggregate(filters=filters)

        assert report.total_generations == 1
        assert report.dast_probe_count == 1

    def test_aggregate_custom_dast_threshold(self):
        backend = MockBackend(_make_records())
        aggregator = TokenUtilizationAggregator(backend)
        filters = AggregationFilters(dast_fingerprint_threshold=21000)
        report = aggregator.aggregate(filters=filters)

        # Only dast-2 (22000) qualifies now
        assert report.dast_probe_count == 1
        assert report.regular_call_count == 4

    def test_aggregate_unknown_cost_model_raises(self):
        backend = MockBackend([])
        aggregator = TokenUtilizationAggregator(backend)
        with pytest.raises(ValueError, match="Unknown cost model"):
            aggregator.aggregate(cost_model="nonexistent")

    def test_aggregate_empty_records(self):
        backend = MockBackend([])
        aggregator = TokenUtilizationAggregator(backend)
        report = aggregator.aggregate()

        assert report.total_generations == 0
        assert report.dast_probe_count == 0
        assert report.total_cost == 0.0
        assert report.avg_input_per_probe == 0
