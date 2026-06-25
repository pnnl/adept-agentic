"""
Pip-Audit Analyzer

Runs pip-audit for Python dependency vulnerability scanning, detecting known
vulnerabilities in installed packages. Parses JSON output with CVE IDs and
fix recommendations.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from asopb.analyzers.base import AnalyzerBase
from asopb.models import ScanFinding, ScanResult, Severity


class PipAuditAnalyzer(AnalyzerBase):
    """Analyzer for pip-audit dependency vulnerability findings.

    pip-audit scans Python project dependencies for known CVEs and security
    vulnerabilities, providing fix recommendations.
    """

    name = "pip_audit"
    description = "Python dependency vulnerability scanning via pip-audit"
    tool_command = "pip-audit"

    async def analyze(self) -> ScanResult:
        """Run pip-audit with JSON output.

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

        # Run pip-audit with JSON format
        cmd = [self.tool_command, "--format", "json"]
        returncode, stdout, stderr = await self.run_command(cmd)

        duration = time.time() - start_time

        # pip-audit can exit with non-zero when vulns found; all are valid
        if not stdout:
            return self._make_result(
                success=False,
                error_message=stderr or f"pip-audit exited with code {returncode}",
                raw_output=stdout,
                duration=duration,
            )

        # Parse JSON output
        data = self._parse_json_output(stdout)
        if data is None:
            return self._make_result(
                success=False,
                error_message="Failed to parse pip-audit JSON output",
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
        """Parse pip-audit JSON output into ScanFinding objects.

        Handles CVE IDs, affected versions, and fix recommendations.

        Args:
            data: Parsed JSON output from pip-audit

        Returns:
            List of ScanFinding objects
        """
        findings = []

        # Extract vulnerabilities
        vulnerabilities = data.get("vulnerabilities", [])
        for idx, vuln in enumerate(vulnerabilities):
            # Determine severity from CVE or default to high for known vulns
            severity = self._infer_severity(vuln)

            # Build fix information
            fix_versions = vuln.get("fix_versions", [])
            fix_info = ", ".join(fix_versions) if fix_versions else "No fix available"

            finding = ScanFinding(
                finding_id=f"pip-audit-{idx}",
                category="dependency_vulnerability",
                severity=severity,
                message=(
                    f"Vulnerable package {vuln.get('name')} "
                    f"({vuln.get('installed_version')}) "
                    f"- {vuln.get('description', 'Unknown vulnerability')}"
                ),
                confidence=0.95,
                metadata={
                    "package_name": vuln.get("name"),
                    "installed_version": vuln.get("installed_version"),
                    "vulnerable_specs": vuln.get("vulnerable_specs", []),
                    "cve_ids": vuln.get("cve_ids", []),
                    "fix_versions": fix_versions,
                    "published_date": vuln.get("published_date"),
                    "advisory_url": vuln.get("advisory_url"),
                },
            )
            findings.append(finding)

        return findings

    @staticmethod
    def _infer_severity(vuln: dict) -> Severity:
        """Infer severity from CVE or use default.

        Args:
            vuln: Vulnerability entry from pip-audit

        Returns:
            Mapped Severity enum value
        """
        # Check for CVE with known severity
        cve_ids = vuln.get("cve_ids", [])
        if cve_ids:
            # Use high severity for any CVE by default
            # In a real scenario, you'd look up CVSS scores
            return Severity.HIGH

        # Default to high for any unspecified vulnerability
        return Severity.HIGH
