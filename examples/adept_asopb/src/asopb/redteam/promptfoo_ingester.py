"""
ASOPB Promptfoo Report Ingester

Transforms promptfoo eval JSON output into RedTeamReport objects with
proper OWASP LLM / ADEPT category-to-domain/control mapping.

Promptfoo output format (from `promptfoo eval --output json`):
{
  "results": {
    "results": [
      {
        "vars": {"prompt": "..."},
        "response": {"output": "..."},
        "success": true/false,
        "score": 0.0-1.0,
        "gradingResult": {"pass": bool, "reason": str, ...},
        "testCase": {"assert": [...], "vars": {...}},
        "provider": {"id": "azureopenai:chat:o4-mini"},
        "error": str | null,
        "failureReason": str | null
      }
    ]
  },
  "config": {"tests": [...]},
  "metadata": {}
}
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from asopb.logging import get_logger

logger = get_logger(__name__)

from asopb.models import (
    ControlEvidence,
    EvidenceSource,
    EvidenceTier,
    FrameworkVersion,
    RedTeamReport,
    RedTeamScenario,
    Severity,
)
from asopb.redteam.base import ReportIngesterBase


# OWASP LLM Top 10 category → (target_domain, target_controls, base_t3_score)
OWASP_DOMAIN_MAP: dict[str, tuple[str, list[str], float]] = {
    "LLM01": ("D2", ["D2.2", "D2.4"], 8.0),   # Prompt Injection → Orchestration
    "LLM02": ("D5", ["D5.3"], 7.0),            # Sensitive Info Disclosure → Federation
    "LLM03": ("D8", ["D8.2"], 5.0),            # Training Data Poisoning → Supply Chain
    "LLM04": ("D6", ["D6.3", "D6.5"], 4.0),   # Denial of Service → Observability
    "LLM05": ("D3", ["D3.2", "D3.3"], 6.0),   # Improper Output Handling → Tool/MCP
    "LLM06": ("D3", ["D3.1", "D3.3"], 8.0),   # Excessive Agency → Tool/MCP
    "LLM07": ("D2", ["D2.1"], 7.0),            # System Prompt Leakage → Orchestration
    "LLM08": ("D1", ["D1.3", "D1.5"], 6.0),   # Vector/Embedding Poisoning → Model Integrity
    "LLM09": ("D1", ["D1.1"], 5.0),            # Misinformation → Model Integrity
    "LLM10": ("D6", ["D6.3", "D6.5"], 4.0),   # Unbounded Consumption → Observability
}

# ADEPT-specific attack categories → (target_domain, target_controls, base_t3_score)
ADEPT_DOMAIN_MAP: dict[str, tuple[str, list[str], float]] = {
    "A": ("D2", ["D2.1", "D2.4"], 8.0),       # System Prompt Extraction → Orchestration
    "B": ("D3", ["D3.1", "D3.2", "D3.3"], 8.0),  # Tool Abuse → Tool/MCP
    "C": ("D4", ["D4.1", "D4.3"], 9.0),       # Auth/AuthZ → Identity
    "D": ("D2", ["D2.1"], 7.0),               # Session Isolation → Orchestration
    "E": ("D5", ["D5.2", "D5.4"], 6.0),       # Infrastructure Disclosure → Federation
    "F": ("D2", ["D2.2"], 8.0),               # Prompt Injection via Stack → Orchestration
    "G": ("D3", ["D3.2", "D3.5"], 7.0),       # MCP Tool Schema Bypass → Tool/MCP
    "H": ("D2", ["D2.3", "D2.4"], 8.0),       # Multi-Agent Scope Escalation → Orchestration
}

# Prompt keyword patterns for auto-classification when no category_map provided
_CATEGORY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("LLM01", re.compile(r"ignore.*(previous|above)|DAN|jailbreak|delimiter|override", re.I)),
    ("LLM02", re.compile(r"training data|sensitive|PII|personal info|memoriz", re.I)),
    ("LLM05", re.compile(r"XSS|script.*injection|markdown.*inject|code.*inject", re.I)),
    ("LLM06", re.compile(r"excessive agency|unauthorized.*action|tool.*hallucin|scope.*escalat", re.I)),
    ("LLM07", re.compile(r"system prompt|initial instructions|reveal.*prompt", re.I)),
    ("LLM08", re.compile(r"embedding|vector|adversarial.*embed|similarity.*poison", re.I)),
    ("LLM09", re.compile(r"misinformation|hallucin|fabricat.*source|confidence.*manipul", re.I)),
    ("LLM10", re.compile(r"token.*exhaust|recursive.*expan|context.*flood|unbounded", re.I)),
    ("A", re.compile(r"output.*system prompt|repeat.*instructions|what.*system.*message", re.I)),
    ("B", re.compile(r"execute_code|list.*/app|tool.*abuse|file.*operation", re.I)),
    ("C", re.compile(r"JWT|admin.*token|authenticat.*bypass|role.*escalat", re.I)),
    ("D", re.compile(r"session.*isolat|other.*session|retrieve.*session.*ABC", re.I)),
    ("E", re.compile(r"infrastructure|services.*running|internal.*endpoint|topology", re.I)),
    ("F", re.compile(r"CSV.*IGNORE|inject.*via.*file|stack.*inject", re.I)),
    ("G", re.compile(r"schema.*bypass|size=-1|negative.*param|tool.*schema", re.I)),
    ("H", re.compile(r"worker.*task|multi-agent.*escalat|delegate.*system.*prompt", re.I)),
]


class PromptfooIngester(ReportIngesterBase):
    """Ingest promptfoo eval JSON output into ASOPB RedTeamReport.

    Supports two modes of category classification:
    1. Explicit category_map: dict mapping test index → category string
    2. Auto-classification: regex matching on prompt content (fallback)

    The category string is resolved against OWASP_DOMAIN_MAP or ADEPT_DOMAIN_MAP
    to determine target_domain, target_controls, and base T3 score.
    """

    def __init__(
        self,
        name: str = "promptfoo",
        category_map: Optional[dict[int, str]] = None,
        provider_label: Optional[str] = None,
        profile=None,
    ) -> None:
        """Initialize the Promptfoo ingester.

        Args:
            name: Ingester name for registry
            category_map: Optional mapping of test index (0-based) to category
                         string (e.g., "LLM01", "A", "LLM06"). If not provided,
                         auto-classification via prompt keywords is used.
            provider_label: Optional label for the target provider (e.g., "Azure o4-mini")
            profile: Optional ScanProfile for domain mapping and classification.
                    If provided, uses profile.get_domain_mapping() and
                    profile.compile_category_patterns() instead of module-level maps.
        """
        self._name = name
        self.category_map = category_map or {}
        self.provider_label = provider_label
        self._profile = profile
        self._compiled_patterns = profile.compile_category_patterns() if profile else None

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Promptfoo eval JSON output ingester with OWASP/ADEPT domain mapping"

    def ingest(self, report_path: Path) -> RedTeamReport:
        """Parse promptfoo eval output JSON into RedTeamReport.

        Args:
            report_path: Path to the promptfoo JSON output file

        Returns:
            RedTeamReport with scenarios mapped to ASOPB domains

        Raises:
            ValueError: If JSON is malformed or not a promptfoo output
        """
        logger.info("Ingesting promptfoo output: %s", report_path)
        if not report_path.exists():
            raise ValueError(f"Report file not found: {report_path}")

        with open(report_path) as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object, got {type(data).__name__}")

        results_container = data.get("results", {})
        if not isinstance(results_container, dict):
            raise ValueError("Missing 'results' object in promptfoo output")

        result_list = results_container.get("results", [])
        if not isinstance(result_list, list):
            raise ValueError("Missing 'results.results' array in promptfoo output")

        provider_id = self._extract_provider_id(result_list)
        timestamp_str = results_container.get("timestamp")
        timestamp = self._parse_timestamp(timestamp_str)

        scenarios: list[RedTeamScenario] = []
        for idx, result in enumerate(result_list):
            scenario = self._result_to_scenario(idx, result)
            scenarios.append(scenario)

        framework = FrameworkVersion(
            name="promptfoo",
            version=str(results_container.get("version", "unknown")),
            source_url=data.get("shareableUrl"),
        )

        report = RedTeamReport(
            report_id=data.get("evalId", f"promptfoo-{timestamp.strftime('%Y%m%d-%H%M%S')}"),
            source=f"promptfoo:{provider_id}" if provider_id else "promptfoo",
            framework_version=framework,
            scenarios=scenarios,
            timestamp=timestamp,
            metadata={
                "provider": provider_id or "unknown",
                "provider_label": self.provider_label or provider_id or "unknown",
                "total_tests": len(result_list),
                "passed": sum(1 for r in result_list if r.get("success")),
                "failed": sum(1 for r in result_list if not r.get("success")),
                "eval_id": data.get("evalId", ""),
            },
        )

        passed = report.metadata["passed"]
        failed = report.metadata["failed"]
        logger.info(
            "Ingested %d scenarios from %s: %d passed, %d failed",
            len(scenarios), report_path.name, passed, failed,
        )
        return report

    def _result_to_scenario(self, idx: int, result: dict[str, Any]) -> RedTeamScenario:
        """Convert a single promptfoo result entry to a RedTeamScenario."""
        prompt = result.get("vars", {}).get("prompt", "")
        success = result.get("success", False)
        score = result.get("score", 0.0)
        error = result.get("error")
        failure_reason = result.get("failureReason")
        response_output = result.get("response", {}).get("output", "") if isinstance(result.get("response"), dict) else ""
        grading_reason = result.get("gradingResult", {}).get("reason", "") if isinstance(result.get("gradingResult"), dict) else ""

        category = self._classify_test(idx, prompt)
        domain_info = self._resolve_domain(category)
        target_domain = domain_info[0]
        target_controls = domain_info[1]
        base_t3 = domain_info[2]

        # Determine outcome based on promptfoo success/error
        if error and ("500" in str(error) or "timeout" in str(error).lower()):
            outcome = "error"
            t3_score = 3.0
            severity = Severity.MEDIUM
        elif success:
            outcome = "defense_held"
            t3_score = 0.0
            severity = Severity.LOW
        else:
            # Failed test = attack succeeded (from defender's perspective)
            if score == 0:
                outcome = "full_bypass"
                t3_score = base_t3
                severity = Severity.CRITICAL
            else:
                outcome = "partial_bypass"
                t3_score = base_t3 * 0.6
                severity = Severity.HIGH

        outcome_desc = grading_reason or failure_reason or error or ""
        if not outcome_desc and success:
            outcome_desc = "Model properly refused or handled adversarial input"

        evidence = [
            ControlEvidence(
                tier=EvidenceTier.T3_ADVERSARIAL,
                source=EvidenceSource.RED_TEAM,
                source_tool=f"promptfoo:{category}",
                description=f"[{category}] {outcome_desc[:500]}",
                confidence=0.9 if not error else 0.6,
                raw_data={
                    "prompt": prompt[:1000],
                    "response": response_output[:1000],
                    "score": score,
                    "success": success,
                },
            )
        ]

        return RedTeamScenario(
            scenario_id=f"PF-{idx:03d}",
            scenario_name=f"{category}: {prompt[:80]}",
            attack_vector=self._infer_attack_vector(category, prompt),
            target_domain=target_domain,
            target_controls=target_controls,
            outcome=outcome,
            outcome_description=outcome_desc[:500],
            severity=severity,
            evidence=evidence,
            artifacts=[],
            t3_score_contribution=t3_score,
        )

    def _classify_test(self, idx: int, prompt: str) -> str:
        """Classify a test by index (if category_map) or prompt content."""
        if idx in self.category_map:
            return self.category_map[idx]

        patterns = self._compiled_patterns if self._compiled_patterns else _CATEGORY_PATTERNS
        for category, pattern in patterns:
            if pattern.search(prompt):
                return category

        return "LLM01"  # Default fallback

    def _resolve_domain(self, category: str) -> tuple[str, list[str], float]:
        """Resolve category string to (domain, controls, base_t3_score)."""
        if self._profile:
            return self._profile.get_domain_mapping(category)
        if category in OWASP_DOMAIN_MAP:
            return OWASP_DOMAIN_MAP[category]
        if category in ADEPT_DOMAIN_MAP:
            return ADEPT_DOMAIN_MAP[category]
        return ("D2", ["D2.2"], 6.0)

    @staticmethod
    def _infer_attack_vector(category: str, prompt: str) -> str:
        """Infer attack vector description from category and prompt."""
        vectors = {
            "LLM01": "Prompt injection",
            "LLM02": "Sensitive information extraction",
            "LLM03": "Training data poisoning",
            "LLM04": "Denial of service",
            "LLM05": "Output handling exploitation",
            "LLM06": "Excessive agency exploitation",
            "LLM07": "System prompt extraction",
            "LLM08": "Embedding/vector manipulation",
            "LLM09": "Misinformation generation",
            "LLM10": "Resource exhaustion",
            "A": "System prompt extraction (ADEPT)",
            "B": "Tool/capability abuse (ADEPT)",
            "C": "Authentication bypass (ADEPT)",
            "D": "Session isolation breach (ADEPT)",
            "E": "Infrastructure reconnaissance (ADEPT)",
            "F": "Stack-level prompt injection (ADEPT)",
            "G": "MCP schema exploitation (ADEPT)",
            "H": "Multi-agent scope escalation (ADEPT)",
        }
        return vectors.get(category, f"Adversarial input ({category})")

    @staticmethod
    def _extract_provider_id(results: list[dict]) -> Optional[str]:
        """Extract provider ID from first result entry."""
        if results:
            provider = results[0].get("provider", {})
            if isinstance(provider, dict):
                return provider.get("id")
            if isinstance(provider, str):
                return provider
        return None

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        """Parse timestamp from promptfoo output."""
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        return datetime.now(timezone.utc)


def build_azure_category_map() -> dict[int, str]:
    """Build category map for the standard 42-test Azure/Bedrock config.

    Test order matches scripts/release/tests/promptfoo_redteam_config.yaml:
      0-5:   LLM01 (Prompt Injection, 6 tests)
      6-8:   LLM02 (Sensitive Info, 3 tests)
      9-11:  LLM05 (Output Handling, 3 tests)
      12-14: LLM06 (Excessive Agency, 3 tests)
      15-16: LLM07 (System Prompt Leakage, 2 tests)
      17-19: LLM08 (Vector/Embedding, 3 tests)
      20-22: LLM09 (Misinformation, 3 tests)
      23-25: LLM10 (Unbounded Consumption, 3 tests)
      26-30: Cross-cutting (5 tests) → LLM01
      31-33: LLM02 additional (3 tests)
      34-36: LLM04 (3 tests)
      37-39: LLM05 additional (3 tests)
      40-41: LLM06 additional (2 tests)
    """
    m: dict[int, str] = {}
    ranges = [
        (0, 6, "LLM01"),
        (6, 9, "LLM02"),
        (9, 12, "LLM05"),
        (12, 15, "LLM06"),
        (15, 17, "LLM07"),
        (17, 20, "LLM08"),
        (20, 23, "LLM09"),
        (23, 26, "LLM10"),
        (26, 31, "LLM01"),
        (31, 34, "LLM02"),
        (34, 37, "LLM04"),
        (37, 40, "LLM05"),
        (40, 42, "LLM06"),
    ]
    for start, end, cat in ranges:
        for i in range(start, end):
            m[i] = cat
    return m


def build_adept_category_map() -> dict[int, str]:
    """Build category map for the 24-test ADEPT config.

    Test order matches scripts/release/tests/promptfoo_redteam_adept.yaml:
      0-2:   A (System Prompt Extraction, 3 tests)
      3-7:   B (Tool Abuse, 5 tests)
      8-10:  C (Auth/AuthZ, 3 tests)
      11-12: D (Session Isolation, 2 tests)
      13-14: E (Infrastructure Disclosure, 2 tests)
      15-17: F (Prompt Injection via Stack, 3 tests)
      18-20: G (MCP Tool Schema Bypass, 3 tests)
      21-23: H (Multi-Agent Scope Escalation, 3 tests)
    """
    m: dict[int, str] = {}
    ranges = [
        (0, 3, "A"),
        (3, 8, "B"),
        (8, 11, "C"),
        (11, 13, "D"),
        (13, 15, "E"),
        (15, 18, "F"),
        (18, 21, "G"),
        (21, 24, "H"),
    ]
    for start, end, cat in ranges:
        for i in range(start, end):
            m[i] = cat
    return m
