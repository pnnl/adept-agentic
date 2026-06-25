"""
ASOPB Generic JSON Report Ingester

Flexible JSON-to-RedTeamReport transformer supporting custom field mappings.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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


class GenericJSONIngester(ReportIngesterBase):
    """Ingest red-team reports from arbitrary JSON files with configurable schema mapping.

    Supports flexible field mapping to transform third-party JSON formats into
    standardized RedTeamReport objects. Configure field_map to specify how to
    extract scenario data from the JSON structure.

    Example field_map:
        {
            "scenarios": "results",  # JSON array path for scenarios
            "scenario_id": "id",
            "scenario_name": "title",
            "attack_vector": "attack_type",
            "target_domain": "target",
            "target_controls": "controls",
            "outcome": "result",
            "outcome_description": "description",
            "severity": "severity",
            "t3_score_contribution": "score",
            "evidence": "evidence",  # Array of evidence items
            "artifacts": "attachments",
        }
    """

    def __init__(
        self,
        name: str = "generic_json",
        field_map: Optional[dict[str, str]] = None,
    ) -> None:
        """Initialize the JSON ingester.

        Args:
            name: Ingester name for registry
            field_map: Mapping from RedTeamScenario fields to JSON keys.
                      If None, assumes field names match JSON keys directly.
        """
        self._name = name
        self.field_map = field_map or {}

    @property
    def name(self) -> str:
        """Return ingester name."""
        return self._name

    @property
    def description(self) -> str:
        """Return ingester description."""
        return "Generic JSON red-team report ingester with flexible schema mapping"

    def ingest(self, report_path: Path) -> RedTeamReport:
        """Parse and ingest a JSON red-team report.

        Expected JSON structure (or configurable via field_map):
        {
            "report_id": str,
            "source": str,
            "framework": {
                "name": str,
                "version": str | null,
                "git_commit": str | null,
                ...
            },
            "scenarios": [
                {
                    "scenario_id": str,
                    "scenario_name": str,
                    "attack_vector": str,
                    "target_domain": str,
                    "target_controls": [str],
                    "outcome": str,
                    "outcome_description": str,
                    "severity": str,
                    "t3_score_contribution": number,
                    "evidence": [
                        {
                            "tier": str,
                            "source": str,
                            "source_tool": str,
                            "description": str,
                            "confidence": number,
                            ...
                        }
                    ],
                    "artifacts": [str]
                }
            ],
            "timestamp": str | null,
            "metadata": {}
        }

        Args:
            report_path: Path to the JSON file

        Returns:
            Standardized RedTeamReport

        Raises:
            ValueError: If JSON is malformed or required fields missing
        """
        if not report_path.exists():
            raise ValueError(f"Report file not found: {report_path}")

        try:
            with open(report_path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {report_path}: {e}")

        if not isinstance(data, dict):
            raise ValueError(
                f"Report must be a JSON object, got {type(data).__name__}"
            )

        # Extract framework version
        framework_data = data.get("framework", {})
        if not isinstance(framework_data, dict):
            framework_data = {}

        framework = FrameworkVersion(
            name=framework_data.get("name", "unknown"),
            version=framework_data.get("version"),
            git_commit=framework_data.get("git_commit"),
            git_branch=framework_data.get("git_branch"),
            git_tag=framework_data.get("git_tag"),
            snapshot_date=self._parse_datetime(
                framework_data.get("snapshot_date")
            ),
            source_url=framework_data.get("source_url"),
            source_hash=framework_data.get("source_hash"),
        )

        # Parse scenarios
        scenarios_data = self._get_nested(data, self.field_map.get("scenarios", "scenarios"))
        if not isinstance(scenarios_data, list):
            scenarios_data = []

        scenarios = [
            self._parse_scenario(s) for s in scenarios_data
        ]

        # Parse timestamp
        timestamp_str = data.get("timestamp")
        timestamp = self._parse_datetime(timestamp_str)
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Build report
        report = RedTeamReport(
            report_id=data.get("report_id", f"rt-{timestamp.isoformat()}"),
            source=data.get("source", "generic_json"),
            framework_version=framework,
            scenarios=scenarios,
            timestamp=timestamp,
            metadata=data.get("metadata", {}),
        )

        return report

    def _parse_scenario(self, data: dict[str, Any]) -> RedTeamScenario:
        """Parse a single scenario object.

        Args:
            data: Scenario dict

        Returns:
            RedTeamScenario
        """
        # Use field_map to extract fields, with fallbacks to direct keys
        scenario_id = self._get_field(data, "scenario_id")
        scenario_name = self._get_field(data, "scenario_name")
        attack_vector = self._get_field(data, "attack_vector")
        target_domain = self._get_field(data, "target_domain")
        target_controls = self._get_field(data, "target_controls", [])
        outcome = self._get_field(data, "outcome")
        outcome_description = self._get_field(data, "outcome_description")
        severity_str = self._get_field(data, "severity", "high")
        t3_score = self._get_field(data, "t3_score_contribution", 0.0)
        evidence_data = self._get_field(data, "evidence", [])
        artifacts = self._get_field(data, "artifacts", [])

        # Parse evidence items
        evidence = []
        if isinstance(evidence_data, list):
            for ev in evidence_data:
                if isinstance(ev, dict):
                    evidence.append(self._parse_evidence(ev))

        # Parse severity
        try:
            severity = Severity(severity_str.lower())
        except (ValueError, AttributeError):
            severity = Severity.HIGH

        # Ensure target_controls is a list
        if not isinstance(target_controls, list):
            target_controls = [str(target_controls)]
        else:
            target_controls = [str(c) for c in target_controls]

        # Ensure artifacts is a list
        if not isinstance(artifacts, list):
            artifacts = [str(artifacts)]
        else:
            artifacts = [str(a) for a in artifacts]

        return RedTeamScenario(
            scenario_id=str(scenario_id) if scenario_id else "unknown",
            scenario_name=str(scenario_name) if scenario_name else "Unnamed",
            attack_vector=str(attack_vector) if attack_vector else "Unknown",
            target_domain=str(target_domain) if target_domain else "D1",
            target_controls=target_controls,
            outcome=str(outcome) if outcome else "unknown",
            outcome_description=str(outcome_description)
            if outcome_description
            else "",
            severity=severity,
            evidence=evidence,
            artifacts=artifacts,
            t3_score_contribution=float(t3_score) if t3_score else 0.0,
        )

    def _parse_evidence(self, data: dict[str, Any]) -> ControlEvidence:
        """Parse a single evidence item.

        Args:
            data: Evidence dict

        Returns:
            ControlEvidence
        """
        tier_str = data.get("tier", "T1")
        source_str = data.get("source", "red_team")
        source_tool = data.get("source_tool", "red_team:manual")
        description = data.get("description", "")
        confidence = data.get("confidence", 0.8)
        file_path = data.get("file_path")
        raw_data = data.get("raw_data")

        # Parse tier
        try:
            tier = EvidenceTier(tier_str)
        except (ValueError, AttributeError):
            tier = EvidenceTier.T3_ADVERSARIAL

        # Parse source
        try:
            source = EvidenceSource(source_str)
        except (ValueError, AttributeError):
            source = EvidenceSource.RED_TEAM

        # Ensure confidence is in range
        try:
            confidence = float(confidence)
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            confidence = 0.8

        return ControlEvidence(
            tier=tier,
            source=source,
            source_tool=str(source_tool),
            file_path=file_path,
            description=str(description),
            confidence=confidence,
            raw_data=raw_data if isinstance(raw_data, dict) else None,
        )

    def _get_field(
        self,
        data: dict[str, Any],
        field_name: str,
        default: Any = None,
    ) -> Any:
        """Get field value using field_map or direct key lookup.

        Args:
            data: Source dict
            field_name: Field name (in RedTeamScenario)
            default: Default value if not found

        Returns:
            Field value or default
        """
        json_key = self.field_map.get(field_name, field_name)
        return self._get_nested(data, json_key, default)

    @staticmethod
    def _get_nested(
        data: dict[str, Any],
        path: str,
        default: Any = None,
    ) -> Any:
        """Get a value from nested dict using dot notation.

        Args:
            data: Source dict
            path: Dot-separated path (e.g., "results.0.metadata")
            default: Default value if path not found

        Returns:
            Value at path or default
        """
        keys = path.split(".")
        current = data

        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list):
                try:
                    idx = int(key)
                    current = current[idx]
                except (ValueError, IndexError):
                    return default
            else:
                return default

            if current is None:
                return default

        return current

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Parse a datetime from various formats.

        Args:
            value: Value to parse

        Returns:
            datetime or None
        """
        if value is None:
            return None

        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            # Try ISO format
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

            # Try common formats
            for fmt in [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d",
            ]:
                try:
                    return datetime.strptime(value, fmt).replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    pass

        return None
