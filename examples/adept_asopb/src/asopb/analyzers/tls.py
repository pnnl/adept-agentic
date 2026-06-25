"""
TLS/SSL Analyzer

Custom analyzer for scanning codebases for TLS/SSL misconfigurations and
disabled certificate verification. Detects verify=False patterns, CERT_NONE usage,
InsecureRequestWarning suppression, and http:// URLs in production configs.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from asopb.analyzers.base import AnalyzerBase
from asopb.models import ScanFinding, ScanResult, Severity


class TLSAnalyzer(AnalyzerBase):
    """Analyzer for TLS/SSL security issues in code.

    Scans for disabled certificate verification, insecure request patterns,
    and cleartext HTTP in production configurations.
    """

    name = "tls"
    description = "TLS/SSL security analysis (verify=False, CERT_NONE, etc.)"
    tool_command = ""  # No external tool required

    def is_available(self) -> bool:
        """Always available - no external tool dependency."""
        return True

    async def analyze(self) -> ScanResult:
        """Scan codebase for TLS/SSL security issues.

        Returns:
            ScanResult with parsed findings
        """
        start_time = time.time()

        findings = []
        raw_output_lines = []

        # Scan Python files for verify=False
        python_findings, python_output = self._scan_python_files()
        findings.extend(python_findings)
        raw_output_lines.extend(python_output)

        # Scan configuration files for http:// URLs
        config_findings, config_output = self._scan_config_files()
        findings.extend(config_findings)
        raw_output_lines.extend(config_output)

        duration = time.time() - start_time
        raw_output = "\n".join(raw_output_lines) if raw_output_lines else None

        return self._make_result(
            success=True,
            findings=findings,
            raw_output=raw_output,
            duration=duration,
        )

    def _scan_python_files(self) -> tuple[list[ScanFinding], list[str]]:
        """Scan Python files for verify=False and SSL issues.

        Returns:
            Tuple of (findings, raw output lines)
        """
        findings = []
        output = []

        # Find all Python files
        python_files = list(self.repo_path.rglob("*.py"))
        output.append(f"Scanning {len(python_files)} Python files")

        finding_count = 0
        for python_file in python_files:
            try:
                content = python_file.read_text()
                relative_path = python_file.relative_to(self.repo_path)

                lines = content.split("\n")
                for line_num, line in enumerate(lines, 1):
                    # Check for verify=False in requests
                    if re.search(r"verify\s*=\s*False", line, re.IGNORECASE):
                        findings.append(
                            ScanFinding(
                                finding_id=f"tls-{finding_count}",
                                category="verify_false",
                                severity=Severity.HIGH,
                                file_path=str(relative_path),
                                line_number=line_num,
                                message="Certificate verification disabled (verify=False)",
                                snippet=line.strip(),
                                confidence=0.99,
                                metadata={"pattern": "verify=False"},
                            )
                        )
                        finding_count += 1

                    # Check for ssl_verify=False
                    if re.search(r"ssl_verify\s*=\s*False", line, re.IGNORECASE):
                        findings.append(
                            ScanFinding(
                                finding_id=f"tls-{finding_count}",
                                category="ssl_verify_false",
                                severity=Severity.HIGH,
                                file_path=str(relative_path),
                                line_number=line_num,
                                message="SSL verification disabled (ssl_verify=False)",
                                snippet=line.strip(),
                                confidence=0.99,
                                metadata={"pattern": "ssl_verify=False"},
                            )
                        )
                        finding_count += 1

                    # Check for CERT_NONE
                    if re.search(r"CERT_NONE|ssl\.CERT_NONE", line, re.IGNORECASE):
                        findings.append(
                            ScanFinding(
                                finding_id=f"tls-{finding_count}",
                                category="cert_none",
                                severity=Severity.HIGH,
                                file_path=str(relative_path),
                                line_number=line_num,
                                message="CERT_NONE used - certificate verification disabled",
                                snippet=line.strip(),
                                confidence=0.95,
                                metadata={"pattern": "CERT_NONE"},
                            )
                        )
                        finding_count += 1

                    # Check for InsecureRequestWarning suppression
                    if re.search(r"InsecureRequestWarning", line):
                        findings.append(
                            ScanFinding(
                                finding_id=f"tls-{finding_count}",
                                category="insecure_request_warning_suppressed",
                                severity=Severity.MEDIUM,
                                file_path=str(relative_path),
                                line_number=line_num,
                                message="InsecureRequestWarning suppression detected",
                                snippet=line.strip(),
                                confidence=0.95,
                                metadata={"pattern": "InsecureRequestWarning"},
                            )
                        )
                        finding_count += 1

            except (IOError, OSError, UnicodeDecodeError):
                pass

        return findings, output

    def _scan_config_files(self) -> tuple[list[ScanFinding], list[str]]:
        """Scan configuration files for http:// in production.

        Returns:
            Tuple of (findings, raw output lines)
        """
        findings = []
        output = []

        # Find configuration files
        config_patterns = [
            "*.yml",
            "*.yaml",
            "*.json",
            "*.conf",
            "*.config",
            "*.env",
            "*.env.*",
            "*config.py",
            "*settings.py",
        ]

        config_files = set()
        for pattern in config_patterns:
            config_files.update(self.repo_path.rglob(pattern))

        # Also check specific common names
        common_config_files = [
            "config.yaml",
            "settings.yaml",
            "docker-compose.yml",
            "docker-compose.yaml",
            ".env",
            "requirements.txt",
        ]

        for config_file in common_config_files:
            config_files.update(self.repo_path.rglob(config_file))

        output.append(f"Scanning {len(config_files)} configuration files")

        finding_count = 0
        for config_file in config_files:
            try:
                content = config_file.read_text(errors="ignore")
                relative_path = config_file.relative_to(self.repo_path)

                lines = content.split("\n")
                for line_num, line in enumerate(lines, 1):
                    # Skip comments
                    if line.strip().startswith("#"):
                        continue

                    # Look for http:// URLs in what appears to be production config
                    if re.search(
                        r"(url|endpoint|base_url|api_url|server|database_url)\s*[:=]\s*['\"]?http://",
                        line,
                        re.IGNORECASE,
                    ):
                        findings.append(
                            ScanFinding(
                                finding_id=f"tls-{finding_count}",
                                category="http_in_config",
                                severity=Severity.MEDIUM,
                                file_path=str(relative_path),
                                line_number=line_num,
                                message="Cleartext HTTP URL in configuration",
                                snippet=line.strip(),
                                confidence=0.85,
                                metadata={"pattern": "http://"},
                            )
                        )
                        finding_count += 1

                    # Look for self-signed cert patterns
                    if re.search(
                        r"(self.signed|self_signed|self-signed|selfsigned)",
                        line,
                        re.IGNORECASE,
                    ):
                        findings.append(
                            ScanFinding(
                                finding_id=f"tls-{finding_count}",
                                category="self_signed_cert",
                                severity=Severity.MEDIUM,
                                file_path=str(relative_path),
                                line_number=line_num,
                                message="Self-signed certificate reference detected",
                                snippet=line.strip(),
                                confidence=0.8,
                                metadata={"pattern": "self-signed"},
                            )
                        )
                        finding_count += 1

            except (IOError, OSError):
                pass

        return findings, output
