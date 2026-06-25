"""
GitXRay Analyzer

Runs gitxray for repository security analysis, detecting secrets, contributor
anomalies, and suspicious commits. Parses JSON output into ScanFinding objects.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from asopb.analyzers.base import AnalyzerBase
from asopb.models import ScanFinding, ScanResult, Severity


class GitXRayAnalyzer(AnalyzerBase):
    """Analyzer for GitXRay repository security findings.

    GitXRay scans repository history for exposed secrets, suspicious commit
    patterns, contributor anomalies, and other Git-based security issues.
    """

    name = "gitxray"
    description = "Repository security analysis via GitXRay (secrets, anomalies)"
    tool_command = "gitxray"

    async def analyze(self) -> ScanResult:
        """Run gitxray and parse JSON output into findings.

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

        # Run gitxray with JSON output
        cmd = [self.tool_command, "--json", str(self.repo_path)]
        returncode, stdout, stderr = await self.run_command(cmd)

        duration = time.time() - start_time

        if returncode != 0:
            return self._make_result(
                success=False,
                error_message=stderr or f"gitxray exited with code {returncode}",
                raw_output=stdout,
                duration=duration,
            )

        # Parse JSON output
        data = self._parse_json_output(stdout)
        if data is None:
            return self._make_result(
                success=False,
                error_message="Failed to parse gitxray JSON output",
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
        """Parse gitxray JSON output into ScanFinding objects.

        Handles secrets, contributor anomalies, suspicious commits, and other
        repository-level security findings.

        Args:
            data: Parsed JSON output from gitxray

        Returns:
            List of ScanFinding objects
        """
        findings = []

        # Process secrets
        secrets = data.get("secrets", [])
        for secret in secrets:
            findings.append(
                ScanFinding(
                    finding_id=f"gx-secret-{len(findings)}",
                    category="exposed_secret",
                    severity=Severity.CRITICAL,
                    file_path=secret.get("file"),
                    line_number=secret.get("line"),
                    message=f"Potential {secret.get('type', 'unknown')} secret exposed",
                    snippet=secret.get("match"),
                    confidence=0.95,
                    metadata={
                        "secret_type": secret.get("type"),
                        "entropy": secret.get("entropy"),
                    },
                )
            )

        # Process contributor anomalies
        anomalies = data.get("contributor_anomalies", [])
        for anomaly in anomalies:
            findings.append(
                ScanFinding(
                    finding_id=f"gx-anomaly-{len(findings)}",
                    category="contributor_anomaly",
                    severity=Severity.HIGH,
                    message=f"Anomalous contributor activity: {anomaly.get('description', 'unknown')}",
                    confidence=anomaly.get("confidence", 0.7),
                    metadata={
                        "contributor": anomaly.get("author"),
                        "anomaly_type": anomaly.get("anomaly_type"),
                        "commits": anomaly.get("commit_count"),
                    },
                )
            )

        # Process suspicious commits
        suspicious = data.get("suspicious_commits", [])
        for commit in suspicious:
            findings.append(
                ScanFinding(
                    finding_id=f"gx-commit-{len(findings)}",
                    category="suspicious_commit",
                    severity=Severity.MEDIUM,
                    message=f"Suspicious commit pattern: {commit.get('reason', 'unknown')}",
                    confidence=commit.get("confidence", 0.7),
                    metadata={
                        "commit_hash": commit.get("hash"),
                        "author": commit.get("author"),
                        "reason": commit.get("reason"),
                    },
                )
            )

        return findings
