"""Core aggregation engine for token utilization data."""

from __future__ import annotations

from datetime import datetime

from .backends.base import ObservabilityBackend
from .models import (
    COST_MODELS,
    AggregationFilters,
    CostModel,
    DateBreakdown,
    GenerationRecord,
    ModelBreakdown,
    UtilizationReport,
)


class TokenUtilizationAggregator:
    """Aggregates token utilization data from an observability backend.

    Classifies traffic into DAST/red-team probes vs. regular usage based
    on input token fingerprinting, computes costs, and generates reports.

    Usage:
        backend = BackendFactory.create("langfuse", config={...})
        aggregator = TokenUtilizationAggregator(backend)
        report = aggregator.aggregate(
            filters=AggregationFilters(from_date="2026-05-01"),
            cost_model="azure-o4-mini",
        )
        report.print_summary()
    """

    def __init__(self, backend: ObservabilityBackend):
        self._backend = backend

    def aggregate(
        self,
        filters: AggregationFilters | None = None,
        cost_model: str | CostModel = "azure-o4-mini",
        page_limit: int = 50,
    ) -> UtilizationReport:
        """Run full aggregation pipeline.

        Args:
            filters: Optional filters for date range, model, token thresholds.
            cost_model: Name of a built-in cost model or a CostModel instance.
            page_limit: Max pages to fetch from backend.

        Returns:
            Complete UtilizationReport with breakdowns and cost analysis.
        """
        if filters is None:
            filters = AggregationFilters()

        if isinstance(cost_model, str):
            if cost_model not in COST_MODELS:
                available = ", ".join(sorted(COST_MODELS.keys()))
                raise ValueError(f"Unknown cost model '{cost_model}'. Available: {available}")
            pricing = COST_MODELS[cost_model]
        else:
            pricing = cost_model

        records = self._backend.fetch_generations(page_limit=page_limit)
        filtered = [r for r in records if filters.matches(r)]
        dast_records, regular_records = self._classify(filtered, filters.dast_fingerprint_threshold)

        by_model = self._aggregate_by_model(filtered, pricing)
        by_date = self._aggregate_by_date(filtered, pricing)

        dast_input = sum(r.input_tokens for r in dast_records)
        dast_output = sum(r.output_tokens for r in dast_records)
        reg_input = sum(r.input_tokens for r in regular_records)
        reg_output = sum(r.output_tokens for r in regular_records)

        return UtilizationReport(
            generated_at=datetime.now(),
            backend_name=self._backend.name,
            total_generations=len(filtered),
            dast_probe_count=len(dast_records),
            regular_call_count=len(regular_records),
            dast_input_tokens=dast_input,
            dast_output_tokens=dast_output,
            dast_total_tokens=dast_input + dast_output,
            regular_input_tokens=reg_input,
            regular_output_tokens=reg_output,
            regular_total_tokens=reg_input + reg_output,
            cost_model_name=pricing.name,
            dast_cost=pricing.compute(dast_input, dast_output),
            regular_cost=pricing.compute(reg_input, reg_output),
            by_model=by_model,
            by_date=by_date,
            filters_applied=filters,
        )

    def _classify(
        self, records: list[GenerationRecord], threshold: int
    ) -> tuple[list[GenerationRecord], list[GenerationRecord]]:
        """Classify records into DAST probes vs. regular traffic."""
        dast = []
        regular = []
        for r in records:
            if r.input_tokens >= threshold:
                dast.append(r)
            else:
                regular.append(r)
        return dast, regular

    def _aggregate_by_model(
        self, records: list[GenerationRecord], pricing: CostModel
    ) -> list[ModelBreakdown]:
        buckets: dict[str, ModelBreakdown] = {}
        for r in records:
            if r.model not in buckets:
                buckets[r.model] = ModelBreakdown(model=r.model)
            b = buckets[r.model]
            b.count += 1
            b.input_tokens += r.input_tokens
            b.output_tokens += r.output_tokens
            b.total_tokens += r.total_tokens
        for b in buckets.values():
            b.cost = pricing.compute(b.input_tokens, b.output_tokens)
        return list(buckets.values())

    def _aggregate_by_date(
        self, records: list[GenerationRecord], pricing: CostModel
    ) -> list[DateBreakdown]:
        buckets: dict[str, DateBreakdown] = {}
        for r in records:
            key = r.date_key
            if key not in buckets:
                buckets[key] = DateBreakdown(date=key)
            b = buckets[key]
            b.count += 1
            b.input_tokens += r.input_tokens
            b.output_tokens += r.output_tokens
            b.total_tokens += r.total_tokens
        for b in buckets.values():
            b.cost = pricing.compute(b.input_tokens, b.output_tokens)
        return list(buckets.values())
