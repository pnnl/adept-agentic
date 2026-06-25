"""Integration test for Langfuse backend (requires live Langfuse instance).

Only runs when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.
"""

import os

import pytest

from asopb.observability.backends.langfuse_backend import LangfuseBackend
from asopb.observability.backends.base import BackendConfig
from asopb.observability.aggregator import TokenUtilizationAggregator
from asopb.observability.models import AggregationFilters


LANGFUSE_AVAILABLE = bool(
    os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
)


@pytest.mark.integration
@pytest.mark.skipif(not LANGFUSE_AVAILABLE, reason="LANGFUSE_PUBLIC_KEY/SECRET_KEY not set")
class TestLangfuseIntegration:
    @pytest.fixture
    def backend(self):
        return LangfuseBackend(BackendConfig(
            endpoint=os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        ))

    def test_connection(self, backend):
        assert backend.test_connection() is True

    def test_fetch_generations(self, backend):
        records = backend.fetch_generations(page_limit=2)
        assert len(records) > 0
        assert records[0].model is not None
        assert records[0].input_tokens >= 0

    def test_full_aggregation(self, backend):
        aggregator = TokenUtilizationAggregator(backend)
        report = aggregator.aggregate(
            filters=AggregationFilters(dast_fingerprint_threshold=15000),
            cost_model="azure-o4-mini",
        )
        assert report.total_generations > 0
        assert report.backend_name == "Langfuse"
        assert report.total_cost >= 0

    def test_aggregation_with_date_filter(self, backend):
        aggregator = TokenUtilizationAggregator(backend)
        report = aggregator.aggregate(
            filters=AggregationFilters(from_date="2026-05-28"),
        )
        for d in report.by_date:
            assert d.date >= "2026-05-28"
