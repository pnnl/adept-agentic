"""Token Utilization and Observability Module.

Factory-pattern module for querying LLM token usage from observability backends.
Supports Langfuse (native), with extensible plugin architecture for AWS CloudWatch,
Azure Monitor, and GCP Cloud Logging.

Usage:
    from asopb.observability import TokenUtilizationAggregator, BackendFactory

    backend = BackendFactory.create("langfuse", config={...})
    aggregator = TokenUtilizationAggregator(backend)
    report = aggregator.aggregate(filters=AggregationFilters(from_date="2026-05-01"))
    report.print_summary()
"""

from .aggregator import TokenUtilizationAggregator
from .backends.base import BackendConfig, ObservabilityBackend
from .factory import BackendFactory
from .models import (
    AggregationFilters,
    CostModel,
    DateBreakdown,
    GenerationRecord,
    ModelBreakdown,
    UtilizationReport,
)

__all__ = [
    "TokenUtilizationAggregator",
    "BackendFactory",
    "BackendConfig",
    "ObservabilityBackend",
    "AggregationFilters",
    "CostModel",
    "DateBreakdown",
    "GenerationRecord",
    "ModelBreakdown",
    "UtilizationReport",
]
