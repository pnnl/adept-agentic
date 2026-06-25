"""
IOC (Indicators of Compromise) Scanner Analyzer

Pure-Python analyzer that checks for known supply chain compromise indicators.
Unlike other analyzers, this does NOT require an external tool — it runs
filesystem and pattern checks directly.

Designed after the LiteLLM March 2026 compromise (ADEPT-SEC-2026-001).

Checks for:
  - Known compromised package versions (maintained blocklist)
  - .pth file injection in site-packages
  - Suspicious systemd persistence services
  - Known C2 domain references in code
  - Kubernetes privileged pod patterns
  - Exfiltration artifact paths
  - Env-var secret exposure patterns
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Optional

from asopb.analyzers.base import AnalyzerBase
from asopb.models import ScanFinding, ScanResult, Severity


class IOCAnalyzer(AnalyzerBase):
    """Scans for indicators of compromise from known supply chain attacks.

    This analyzer runs pure Python — no external tool required.
    It scans the repository and deployment configuration for IOC patterns
    drawn from real-world supply chain compromises.
    """

    name = "ioc_scanner"
    description = "Indicator of Compromise (IOC) scanner for supply chain attacks"
    tool_command = ""  # Pure Python — no external tool

    # ------------------------------------------------------------------
    # Known compromised package versions (extensible blocklist)
    # ------------------------------------------------------------------
    KNOWN_COMPROMISED: dict[str, list[str]] = {
        "litellm": ["1.82.7", "1.82.8"],
        # Extensible via config or user-provided YAML
    }

    # ------------------------------------------------------------------
    # Filesystem IOCs
    # ------------------------------------------------------------------
    FILESYSTEM_IOCS: list[dict[str, Any]] = [
        {
            "path_pattern": r"\.config/sysmon/sysmon\.(py|service)",
            "description": "LiteLLM compromise: systemd persistence backdoor",
            "reference": "ADEPT-SEC-2026-001",
            "severity": Severity.CRITICAL,
        },
        {
            "path_pattern": r"litellm_init\.pth",
            "description": "LiteLLM compromise: .pth import-time injection",
            "reference": "ADEPT-SEC-2026-001",
            "severity": Severity.CRITICAL,
        },
        {
            "path_pattern": r"/tmp/tpcp\.tar\.gz",
            "description": "LiteLLM compromise: encrypted exfiltration archive",
            "reference": "ADEPT-SEC-2026-001",
            "severity": Severity.CRITICAL,
        },
        {
            "path_pattern": r"/tmp/pglog",
            "description": "LiteLLM compromise: C2 downloaded payload",
            "reference": "ADEPT-SEC-2026-001",
            "severity": Severity.CRITICAL,
        },
        {
            "path_pattern": r"/tmp/\.pg_state",
            "description": "LiteLLM compromise: state tracking file",
            "reference": "ADEPT-SEC-2026-001",
            "severity": Severity.HIGH,
        },
        {
            "path_pattern": r"/tmp/session\.key",
            "description": "LiteLLM compromise: AES session key artifact",
            "reference": "ADEPT-SEC-2026-001",
            "severity": Severity.HIGH,
        },
    ]

    # ------------------------------------------------------------------
    # Network IOCs (domain/IP patterns)
    # ------------------------------------------------------------------
    NETWORK_IOCS: list[dict[str, Any]] = [
        {
            "pattern": r"models\.litellm\[?\.\]?cloud",
            "description": "LiteLLM compromise: exfiltration endpoint",
            "severity": Severity.CRITICAL,
        },
        {
            "pattern": r"46\.151\.182\.203",
            "description": "LiteLLM compromise: C2 server IP (exfiltration)",
            "severity": Severity.CRITICAL,
        },
        {
            "pattern": r"checkmarx\[?\.\]?zone",
            "description": "LiteLLM compromise: persistence C2 domain",
            "severity": Severity.CRITICAL,
        },
        {
            "pattern": r"83\.142\.209\.11",
            "description": "LiteLLM compromise: C2 server IP (persistence)",
            "severity": Severity.CRITICAL,
        },
    ]

    # ------------------------------------------------------------------
    # Kubernetes IOCs
    # ------------------------------------------------------------------
    K8S_IOCS: list[dict[str, Any]] = [
        {
            "pattern": r"node-setup-\w+",
            "context": r"kube-system",
            "description": "LiteLLM compromise: lateral movement pod naming pattern",
            "severity": Severity.HIGH,
        },
    ]

    # ------------------------------------------------------------------
    # Suspicious patterns in code (not just IOCs — weak signals)
    # ------------------------------------------------------------------
    SUSPICIOUS_PATTERNS: list[dict[str, Any]] = [
        {
            "pattern": r"base64\.b64decode\(.*\).*exec\(",
            "description": "Base64-decoded exec() — common in multi-stage payloads",
            "severity": Severity.HIGH,
            "confidence": 0.6,
        },
        {
            "pattern": r"subprocess\.Popen\(.*base64",
            "description": "Subprocess launch with base64 content — potential payload",
            "severity": Severity.HIGH,
            "confidence": 0.5,
        },
        {
            "pattern": r"systemd.*service.*Restart=always",
            "description": "systemd service with auto-restart — potential persistence",
            "severity": Severity.MEDIUM,
            "confidence": 0.4,
        },
        {
            "pattern": r"kubectl\s+get\s+secrets?\s+--all-namespaces",
            "description": "Cluster-wide secret enumeration — potential lateral movement",
            "severity": Severity.HIGH,
            "confidence": 0.7,
        },
        {
            "pattern": r"hostPID.*hostNetwork.*mountPath:\s*/",
            "description": "Privileged pod with host filesystem mount — container escape",
            "severity": Severity.CRITICAL,
            "confidence": 0.8,
        },
    ]

    # ------------------------------------------------------------------
    # Env-var secret exposure
    # ------------------------------------------------------------------
    ENV_SECRET_PATTERNS: list[str] = [
        r"os\.environ\[.*(SECRET|TOKEN|KEY|PASSWORD|CREDENTIAL|API_KEY)",
        r"os\.getenv\(.*(SECRET|TOKEN|KEY|PASSWORD|CREDENTIAL|API_KEY)",
        r"SECRET_KEY\s*=\s*os\.",
        r"\.env\b.*\b(SECRET|TOKEN|KEY|PASSWORD)\b",
    ]

    def is_available(self) -> bool:
        """IOC scanner is always available (pure Python)."""
        return True

    async def analyze(self) -> ScanResult:
        """Run the full IOC analysis suite."""
        start = time.time()
        findings: list[ScanFinding] = []

        # 1. Check for known compromised package versions in dependency files
        self._check_compromised_versions(findings)

        # 2. Check for filesystem IOC patterns in code/config
        self._check_filesystem_iocs(findings)

        # 3. Check for network IOC patterns (C2 domains/IPs) in code
        self._check_network_iocs(findings)

        # 4. Check for K8s IOC patterns
        self._check_k8s_iocs(findings)

        # 5. Check for suspicious code patterns
        self._check_suspicious_patterns(findings)

        # 6. Check for env-var secret exposure
        self._check_env_secrets(findings)

        # 7. Check for .pth files in repo
        self._check_pth_files(findings)

        duration = time.time() - start

        return self._make_result(
            success=True,
            findings=findings,
            duration=duration,
            summary_stats={
                "compromised_versions_found": sum(
                    1 for f in findings if f.category == "compromised_version"
                ),
                "filesystem_iocs": sum(
                    1 for f in findings if f.category == "filesystem_ioc"
                ),
                "network_iocs": sum(
                    1 for f in findings if f.category == "network_ioc"
                ),
                "suspicious_patterns": sum(
                    1 for f in findings if f.category == "suspicious_pattern"
                ),
                "env_secret_exposure": sum(
                    1 for f in findings if f.category == "env_secret_exposure"
                ),
            },
        )

    # ==================================================================
    # Check methods
    # ==================================================================

    def _check_compromised_versions(self, findings: list[ScanFinding]) -> None:
        """Scan dependency files for known compromised package versions."""
        dep_files = list(self.repo_path.rglob("requirements*.txt"))
        dep_files += list(self.repo_path.rglob("pyproject.toml"))
        dep_files += list(self.repo_path.rglob("Pipfile.lock"))
        dep_files += list(self.repo_path.rglob("poetry.lock"))
        dep_files += list(self.repo_path.rglob("uv.lock"))
        dep_files += list(self.repo_path.rglob("setup.cfg"))

        for dep_file in dep_files:
            try:
                content = dep_file.read_text(errors="replace")
            except OSError:
                continue

            rel_path = str(dep_file.relative_to(self.repo_path))

            for pkg_name, bad_versions in self.KNOWN_COMPROMISED.items():
                for bad_ver in bad_versions:
                    # Check for exact references
                    patterns = [
                        rf"{pkg_name}\s*==\s*{re.escape(bad_ver)}",
                        rf'"{pkg_name}"\s*:\s*"{re.escape(bad_ver)}"',
                        rf"{pkg_name}=={re.escape(bad_ver)}",
                        rf'version\s*=\s*"{re.escape(bad_ver)}"',
                    ]
                    for pat in patterns:
                        for i, line in enumerate(content.splitlines(), 1):
                            if re.search(pat, line, re.IGNORECASE):
                                findings.append(ScanFinding(
                                    finding_id=f"ioc:compromised_version:{pkg_name}:{bad_ver}:{rel_path}:{i}",
                                    category="compromised_version",
                                    severity=Severity.CRITICAL,
                                    file_path=rel_path,
                                    line_number=i,
                                    message=(
                                        f"KNOWN COMPROMISED: {pkg_name}=={bad_ver} "
                                        f"referenced in {rel_path}. This version contains "
                                        f"a multi-stage credential stealer."
                                    ),
                                    snippet=line.strip()[:120],
                                    confidence=1.0,
                                    metadata={
                                        "package": pkg_name,
                                        "version": bad_ver,
                                        "cvss_base": 9.8,
                                        "exploit_maturity": "attacked",
                                    },
                                ))

    def _check_filesystem_iocs(self, findings: list[ScanFinding]) -> None:
        """Check for filesystem IOC patterns in code and config files."""
        for ioc in self.FILESYSTEM_IOCS:
            pattern = ioc["path_pattern"]
            matches = list(self.repo_path.rglob("*"))
            for fpath in matches:
                if not fpath.is_file():
                    continue
                rel = str(fpath.relative_to(self.repo_path))
                if re.search(pattern, rel):
                    findings.append(ScanFinding(
                        finding_id=f"ioc:filesystem_ioc:{rel}",
                        category="filesystem_ioc",
                        severity=ioc["severity"],
                        file_path=rel,
                        message=f"IOC: {ioc['description']} — file: {rel}",
                        confidence=0.95,
                        metadata={"reference": ioc.get("reference", "")},
                    ))

            # Also check for references to these paths in code
            try:
                code_matches = self._grep_repo(pattern)
                for match_file, match_line, match_num in code_matches:
                    findings.append(ScanFinding(
                        finding_id=f"ioc:filesystem_ioc_ref:{match_file}:{match_num}",
                        category="filesystem_ioc",
                        severity=Severity.HIGH,
                        file_path=match_file,
                        line_number=match_num,
                        message=f"IOC reference: {ioc['description']} — {match_line[:60]}",
                        snippet=match_line[:120],
                        confidence=0.7,
                        metadata={"reference": ioc.get("reference", "")},
                    ))
            except Exception:
                pass

    def _check_network_iocs(self, findings: list[ScanFinding]) -> None:
        """Check for known C2 domain/IP references in code."""
        for ioc in self.NETWORK_IOCS:
            matches = self._grep_repo(ioc["pattern"])
            for match_file, match_line, match_num in matches:
                findings.append(ScanFinding(
                    finding_id=f"ioc:network_ioc:{match_file}:{match_num}",
                    category="network_ioc",
                    severity=ioc["severity"],
                    file_path=match_file,
                    line_number=match_num,
                    message=f"Network IOC: {ioc['description']} — {match_line[:60]}",
                    snippet=match_line[:120],
                    confidence=0.9,
                ))

    def _check_k8s_iocs(self, findings: list[ScanFinding]) -> None:
        """Check for Kubernetes lateral movement IOC patterns."""
        for ioc in self.K8S_IOCS:
            matches = self._grep_repo(ioc["pattern"])
            for match_file, match_line, match_num in matches:
                # If context pattern is specified, check that file also contains it
                if "context" in ioc:
                    try:
                        file_content = (self.repo_path / match_file).read_text(errors="replace")
                        if not re.search(ioc["context"], file_content, re.IGNORECASE):
                            continue
                    except OSError:
                        continue

                findings.append(ScanFinding(
                    finding_id=f"ioc:k8s_ioc:{match_file}:{match_num}",
                    category="k8s_ioc",
                    severity=ioc["severity"],
                    file_path=match_file,
                    line_number=match_num,
                    message=f"K8s IOC: {ioc['description']} — {match_line[:60]}",
                    snippet=match_line[:120],
                    confidence=0.7,
                ))

    def _check_suspicious_patterns(self, findings: list[ScanFinding]) -> None:
        """Check for suspicious code patterns that may indicate compromise."""
        for pat_info in self.SUSPICIOUS_PATTERNS:
            matches = self._grep_repo(pat_info["pattern"])
            for match_file, match_line, match_num in matches:
                # Skip test files, documentation, and this analyzer itself
                if any(
                    skip in match_file
                    for skip in ("test_", "tests/", ".md", ".rst", "ioc_scanner")
                ):
                    continue

                findings.append(ScanFinding(
                    finding_id=f"ioc:suspicious_pattern:{match_file}:{match_num}",
                    category="suspicious_pattern",
                    severity=pat_info["severity"],
                    file_path=match_file,
                    line_number=match_num,
                    message=f"Suspicious: {pat_info['description']} — {match_line[:60]}",
                    snippet=match_line[:120],
                    confidence=pat_info.get("confidence", 0.5),
                ))

    def _check_env_secrets(self, findings: list[ScanFinding]) -> None:
        """Check for secrets stored in environment variables."""
        for pattern in self.ENV_SECRET_PATTERNS:
            matches = self._grep_repo(pattern)
            for match_file, match_line, match_num in matches:
                if any(
                    skip in match_file
                    for skip in ("test_", "tests/", ".md", "ioc_scanner")
                ):
                    continue

                findings.append(ScanFinding(
                    finding_id=f"ioc:env_secret_exposure:{match_file}:{match_num}",
                    category="env_secret_exposure",
                    severity=Severity.MEDIUM,
                    file_path=match_file,
                    line_number=match_num,
                    message=(
                        f"Secret in environment variable: {match_line.strip()[:60]}. "
                        f"Prefer file-based secret injection to limit blast radius."
                    ),
                    snippet=match_line.strip()[:120],
                    confidence=0.7,
                ))

    def _check_pth_files(self, findings: list[ScanFinding]) -> None:
        """Check for .pth files anywhere in the repository."""
        pth_files = list(self.repo_path.rglob("*.pth"))
        for pf in pth_files:
            rel = str(pf.relative_to(self.repo_path))
            # Read first few lines to assess content
            snippet = ""
            try:
                content = pf.read_text(errors="replace")
                lines = content.splitlines()
                snippet = "; ".join(lines[:3])[:120]
                # Check if it contains executable Python (not just paths)
                has_import = any(
                    re.search(r"\bimport\b|\bexec\b|\beval\b", line)
                    for line in lines
                )
            except OSError:
                has_import = False

            severity = Severity.CRITICAL if has_import else Severity.HIGH
            findings.append(ScanFinding(
                finding_id=f"ioc:pth_file:{rel}",
                category="pth_file",
                severity=severity,
                file_path=rel,
                message=(
                    f".pth file: {rel}"
                    + (" (contains executable code!)" if has_import else "")
                    + ". These execute at Python import time."
                ),
                snippet=snippet,
                confidence=0.9 if has_import else 0.7,
            ))

    # ==================================================================
    # Utilities
    # ==================================================================

    def _grep_repo(
        self,
        pattern: str,
        max_results: int = 50,
    ) -> list[tuple[str, str, int]]:
        """Simple regex grep across all files in repo.

        Returns list of (relative_path, line_content, line_number).
        """
        compiled = re.compile(pattern, re.IGNORECASE)
        results: list[tuple[str, str, int]] = []
        exclude_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv"}

        for fpath in self.repo_path.rglob("*"):
            if not fpath.is_file():
                continue
            parts = set(fpath.relative_to(self.repo_path).parts)
            if parts & exclude_dirs:
                continue
            # Skip binary files
            if fpath.suffix in (".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".tar", ".gz", ".zip"):
                continue

            try:
                text = fpath.read_text(errors="replace")
            except OSError:
                continue

            for i, line in enumerate(text.splitlines(), 1):
                if compiled.search(line):
                    rel = str(fpath.relative_to(self.repo_path))
                    results.append((rel, line.strip(), i))
                    if len(results) >= max_results:
                        return results

        return results
