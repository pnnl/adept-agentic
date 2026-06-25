"""
Semgrep Analyzer

Runs semgrep for static application security testing (SAST), detecting code
patterns and security issues. Parses JSON output with rule IDs, severity mapping,
and CWE references.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from asopb.analyzers.base import AnalyzerBase
from asopb.models import ScanFinding, ScanResult, Severity


class SemgrepAnalyzer(AnalyzerBase):
    """Analyzer for Semgrep SAST findings.

    Semgrep performs pattern-based code scanning to detect security issues,
    code quality problems, and compliance violations across multiple languages.
    """

    name = "semgrep"
    description = "Static application security testing via Semgrep"
    tool_command = "semgrep"

    async def analyze(self) -> ScanResult:
        """Run semgrep with auto config and parse JSON output.

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

        # Run semgrep with auto config and JSON output
        cmd = [
            self.tool_command,
            "--config",
            "auto",
            "--json",
            str(self.repo_path),
        ]
        returncode, stdout, stderr = await self.run_command(cmd)

        duration = time.time() - start_time

        # Semgrep exits with 0 (no findings) or 1 (findings found), both valid
        if returncode not in (0, 1):
            return self._make_result(
                success=False,
                error_message=stderr or f"semgrep exited with code {returncode}",
                raw_output=stdout,
                duration=duration,
            )

        # Parse JSON output
        data = self._parse_json_output(stdout)
        if data is None:
            return self._make_result(
                success=False,
                error_message="Failed to parse semgrep JSON output",
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
        """Parse semgrep JSON output into ScanFinding objects.

        Handles rule matches with severity mapping and CWE references.

        Args:
            data: Parsed JSON output from semgrep

        Returns:
            List of ScanFinding objects
        """
        findings = []

        # Extract results (matches and errors)
        results = data.get("results", [])
        for idx, result in enumerate(results):
            severity = self._map_semgrep_severity(result.get("severity", "INFO"))
            message = result.get("extra", {}).get("message", result.get("check_id", "Unknown issue"))

            # Extract CWE if available
            cwe_id = None
            metadata = result.get("extra", {})
            if "cwe" in metadata:
                cwe_id = metadata["cwe"]

            finding = ScanFinding(
                finding_id=f"semgrep-{idx}",
                category=result.get("check_id", "unknown"),
                severity=severity,
                file_path=result.get("path"),
                line_number=result.get("start", {}).get("line"),
                line_range=(
                    result.get("start", {}).get("line"),
                    result.get("end", {}).get("line"),
                ),
                message=message,
                snippet=result.get("extra", {}).get("snippet"),
                confidence=0.95,
                metadata={
                    "rule_id": result.get("check_id"),
                    "rule_url": metadata.get("metadata", {}).get("references", [None])[0],
                    "cwe": cwe_id,
                    "languages": metadata.get("metadata", {}).get("languages", []),
                    "severity": result.get("severity"),
                },
            )
            findings.append(finding)

        return findings

    @staticmethod
    def _map_semgrep_severity(semgrep_severity: str) -> Severity:
        """Map semgrep severity levels to ASOPB severity.

        Args:
            semgrep_severity: Semgrep severity (ERROR, WARNING, INFO)

        Returns:
            Mapped Severity enum value
        """
        mapping = {
            "ERROR": Severity.HIGH,
            "WARNING": Severity.MEDIUM,
            "INFO": Severity.LOW,
        }
        return mapping.get(semgrep_severity.upper(), Severity.INFORMATIONAL)
