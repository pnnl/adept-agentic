"""Data models for token utilization aggregation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class GenerationRecord:
    """Single LLM generation observation."""

    id: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    timestamp: Optional[datetime] = None
    name: str = ""
    trace_id: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def date_key(self) -> str:
        if self.timestamp:
            return self.timestamp.strftime("%Y-%m-%d")
        return "unknown"


@dataclass
class CostModel:
    """Per-model token pricing."""

    name: str
    input_cost_per_million: float
    output_cost_per_million: float

    def compute(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1_000_000 * self.input_cost_per_million
            + output_tokens / 1_000_000 * self.output_cost_per_million
        )


COST_MODELS: dict[str, CostModel] = {
    "azure-o4-mini": CostModel("azure-o4-mini", 1.10, 4.40),
    "azure-gpt-4o": CostModel("azure-gpt-4o", 2.50, 10.00),
    "bedrock-claude-sonnet-4": CostModel("bedrock-claude-sonnet-4", 3.00, 15.00),
    "bedrock-claude-opus": CostModel("bedrock-claude-opus", 15.00, 75.00),
    "bedrock-claude-haiku": CostModel("bedrock-claude-haiku", 0.25, 1.25),
    "openai-gpt-4o": CostModel("openai-gpt-4o", 2.50, 10.00),
    "openai-gpt-4o-mini": CostModel("openai-gpt-4o-mini", 0.15, 0.60),
}


@dataclass
class AggregationFilters:
    """Filters for querying generation data."""

    from_date: Optional[str] = None
    to_date: Optional[str] = None
    model: Optional[str] = None
    min_input_tokens: int = 0
    max_input_tokens: Optional[int] = None
    name_pattern: Optional[str] = None
    trace_id: Optional[str] = None
    dast_fingerprint_threshold: int = 15000

    def matches(self, record: GenerationRecord) -> bool:
        if self.from_date:
            if record.date_key == "unknown" or record.date_key < self.from_date:
                return False
        if self.to_date:
            if record.date_key == "unknown" or record.date_key > self.to_date:
                return False
        if self.model and self.model.lower() not in record.model.lower():
            return False
        if record.input_tokens < self.min_input_tokens:
            return False
        if self.max_input_tokens and record.input_tokens > self.max_input_tokens:
            return False
        if self.name_pattern and self.name_pattern.lower() not in record.name.lower():
            return False
        if self.trace_id and self.trace_id != record.trace_id:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "from_date": self.from_date,
            "to_date": self.to_date,
            "model": self.model,
            "min_input_tokens": self.min_input_tokens,
            "max_input_tokens": self.max_input_tokens,
            "name_pattern": self.name_pattern,
            "trace_id": self.trace_id,
            "dast_fingerprint_threshold": self.dast_fingerprint_threshold,
        }


@dataclass
class ModelBreakdown:
    """Aggregated stats for a single model."""

    model: str
    count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0


@dataclass
class DateBreakdown:
    """Aggregated stats for a single date."""

    date: str
    count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0


@dataclass
class UtilizationReport:
    """Complete token utilization report."""

    generated_at: datetime
    backend_name: str
    total_generations: int
    dast_probe_count: int
    regular_call_count: int
    dast_input_tokens: int
    dast_output_tokens: int
    dast_total_tokens: int
    regular_input_tokens: int
    regular_output_tokens: int
    regular_total_tokens: int
    cost_model_name: str
    dast_cost: float
    regular_cost: float
    by_model: list[ModelBreakdown] = field(default_factory=list)
    by_date: list[DateBreakdown] = field(default_factory=list)
    filters_applied: Optional[AggregationFilters] = None

    @property
    def total_cost(self) -> float:
        return self.dast_cost + self.regular_cost

    @property
    def avg_input_per_probe(self) -> int:
        if self.dast_probe_count == 0:
            return 0
        return self.dast_input_tokens // self.dast_probe_count

    @property
    def avg_output_per_probe(self) -> int:
        if self.dast_probe_count == 0:
            return 0
        return self.dast_output_tokens // self.dast_probe_count

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at.isoformat(),
            "backend_name": self.backend_name,
            "total_generations": self.total_generations,
            "dast_probe_count": self.dast_probe_count,
            "regular_call_count": self.regular_call_count,
            "dast_input_tokens": self.dast_input_tokens,
            "dast_output_tokens": self.dast_output_tokens,
            "dast_total_tokens": self.dast_total_tokens,
            "dast_cost": self.dast_cost,
            "regular_input_tokens": self.regular_input_tokens,
            "regular_output_tokens": self.regular_output_tokens,
            "regular_total_tokens": self.regular_total_tokens,
            "regular_cost": self.regular_cost,
            "cost_model_name": self.cost_model_name,
            "total_cost": self.total_cost,
            "avg_input_per_probe": self.avg_input_per_probe,
            "avg_output_per_probe": self.avg_output_per_probe,
            "filters_applied": self.filters_applied.to_dict() if self.filters_applied else None,
            "by_model": [
                {"model": m.model, "count": m.count, "input": m.input_tokens,
                 "output": m.output_tokens, "total": m.total_tokens, "cost": m.cost}
                for m in self.by_model
            ],
            "by_date": [
                {"date": d.date, "count": d.count, "input": d.input_tokens,
                 "output": d.output_tokens, "total": d.total_tokens, "cost": d.cost}
                for d in self.by_date
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def format_text(self) -> str:
        lines = []
        lines.append("=" * 70)
        lines.append("TOKEN UTILIZATION REPORT")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"Generated:   {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Backend:     {self.backend_name}")
        lines.append(f"Cost model:  {self.cost_model_name}")
        lines.append(f"Total generations: {self.total_generations}")
        lines.append("")
        if self.filters_applied:
            lines.append("--- Filters ---")
            if self.filters_applied.from_date:
                lines.append(f"  From: {self.filters_applied.from_date}")
            if self.filters_applied.to_date:
                lines.append(f"  To:   {self.filters_applied.to_date}")
            if self.filters_applied.model:
                lines.append(f"  Model filter: {self.filters_applied.model}")
            lines.append(
                f"  DAST threshold: >= {self.filters_applied.dast_fingerprint_threshold} input tokens"
            )
            lines.append("")

        lines.append(f"--- DAST/Red-Team Probes ({self.dast_probe_count} identified) ---")
        lines.append(f"  Input tokens:   {self.dast_input_tokens:>14,}")
        lines.append(f"  Output tokens:  {self.dast_output_tokens:>14,}")
        lines.append(f"  Total tokens:   {self.dast_total_tokens:>14,}")
        lines.append(f"  Avg input/probe:  {self.avg_input_per_probe:>12,}")
        lines.append(f"  Avg output/probe: {self.avg_output_per_probe:>12,}")
        lines.append(f"  Cost:           ${self.dast_cost:>13.4f}")
        lines.append("")
        lines.append(f"--- Regular Traffic ({self.regular_call_count} calls) ---")
        lines.append(f"  Input tokens:   {self.regular_input_tokens:>14,}")
        lines.append(f"  Output tokens:  {self.regular_output_tokens:>14,}")
        lines.append(f"  Total tokens:   {self.regular_total_tokens:>14,}")
        lines.append(f"  Cost:           ${self.regular_cost:>13.4f}")
        lines.append("")
        lines.append("--- Total Cost ---")
        lines.append(f"  DAST:           ${self.dast_cost:>13.4f}")
        lines.append(f"  Regular:        ${self.regular_cost:>13.4f}")
        lines.append(f"  TOTAL:          ${self.total_cost:>13.4f}")
        lines.append("")

        if self.by_model:
            lines.append("--- Breakdown by Model ---")
            for m in sorted(self.by_model, key=lambda x: -x.total_tokens):
                lines.append(f"  {m.model}")
                lines.append(
                    f"    Count: {m.count:>5}  |  "
                    f"Input: {m.input_tokens:>12,}  |  "
                    f"Output: {m.output_tokens:>10,}  |  "
                    f"Cost: ${m.cost:.4f}"
                )
            lines.append("")

        if self.by_date:
            lines.append("--- Breakdown by Date ---")
            for d in sorted(self.by_date, key=lambda x: x.date):
                lines.append(
                    f"  {d.date}:  {d.count:>4} calls  |  "
                    f"{d.total_tokens:>12,} tokens  |  "
                    f"${d.cost:.4f}"
                )
            lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)

    def print_summary(self) -> None:
        print(self.format_text())
