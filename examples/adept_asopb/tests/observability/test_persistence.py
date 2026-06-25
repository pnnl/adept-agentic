"""Unit tests for SQLite persistence layer."""

import json
import os
import tempfile

import pytest
from datetime import datetime

from asopb.observability.models import (
    AggregationFilters,
    DateBreakdown,
    ModelBreakdown,
    UtilizationReport,
)
from asopb.observability.persistence import TokenUtilizationStore


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def store(tmp_db):
    return TokenUtilizationStore(db_path=tmp_db)


def _make_report(probe_count=10, cost=5.0):
    return UtilizationReport(
        generated_at=datetime(2026, 5, 28, 20, 0, 0),
        backend_name="Langfuse",
        total_generations=probe_count + 5,
        dast_probe_count=probe_count,
        regular_call_count=5,
        dast_input_tokens=probe_count * 20000,
        dast_output_tokens=probe_count * 400,
        dast_total_tokens=probe_count * 20400,
        regular_input_tokens=10000,
        regular_output_tokens=2000,
        regular_total_tokens=12000,
        cost_model_name="azure-o4-mini",
        dast_cost=cost,
        regular_cost=0.02,
        by_model=[ModelBreakdown(model="AzureChatOpenAI", count=15, input_tokens=210000, output_tokens=6000, total_tokens=216000, cost=cost + 0.02)],
        by_date=[DateBreakdown(date="2026-05-28", count=15, input_tokens=210000, output_tokens=6000, total_tokens=216000, cost=cost + 0.02)],
        filters_applied=AggregationFilters(from_date="2026-05-01"),
    )


class TestTokenUtilizationStore:
    def test_save_and_list(self, store):
        report = _make_report()
        run_id = store.save_report(report)
        assert run_id.startswith("run_")

        runs = store.list_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == run_id
        assert runs[0]["backend"] == "Langfuse"
        assert runs[0]["total_generations"] == 15

    def test_get_run(self, store):
        report = _make_report()
        run_id = store.save_report(report)

        data = store.get_run(run_id)
        assert data is not None
        assert data["dast_probe_count"] == 10
        assert data["total_cost"] == pytest.approx(5.02)
        assert "report" in data

    def test_get_run_nonexistent(self, store):
        assert store.get_run("run_nonexistent") is None

    def test_get_trends(self, store):
        for i in range(5):
            store.save_report(_make_report(probe_count=10 + i, cost=5.0 + i))

        trends = store.get_trends(last_n=3)
        assert len(trends) == 3
        # Each trend entry has required fields
        for t in trends:
            assert "generated_at" in t
            assert "total_cost" in t
            assert "dast_probe_count" in t
            assert t["total_cost"] > 0

    def test_get_daily_breakdown(self, store):
        report = _make_report()
        run_id = store.save_report(report)

        daily = store.get_daily_breakdown(run_id)
        assert len(daily) == 1
        assert daily[0]["date"] == "2026-05-28"
        assert daily[0]["count"] == 15

    def test_multiple_runs_independent(self, store):
        r1 = store.save_report(_make_report(probe_count=5, cost=2.0))
        r2 = store.save_report(_make_report(probe_count=20, cost=10.0))

        runs = store.list_runs()
        assert len(runs) == 2

        d1 = store.get_run(r1)
        d2 = store.get_run(r2)
        assert d1["dast_probe_count"] == 5
        assert d2["dast_probe_count"] == 20

    def test_report_json_roundtrip(self, store):
        report = _make_report()
        run_id = store.save_report(report)

        data = store.get_run(run_id)
        parsed = data["report"]
        assert parsed["backend_name"] == "Langfuse"
        assert parsed["dast_probe_count"] == 10
        assert parsed["by_model"][0]["model"] == "AzureChatOpenAI"
