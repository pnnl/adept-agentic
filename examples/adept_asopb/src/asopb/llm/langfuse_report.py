"""
Langfuse Report Generator for ASOPB LLM evaluations.

Queries the Langfuse API for ASOPB evaluation session traces and generates
a summary report covering:
- Per-domain LLM call count, latency, and token usage
- Model distribution (which models were used)
- Cost estimation
- Evaluation phase breakdown (T1/T2/summary)
- Session-level aggregate statistics

Usage:
    # As CLI:
    python -m asopb.llm.langfuse_report --session-id asopb-eval-abc123
    python -m asopb.llm.langfuse_report --latest --json

    # As library:
    from asopb.llm.langfuse_report import LangfuseReportGenerator
    gen = LangfuseReportGenerator()
    report = gen.generate_session_report(session_id="asopb-eval-abc123")
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from asopb.config import LangfuseConfig
from asopb.llm.langfuse_integration import _resolve_credentials
from asopb.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DomainStats:
    """Aggregated statistics for a single ASOPB domain."""

    domain_id: str
    call_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: float = 0.0
    models_used: dict[str, int] = field(default_factory=dict)
    phases: dict[str, int] = field(default_factory=dict)
    tiers: dict[str, int] = field(default_factory=dict)
    errors: int = 0

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.call_count if self.call_count else 0.0

    @property
    def estimated_cost_usd(self) -> float:
        # Rough estimate: $3/1M input, $15/1M output (Claude Sonnet-class)
        return (self.total_input_tokens * 3.0 + self.total_output_tokens * 15.0) / 1_000_000

    def to_dict(self) -> dict:
        return {
            "domain_id": self.domain_id,
            "call_count": self.call_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "total_latency_ms": round(self.total_latency_ms, 1),
            "models_used": self.models_used,
            "phases": self.phases,
            "tiers": self.tiers,
            "errors": self.errors,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
        }


@dataclass
class EvalSessionReport:
    """Complete report for an ASOPB evaluation session."""

    session_id: str
    generated_at: str = ""
    trace_count: int = 0
    generation_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: float = 0.0
    domains: dict[str, DomainStats] = field(default_factory=dict)
    models: dict[str, int] = field(default_factory=dict)
    phases: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.generation_count if self.generation_count else 0.0

    @property
    def estimated_cost_usd(self) -> float:
        return sum(d.estimated_cost_usd for d in self.domains.values())

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "generated_at": self.generated_at,
            "summary": {
                "trace_count": self.trace_count,
                "generation_count": self.generation_count,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_tokens": self.total_tokens,
                "avg_latency_ms": round(self.avg_latency_ms, 1),
                "total_latency_ms": round(self.total_latency_ms, 1),
                "estimated_cost_usd": round(self.estimated_cost_usd, 4),
                "models": self.models,
                "phases": self.phases,
                "time_range": {
                    "start": self.time_range_start,
                    "end": self.time_range_end,
                },
            },
            "domains": {k: v.to_dict() for k, v in sorted(self.domains.items())},
            "errors": self.errors,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_text(self) -> str:
        """Human-readable report."""
        lines = []
        lines.append(f"ASOPB Langfuse Evaluation Report")
        lines.append(f"{'=' * 60}")
        lines.append(f"Session: {self.session_id}")
        lines.append(f"Generated: {self.generated_at}")
        if self.time_range_start and self.time_range_end:
            lines.append(f"Time Range: {self.time_range_start} -- {self.time_range_end}")
        lines.append("")

        lines.append(f"AGGREGATE STATISTICS")
        lines.append(f"{'-' * 40}")
        lines.append(f"  Traces:       {self.trace_count}")
        lines.append(f"  Generations:  {self.generation_count}")
        lines.append(f"  Input Tokens: {self.total_input_tokens:,}")
        lines.append(f"  Output Tokens:{self.total_output_tokens:,}")
        lines.append(f"  Total Tokens: {self.total_tokens:,}")
        lines.append(f"  Avg Latency:  {self.avg_latency_ms:.0f} ms")
        lines.append(f"  Est. Cost:    ${self.estimated_cost_usd:.4f}")
        lines.append("")

        if self.models:
            lines.append(f"MODELS USED")
            lines.append(f"{'-' * 40}")
            for model, count in sorted(self.models.items(), key=lambda x: -x[1]):
                lines.append(f"  {model}: {count} calls")
            lines.append("")

        if self.phases:
            lines.append(f"EVALUATION PHASES")
            lines.append(f"{'-' * 40}")
            for phase, count in sorted(self.phases.items()):
                lines.append(f"  {phase}: {count} calls")
            lines.append("")

        if self.domains:
            lines.append(f"PER-DOMAIN BREAKDOWN")
            lines.append(f"{'-' * 60}")
            lines.append(f"  {'Domain':<8} {'Calls':>6} {'Tokens':>10} {'Latency':>10} {'Cost':>10}")
            lines.append(f"  {'------':<8} {'-----':>6} {'------':>10} {'-------':>10} {'----':>10}")
            for domain_id in sorted(self.domains.keys()):
                d = self.domains[domain_id]
                lines.append(
                    f"  {d.domain_id:<8} {d.call_count:>6} "
                    f"{d.total_tokens:>10,} "
                    f"{d.avg_latency_ms:>8.0f}ms "
                    f"${d.estimated_cost_usd:>8.4f}"
                )
            lines.append("")

        if self.errors:
            lines.append(f"ERRORS ({len(self.errors)})")
            lines.append(f"{'-' * 40}")
            for err in self.errors[:10]:
                lines.append(f"  - {err}")
            lines.append("")

        return "\n".join(lines)


class LangfuseReportGenerator:
    """Generates evaluation reports from Langfuse trace data."""

    def __init__(self, config: Optional[LangfuseConfig] = None):
        self.config = config or LangfuseConfig()
        self._session = None
        self._host = None
        self._initialized = False

    def _init_client(self) -> bool:
        """Initialize HTTP session with Langfuse credentials."""
        if self._initialized:
            return True

        public_key, secret_key = _resolve_credentials(self.config)
        if not public_key or not secret_key:
            logger.error("Cannot generate report: Langfuse credentials not found")
            return False

        self._host = self.config.host or "http://langfuse-web:3000"

        try:
            import requests
            self._session = requests.Session()
            self._session.auth = (public_key, secret_key)
            self._session.headers.update({"Content-Type": "application/json"})
            self._initialized = True
            return True
        except ImportError:
            logger.error("requests package required: pip install requests")
            return False

    def _api_get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        """Make authenticated GET request to Langfuse API."""
        if not self._init_client():
            return None

        url = f"{self._host}/api/public{path}"
        try:
            resp = self._session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"Langfuse API {path} returned {resp.status_code}: {resp.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"Langfuse API request failed: {e}")
            return None

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """List recent ASOPB evaluation sessions from Langfuse."""
        data = self._api_get("/sessions", params={"page": 1, "limit": limit})
        if not data:
            return []

        sessions = data.get("data", [])
        return [
            s for s in sessions
            if s.get("id", "").startswith("asopb-eval-")
        ]

    def get_latest_session_id(self) -> Optional[str]:
        """Get the most recent ASOPB session ID."""
        sessions = self.list_sessions(limit=5)
        if sessions:
            return sessions[0]["id"]
        return None

    def _fetch_traces(self, session_id: str) -> list[dict]:
        """Fetch all traces for a session."""
        traces = []
        page = 1
        while True:
            data = self._api_get("/traces", params={
                "sessionId": session_id,
                "page": page,
                "limit": 50,
            })
            if not data:
                break

            page_traces = data.get("data", [])
            if not page_traces:
                break

            traces.extend(page_traces)
            if len(page_traces) < 50:
                break
            page += 1

        return traces

    def _fetch_generations(self, trace_id: str) -> list[dict]:
        """Fetch generations (LLM calls) for a trace."""
        data = self._api_get("/observations", params={
            "traceId": trace_id,
            "type": "GENERATION",
            "page": 1,
            "limit": 100,
        })
        if not data:
            return []
        return data.get("data", [])

    def _extract_metadata(self, trace: dict) -> dict:
        """Extract ASOPB metadata from trace."""
        meta = trace.get("metadata", {}) or {}
        return {
            "domain": meta.get("asopb_domain", "unknown"),
            "control": meta.get("asopb_control", ""),
            "tier": meta.get("asopb_tier", ""),
            "phase": meta.get("asopb_phase", ""),
        }

    def generate_session_report(self, session_id: Optional[str] = None) -> Optional[EvalSessionReport]:
        """Generate a complete report for an evaluation session.

        Args:
            session_id: Specific session ID, or None to use the latest.

        Returns:
            EvalSessionReport or None if session not found / API unavailable.
        """
        if not self._init_client():
            return None

        if not session_id:
            session_id = self.get_latest_session_id()
            if not session_id:
                logger.error("No ASOPB evaluation sessions found in Langfuse")
                return None

        logger.info(f"Generating report for session: {session_id}")

        traces = self._fetch_traces(session_id)
        if not traces:
            logger.warning(f"No traces found for session {session_id}")
            return EvalSessionReport(session_id=session_id, errors=["No traces found"])

        report = EvalSessionReport(session_id=session_id, trace_count=len(traces))
        timestamps = []

        for trace in traces:
            meta = self._extract_metadata(trace)
            domain_id = meta["domain"]

            if domain_id not in report.domains:
                report.domains[domain_id] = DomainStats(domain_id=domain_id)

            domain_stats = report.domains[domain_id]

            # Fetch generations for this trace
            generations = self._fetch_generations(trace["id"])

            for gen in generations:
                report.generation_count += 1
                domain_stats.call_count += 1

                # Token usage
                usage = gen.get("usage", {}) or {}
                input_tokens = usage.get("input", 0) or 0
                output_tokens = usage.get("output", 0) or 0

                report.total_input_tokens += input_tokens
                report.total_output_tokens += output_tokens
                domain_stats.total_input_tokens += input_tokens
                domain_stats.total_output_tokens += output_tokens

                # Latency
                latency = gen.get("latency")
                if latency is not None:
                    report.total_latency_ms += latency
                    domain_stats.total_latency_ms += latency

                # Model
                model = gen.get("model", "unknown")
                report.models[model] = report.models.get(model, 0) + 1
                domain_stats.models_used[model] = domain_stats.models_used.get(model, 0) + 1

                # Phase and tier
                phase = meta.get("phase", "unknown")
                tier = meta.get("tier", "unknown")
                report.phases[phase] = report.phases.get(phase, 0) + 1
                domain_stats.phases[phase] = domain_stats.phases.get(phase, 0) + 1
                domain_stats.tiers[tier] = domain_stats.tiers.get(tier, 0) + 1

                # Error tracking
                if gen.get("level") == "ERROR" or gen.get("statusMessage"):
                    domain_stats.errors += 1
                    msg = gen.get("statusMessage", "Unknown error")
                    report.errors.append(f"{domain_id}/{phase}: {msg[:100]}")

                # Timestamps
                start_time = gen.get("startTime") or trace.get("timestamp")
                if start_time:
                    timestamps.append(start_time)

        if timestamps:
            timestamps.sort()
            report.time_range_start = timestamps[0]
            report.time_range_end = timestamps[-1]

        return report

    def generate_from_local_traces(self, traces_json_path: Path) -> Optional[EvalSessionReport]:
        """Generate report from a local JSON file of traces (offline mode).

        Useful when Langfuse is unreachable but traces were exported.
        """
        if not traces_json_path.exists():
            logger.error(f"Traces file not found: {traces_json_path}")
            return None

        data = json.loads(traces_json_path.read_text())
        if isinstance(data, dict):
            traces = data.get("data", data.get("traces", []))
        else:
            traces = data

        session_id = "local-export"
        if traces:
            meta = (traces[0].get("metadata") or {})
            session_id = meta.get("session_id", session_id)

        report = EvalSessionReport(session_id=session_id, trace_count=len(traces))

        for trace in traces:
            meta = trace.get("metadata", {}) or {}
            domain_id = meta.get("asopb_domain", "unknown")

            if domain_id not in report.domains:
                report.domains[domain_id] = DomainStats(domain_id=domain_id)

            domain_stats = report.domains[domain_id]

            # Process observations/generations embedded in trace export
            observations = trace.get("observations", [])
            for obs in observations:
                if obs.get("type") != "GENERATION":
                    continue

                report.generation_count += 1
                domain_stats.call_count += 1

                usage = obs.get("usage", {}) or {}
                input_tokens = usage.get("input", 0) or 0
                output_tokens = usage.get("output", 0) or 0
                report.total_input_tokens += input_tokens
                report.total_output_tokens += output_tokens
                domain_stats.total_input_tokens += input_tokens
                domain_stats.total_output_tokens += output_tokens

                latency = obs.get("latency")
                if latency:
                    report.total_latency_ms += latency
                    domain_stats.total_latency_ms += latency

                model = obs.get("model", "unknown")
                report.models[model] = report.models.get(model, 0) + 1
                domain_stats.models_used[model] = domain_stats.models_used.get(model, 0) + 1

        return report


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate ASOPB evaluation reports from Langfuse traces"
    )
    parser.add_argument(
        "--session-id", "-s",
        help="Specific session ID to report on (default: latest)"
    )
    parser.add_argument(
        "--latest", action="store_true",
        help="Use the most recent ASOPB session"
    )
    parser.add_argument(
        "--list-sessions", action="store_true",
        help="List recent ASOPB sessions"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON instead of text"
    )
    parser.add_argument(
        "--output", "-o",
        help="Write report to file instead of stdout"
    )
    parser.add_argument(
        "--local", type=str,
        help="Path to exported traces JSON (offline mode)"
    )

    args = parser.parse_args()

    config = LangfuseConfig(
        enabled=True,
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000"),
    )

    gen = LangfuseReportGenerator(config)

    if args.list_sessions:
        sessions = gen.list_sessions()
        if not sessions:
            print("No ASOPB evaluation sessions found.", file=sys.stderr)
            sys.exit(1)
        for s in sessions:
            print(f"  {s.get('id', 'unknown'):<40} traces={s.get('traces', '?')}")
        sys.exit(0)

    if args.local:
        report = gen.generate_from_local_traces(Path(args.local))
    else:
        session_id = args.session_id
        if args.latest or not session_id:
            session_id = None  # generate_session_report will find latest
        report = gen.generate_session_report(session_id)

    if not report:
        print("Failed to generate report.", file=sys.stderr)
        sys.exit(1)

    output = report.to_json() if args.json else report.to_text()

    if args.output:
        Path(args.output).write_text(output)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
