"""
Bandit Analyzer

Runs bandit for Python security analysis, detecting common security issues
in Python code. Parses JSON output with test IDs, severity, and confidence mapping.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from asopb.analyzers.base import AnalyzerBase
from asopb.models import ScanFinding, ScanResult, Severity


class BanditAnalyzer(AnalyzerBase):
    """Analyzer for Bandit Python security findings.

    Bandit scans Python code for common security issues including hardcoded
    credentials, use of dangerous functions, and other Python-specific vulnerabilities.
    """

    name = "bandit"
    description = "Python security analysis via Bandit"
    tool_command = "bandit"

    async def analyze(self) -> ScanResult:
        """Run bandit on the repository with JSON output.

        Returns:
            ScanResult with parsed findings or error message
        """
        start_time = time.time()

        if not self.is_available():
            return self._make_result(
                success=False,
                error_message=f"Tool '{self.tool_command}' not found",
                duration=time.time() - start_time,
            )

        # Run bandit recursively on repo with JSON output
        cmd = [self.tool_command, "-r", ".", "-f", "json"]
        returncode, stdout, stderr = await self.run_command(cmd)

        duration = time.time() - start_time

        # Bandit exits with various codes; all are potentially valid
        if not stdout:
            return self._make_result(
                success=False,
                error_message=stderr or f"bandit exited with code {returncode}",
                raw_output=stdout,
                duration=duration,
            )

        # Parse JSON output
        data = self._parse_json_output(stdout)
        if data is None:
            return self._make_result(
                success=False,
                error_message="Failed to parse bandit JSON output",
                raw_output=stdout,
                duration=duration,
            )

        # Extract findings
        findings = self._parse_findings(data)

        return self._make_result(
            success=True,
            findings=findings,
            raw_output=stdout,
            duration=duration,
        )

    def _parse_findings(self, data: dict) -> list[ScanFinding]:
        """Parse bandit JSON output into ScanFinding objects.

        Handles test IDs (B101, B301, etc.), severity levels, and confidence.

        Args:
            data: Parsed JSON output from bandit

        Returns:
            List of ScanFinding objects
        """
        findings = []

        # Extract results
        results = data.get("results", [])
        for idx, result in enumerate(results):
            severity = self._map_bandit_severity(result.get("severity", "MEDIUM"))
            confidence = self._confidence_to_float(result.get("confidence", "MEDIUM"))

            finding = ScanFinding(
                finding_id=f"bandit-{idx}",
                category=result.get("test_id", "unknown"),
                severity=severity,
                file_path=result.get("filename"),
                line_number=result.get("line_number"),
                line_range=(
                    result.get("line_number"),
                    result.get("line_number"),
                ),
                message=result.get("issue_text", "Unknown issue"),
                snippet=result.get("test_code", [None])[0] if result.get("test_code") else None,
                confidence=confidence,
                metadata={
                    "test_id": result.get("test_id"),
                    "test_name": result.get("test_name"),
                    "severity": result.get("severity"),
                    "confidence": result.get("confidence"),
                    "issue_cwe": result.get("issue_cwe"),
                },
            )
            findings.append(finding)

        return findings

    @staticmethod
    def _map_bandit_severity(bandit_severity: str) -> Severity:
        """Map Bandit severity levels to ASOPB severity.

        Args:
            bandit_severity: Bandit severity (HIGH, MEDIUM, LOW)

        Returns:
            Mapped Severity enum value
        """
        mapping = {
            "HIGH": Severity.HIGH,
            "MEDIUM": Severity.MEDIUM,
            "LOW": Severity.LOW,
        }
        return mapping.get(bandit_severity.upper(), Severity.INFORMATIONAL)

    @staticmethod
    def _confidence_to_float(confidence: str) -> float:
        """Convert Bandit confidence level to float.

        Args:
            confidence: Bandit confidence (HIGH, MEDIUM, LOW)

        Returns:
            Confidence as float between 0.0 and 1.0
        """
        mapping = {
            "HIGH": 0.9,
            "MEDIUM": 0.7,
            "LOW": 0.5,
        }
        return mapping.get(confidence.upper(), 0.5)
