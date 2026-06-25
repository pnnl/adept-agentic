"""
Langfuse Sink for ASOPB Red-Team Reports.

Writes promptfoo evaluation results into Langfuse as traces, enabling:
- Per-test-case trace visibility (prompt, response, score, latency)
- Dataset run tracking (group eval runs for comparison)
- ASOPB domain/control tagging for filtering
- Cost and token usage aggregation

This bridges the gap between promptfoo's eval engine (which doesn't use LLMClient)
and the Langfuse observability layer. It reads the already-ingested RedTeamReport
and writes each scenario as a Langfuse trace with generation observations.

Usage:
    from asopb.redteam.langfuse_sink import LangfuseSink
    from asopb.redteam.promptfoo_ingester import PromptfooIngester

    ingester = PromptfooIngester(category_map=build_azure_category_map())
    report = ingester.ingest(Path("logs/promptfoo-*/promptfoo_results.json"))

    sink = LangfuseSink()
    sink.write_report(report)

CLI:
    python -m asopb.redteam.langfuse_sink --input logs/promptfoo-*/promptfoo_results.json
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from asopb.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_CREDENTIAL_DIRS = [
    ".env-keycloak-credentials-dir",
]


class LangfuseSink:
    """Writes ASOPB RedTeamReport data into Langfuse as traces."""

    def __init__(
        self,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        host: Optional[str] = None,
        dataset_name: str = "asopb-redteam",
        credential_dirs: Optional[list[str]] = None,
    ):
        self._public_key = public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        self._secret_key = secret_key or os.getenv("LANGFUSE_SECRET_KEY")
        self._host = host or os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000")
        self._dataset_name = dataset_name
        self._credential_dirs = credential_dirs or _DEFAULT_CREDENTIAL_DIRS
        self._client = None

        if not self._public_key or not self._secret_key:
            self._resolve_from_files()

    def _resolve_from_files(self):
        """Resolve credentials from credential directory files."""
        for cred_dir in self._credential_dirs:
            id_path = os.path.join(cred_dir, "LANGFUSE_CLIENT_ID")
            secret_path = os.path.join(cred_dir, "LANGFUSE_CLIENT_SECRET")
            if os.path.isfile(id_path) and os.path.isfile(secret_path):
                with open(id_path) as f:
                    self._public_key = f.read().strip()
                with open(secret_path) as f:
                    self._secret_key = f.read().strip()
                if self._public_key and self._secret_key:
                    logger.info(f"Langfuse credentials loaded from {cred_dir}/")
                    return

    def _get_client(self):
        """Lazily initialize the Langfuse SDK client."""
        if self._client is not None:
            return self._client

        if not self._public_key or not self._secret_key:
            raise RuntimeError(
                "Langfuse credentials not available. "
                "Set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY or provide credential files."
            )

        try:
            from langfuse import Langfuse
        except ImportError:
            raise RuntimeError("langfuse package required: pip install langfuse")

        self._client = Langfuse(
            public_key=self._public_key,
            secret_key=self._secret_key,
            host=self._host,
        )
        return self._client

    def write_report(self, report, flush: bool = True) -> dict:
        """Write a RedTeamReport to Langfuse as traces.

        Each scenario becomes a trace with:
        - name: scenario_id (e.g., "PF-001")
        - metadata: domain, controls, outcome, severity
        - tags: ["redteam", domain_id, outcome]
        - One generation observation per scenario (the LLM call)

        Args:
            report: RedTeamReport object from PromptfooIngester
            flush: Whether to flush after writing (default True)

        Returns:
            Summary dict with counts and session_id
        """
        client = self._get_client()
        session_id = f"asopb-redteam-{report.report_id}"

        stats = {
            "session_id": session_id,
            "traces_written": 0,
            "generations_written": 0,
            "errors": [],
        }

        for scenario in report.scenarios:
            try:
                self._write_scenario(client, session_id, report, scenario)
                stats["traces_written"] += 1
                stats["generations_written"] += 1
            except Exception as e:
                msg = f"Failed to write scenario {scenario.scenario_id}: {e}"
                logger.warning(msg)
                stats["errors"].append(msg)

        if flush:
            client.flush()

        logger.info(
            "Wrote %d traces to Langfuse session %s (%d errors)",
            stats["traces_written"],
            session_id,
            len(stats["errors"]),
        )
        return stats

    def _write_scenario(self, client, session_id: str, report, scenario):
        """Write a single RedTeamScenario as a Langfuse trace + generation."""
        raw_data = {}
        if scenario.evidence:
            raw_data = scenario.evidence[0].raw_data or {}

        prompt_text = raw_data.get("prompt", scenario.scenario_name)
        response_text = raw_data.get("response", scenario.outcome_description)
        score_value = raw_data.get("score", 0.0)

        trace = client.trace(
            name=f"redteam:{scenario.scenario_id}",
            session_id=session_id,
            metadata={
                "asopb_domain": scenario.target_domain,
                "asopb_controls": scenario.target_controls,
                "asopb_phase": "red_team",
                "asopb_tier": "T3",
                "outcome": scenario.outcome,
                "severity": scenario.severity.value if hasattr(scenario.severity, "value") else str(scenario.severity),
                "attack_vector": scenario.attack_vector,
                "report_id": report.report_id,
                "provider": report.metadata.get("provider", "unknown"),
            },
            tags=["redteam", scenario.target_domain, scenario.outcome],
        )

        trace.generation(
            name=f"eval:{scenario.scenario_id}",
            model=report.metadata.get("provider", "unknown"),
            input=[{"role": "user", "content": prompt_text[:2000]}],
            output=response_text[:2000],
            metadata={
                "category": scenario.scenario_id.split("-")[0] if "-" in scenario.scenario_id else "",
                "success": raw_data.get("success", False),
            },
        )

        trace.score(
            name="defense_score",
            value=score_value,
            comment=scenario.outcome_description[:500] if scenario.outcome_description else None,
        )

    def write_dataset_items(self, report, flush: bool = True) -> dict:
        """Write report scenarios as Langfuse dataset items for benchmarking.

        Creates a dataset (if not exists) and adds each test case as an item,
        enabling future comparison runs.

        Args:
            report: RedTeamReport from PromptfooIngester
            flush: Whether to flush after writing

        Returns:
            Summary dict with dataset_name and item count
        """
        client = self._get_client()

        try:
            dataset = client.get_dataset(self._dataset_name)
        except Exception:
            dataset = client.create_dataset(
                name=self._dataset_name,
                description="ASOPB red-team evaluation dataset (promptfoo scenarios)",
                metadata={"source": "promptfoo", "report_id": report.report_id},
            )

        stats = {"dataset_name": self._dataset_name, "items_written": 0, "errors": []}

        for scenario in report.scenarios:
            raw_data = {}
            if scenario.evidence:
                raw_data = scenario.evidence[0].raw_data or {}

            try:
                client.create_dataset_item(
                    dataset_name=self._dataset_name,
                    input={"prompt": raw_data.get("prompt", scenario.scenario_name)},
                    expected_output=scenario.outcome,
                    metadata={
                        "scenario_id": scenario.scenario_id,
                        "domain": scenario.target_domain,
                        "controls": scenario.target_controls,
                        "attack_vector": scenario.attack_vector,
                        "severity": scenario.severity.value if hasattr(scenario.severity, "value") else str(scenario.severity),
                    },
                )
                stats["items_written"] += 1
            except Exception as e:
                stats["errors"].append(f"{scenario.scenario_id}: {e}")

        if flush:
            client.flush()

        logger.info(
            "Wrote %d dataset items to '%s'",
            stats["items_written"],
            self._dataset_name,
        )
        return stats


def main():
    """CLI entry point for promptfoo -> Langfuse ingestion."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest promptfoo eval results into Langfuse"
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Path to promptfoo_results.json"
    )
    parser.add_argument(
        "--dataset", action="store_true",
        help="Also write as dataset items for benchmarking"
    )
    parser.add_argument(
        "--dataset-name", default="asopb-redteam",
        help="Langfuse dataset name (default: asopb-redteam)"
    )
    parser.add_argument(
        "--config", choices=["azure", "adept", "bedrock"],
        default="azure",
        help="Which category map to use (default: azure)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse and validate without writing to Langfuse"
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=__import__("sys").stderr)
        __import__("sys").exit(1)

    from asopb.redteam.promptfoo_ingester import (
        PromptfooIngester,
        build_adept_category_map,
        build_azure_category_map,
    )

    if args.config == "azure":
        category_map = build_azure_category_map()
    elif args.config == "adept":
        category_map = build_adept_category_map()
    else:
        category_map = {}

    ingester = PromptfooIngester(category_map=category_map)
    report = ingester.ingest(input_path)

    print(f"Ingested: {len(report.scenarios)} scenarios")
    print(f"  Passed: {report.metadata.get('passed', 0)}")
    print(f"  Failed: {report.metadata.get('failed', 0)}")
    print(f"  Provider: {report.metadata.get('provider', 'unknown')}")

    if args.dry_run:
        print("\n[DRY RUN] Would write to Langfuse but --dry-run specified.")
        return

    sink = LangfuseSink(dataset_name=args.dataset_name)
    stats = sink.write_report(report)
    print(f"\nLangfuse traces: {stats['traces_written']} written")
    print(f"Session: {stats['session_id']}")

    if args.dataset:
        ds_stats = sink.write_dataset_items(report)
        print(f"Dataset items: {ds_stats['items_written']} written to '{ds_stats['dataset_name']}'")

    if stats["errors"]:
        print(f"\nWarnings: {len(stats['errors'])} errors during write")
        for err in stats["errors"][:5]:
            print(f"  - {err}")


if __name__ == "__main__":
    main()
