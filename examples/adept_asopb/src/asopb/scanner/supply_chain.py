"""
Supply Chain Scanner

Detects dependency management, lock files, SBOM, ML-BOM,
pinning strategies, CI/CD security patterns, and supply-chain
attack vectors identified in the LiteLLM March 2026 compromise.

Post-LiteLLM additions (P0):
  - Open-ended vs exact version pinning classification
  - CI/CD action SHA pinning vs floating tag detection
  - .pth file injection detection
  - --require-hashes enforcement detection
  - Docker socket / privileged container detection in compose
  - Network egress policy detection
  - Bare pip install without version constraint detection
"""

from __future__ import annotations

import re
from typing import Any

from asopb.models import ScanResult, Severity
from asopb.scanner.base import ScannerBase


class SupplyChainScanner(ScannerBase):
    """Detects supply chain security patterns and anti-patterns.

    Identifies:
    - Dependency lock files (requirements.lock, package-lock.json, etc.)
    - Software Bill of Materials (SBOM) files
    - ML/AI Model BOMs
    - Version pinning strategies (exact vs open-ended)
    - Hash verification in pip install commands
    - CI/CD pipeline configurations and action pinning
    - Container signing and attestation
    - Dependency scanning tools
    - Reproducible build configurations
    - Signed commits and tags
    - .pth file injection vectors
    - Docker socket and privileged container exposure
    - Network egress policies
    """

    name = "supply_chain"
    description = "Dependency management and supply chain security"

    # Lock file patterns
    LOCK_FILE_PATTERNS = [
        "requirements.lock",
        "requirements.txt",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "go.sum",
        "Cargo.lock",
        "composer.lock",
    ]

    # SBOM patterns
    SBOM_PATTERNS = [
        "sbom.json",
        "sbom.xml",
        "sbom.spdx",
        "*sbom*",
        "cyclonedx*",
        "spdx*",
    ]

    # ML/AI Model patterns
    ML_BOM_PATTERNS = [
        r"model.*card",
        r"model_card",
        r"model.*provenance",
        r"model.*license",
        r"model.*version",
        r"model.*hash",
        r"model.*checksum",
        r"model.*signature",
        r"modelcard\.md",
        r"MODEL_CARD",
    ]

    # ---------------------------------------------------------------
    # Version pinning: exact vs open-ended (P0)
    # ---------------------------------------------------------------
    EXACT_PIN_RE = re.compile(r"==\d+\.\d+[\.\d]*")
    HASH_PIN_RE = re.compile(r"--hash[= ]|sha256:")
    OPEN_ENDED_PIN_RE = re.compile(r">=\d+\.\d+[\.\d]*(?!\s*,\s*<)")  # >= without upper bound
    COMPATIBLE_PIN_RE = re.compile(r"~=\d+\.\d+")

    # ---------------------------------------------------------------
    # CI/CD patterns (extended for action pinning — P0)
    # ---------------------------------------------------------------
    CICD_FILE_PATTERNS = [
        ".github/workflows",
        ".gitlab-ci.yml",
        "Jenkinsfile",
        ".circleci/config.yml",
        "azure-pipelines.yml",
        ".travis.yml",
        "tox.ini",
        ".pre-commit-config.yaml",
    ]

    # GitHub Actions: SHA-pinned (POSITIVE) vs floating tag (NEGATIVE)
    ACTION_SHA_PIN_RE = re.compile(r"uses:\s+[\w\-\.]+/[\w\-\.]+@[a-f0-9]{40}")
    ACTION_FLOAT_TAG_RE = re.compile(r"uses:\s+[\w\-\.]+/[\w\-\.]+@v[\d\.]+")
    # Dangerous workflow trigger
    PULL_REQUEST_TARGET_RE = re.compile(r"pull_request_target")

    # ---------------------------------------------------------------
    # .pth file injection detection (P0)
    # ---------------------------------------------------------------
    PTH_FILE_GLOBS = ["**/*.pth"]
    PTH_REFERENCE_RE = re.compile(r"\.pth\b")

    # ---------------------------------------------------------------
    # pip install patterns (P0)
    # ---------------------------------------------------------------
    REQUIRE_HASHES_RE = re.compile(r"--require-hashes")
    BARE_PIP_INSTALL_RE = re.compile(
        r"pip\s+install\s+(?!.*(?:--require-hashes|-r\s|requirements))"
        r"[\w\-]+"
        r"(?!\s*[=~<>!])"
    )

    # ---------------------------------------------------------------
    # Container security patterns (P0 cross-domain)
    # ---------------------------------------------------------------
    DOCKER_SOCKET_RE = re.compile(r"/var/run/docker\.sock")
    PRIVILEGED_RE = re.compile(r"privileged:\s*true", re.IGNORECASE)
    HOST_PID_RE = re.compile(r"hostPID:\s*true", re.IGNORECASE)
    HOST_NETWORK_RE = re.compile(r"hostNetwork:\s*true|network_mode:\s*[\"']?host", re.IGNORECASE)
    READ_ONLY_FS_RE = re.compile(r"read_only:\s*true", re.IGNORECASE)
    SECCOMP_RE = re.compile(r"seccomp|security_opt.*seccomp", re.IGNORECASE)

    # ---------------------------------------------------------------
    # Network egress policy detection (P0)
    # ---------------------------------------------------------------
    NETWORK_EGRESS_PATTERNS = [
        r"NetworkPolicy",
        r"egress:\s*\[",
        r"iptables.*OUTPUT",
        r"nftables",
        r"calico.*NetworkPolicy",
        r"cilium.*NetworkPolicy",
    ]

    # ---------------------------------------------------------------
    # Existing patterns (unchanged)
    # ---------------------------------------------------------------
    CONTAINER_SIGNING_PATTERNS = [
        r"cosign",
        r"notation",
        r"sigstore",
        r"docker.*sign",
        r"container.*sign",
        r"image.*verify",
        r"attestation",
        r"sbom.*attach",
        r"--signingIdentity",
        r"--keyPath",
    ]

    DEPENDENCY_SCAN_PATTERNS = [
        r"dependabot",
        r"Dependabot",
        r"snyk",
        r"Snyk",
        r"pip-audit",
        r"safety",
        r"bandit",
        r"trivy",
        r"grype",
        r"owasp.*dependency",
    ]

    REPRODUCIBLE_PATTERNS = [
        r"BUILD_REPRODUCIBLE",
        r"SOURCE_DATE_EPOCH",
        r"reproducible.*build",
        r"nix.*flake",
        r"flake\.nix",
        r"bazel",
        r"buck",
    ]

    SIGNED_COMMIT_PATTERNS = [
        r"--gpg-sign",
        r"--sign",
        r"gpg.*sign",
        r"commit.*signed",
        r"tag.*signed",
        r"verification.*required",
        r"branch.*protection",
    ]

    LICENSE_PATTERNS = [
        r"LICENSE",
        r"LICENSE\.txt",
        r"COPYING",
        r"licenses\.csv",
        r"license.*check",
        r"license.*compliance",
        r"spdx.*identifier",
    ]

    async def scan(self) -> ScanResult:
        """Execute supply chain scanner."""
        result = ScanResult(
            tool_name=self.name,
            tool_version="2.0.0",
        )

        findings = []
        stats: dict[str, Any] = {
            "lock_files": [],
            "sbom_files": [],
            "ml_bom_patterns": 0,
            "cicd_pipelines": [],
            "container_signing": 0,
            "dependency_scanning": 0,
            "reproducible_builds": 0,
            "signed_commits": 0,
            "license_files": [],
            # P0 additions
            "exact_pins": 0,
            "open_ended_pins": 0,
            "compatible_pins": 0,
            "hash_pins": 0,
            "pin_strength_ratio": 0.0,
            "actions_sha_pinned": 0,
            "actions_float_tagged": 0,
            "action_pin_ratio": 0.0,
            "pth_files_found": 0,
            "pth_references": 0,
            "require_hashes_count": 0,
            "bare_pip_install_count": 0,
            "docker_socket_mounts": 0,
            "privileged_containers": 0,
            "host_pid_network": 0,
            "read_only_fs": 0,
            "seccomp_profiles": 0,
            "network_egress_policies": 0,
            "pull_request_target": 0,
        }

        try:
            # ===== Lock files =====
            for lock_pattern in self.LOCK_FILE_PATTERNS:
                lock_files = self.find_files(lock_pattern)
                for lf in lock_files:
                    rel_path = str(lf.relative_to(self.repo_path))
                    stats["lock_files"].append(rel_path)
                    findings.append(self._make_finding(
                        "lock_file_found",
                        f"Dependency lock file: {rel_path}",
                        file_path=rel_path,
                        severity=Severity.INFORMATIONAL,
                    ))

            # ===== SBOM files =====
            for sbom_pattern in self.SBOM_PATTERNS:
                for sf in self.find_files(sbom_pattern):
                    rel_path = str(sf.relative_to(self.repo_path))
                    stats["sbom_files"].append(rel_path)
                    findings.append(self._make_finding(
                        "sbom_file_found",
                        f"SBOM file found: {rel_path}",
                        file_path=rel_path,
                        severity=Severity.INFORMATIONAL,
                    ))

            # ===== ML/Model BOM =====
            ml_bom_matches = self.grep(
                "|".join(self.ML_BOM_PATTERNS),
                glob="**/*", ignore_case=True,
            )
            stats["ml_bom_patterns"] = len(ml_bom_matches)
            for match in ml_bom_matches[:3]:
                findings.append(self._make_finding(
                    "ml_model_bom",
                    f"ML/Model BOM pattern: {match.match_text}",
                    file_path=match.file_path,
                    line_number=match.line_number,
                    severity=Severity.INFORMATIONAL,
                ))

            # ===== P0: Version pinning strength analysis =====
            self._scan_pin_strength(findings, stats)

            # ===== P0: Hash verification =====
            self._scan_hash_verification(findings, stats)

            # ===== P0: Bare pip install =====
            self._scan_bare_pip_install(findings, stats)

            # ===== CI/CD pipelines =====
            for cicd_pattern in self.CICD_FILE_PATTERNS:
                for cf in self.find_files(cicd_pattern):
                    rel_path = str(cf.relative_to(self.repo_path))
                    stats["cicd_pipelines"].append(rel_path)
                    findings.append(self._make_finding(
                        "cicd_pipeline_found",
                        f"CI/CD pipeline configuration: {rel_path}",
                        file_path=rel_path,
                        severity=Severity.INFORMATIONAL,
                    ))

            # ===== P0: CI/CD action pinning analysis =====
            self._scan_action_pinning(findings, stats)

            # ===== P0: pull_request_target detection =====
            self._scan_pull_request_target(findings, stats)

            # ===== P0: .pth file detection =====
            self._scan_pth_files(findings, stats)

            # ===== P0: Container security =====
            self._scan_container_security(findings, stats)

            # ===== P0: Network egress policies =====
            self._scan_network_egress(findings, stats)

            # ===== Container signing =====
            signing_matches = self.grep(
                "|".join(self.CONTAINER_SIGNING_PATTERNS),
                glob="**/*", ignore_case=True,
            )
            stats["container_signing"] = len(signing_matches)
            for match in signing_matches[:3]:
                findings.append(self._make_finding(
                    "container_signing",
                    f"Container signing/attestation: {match.match_text}",
                    file_path=match.file_path,
                    line_number=match.line_number,
                    severity=Severity.INFORMATIONAL,
                ))

            # ===== Dependency scanning tools =====
            dep_matches = self.grep(
                "|".join(self.DEPENDENCY_SCAN_PATTERNS),
                glob="**/*", ignore_case=True,
            )
            stats["dependency_scanning"] = len(dep_matches)
            for match in dep_matches[:3]:
                findings.append(self._make_finding(
                    "dependency_scanning_tool",
                    f"Dependency scanning tool: {match.match_text}",
                    file_path=match.file_path,
                    line_number=match.line_number,
                    severity=Severity.INFORMATIONAL,
                ))

            # ===== Reproducible builds =====
            repro_matches = self.grep(
                "|".join(self.REPRODUCIBLE_PATTERNS),
                glob="**/*", ignore_case=True,
            )
            stats["reproducible_builds"] = len(repro_matches)
            for match in repro_matches[:3]:
                findings.append(self._make_finding(
                    "reproducible_build",
                    f"Reproducible build pattern: {match.match_text}",
                    file_path=match.file_path,
                    line_number=match.line_number,
                    severity=Severity.INFORMATIONAL,
                ))

            # ===== Signed commits =====
            signed_matches = self.grep(
                "|".join(self.SIGNED_COMMIT_PATTERNS),
                glob="**/*", ignore_case=True,
            )
            stats["signed_commits"] = len(signed_matches)
            for match in signed_matches[:3]:
                findings.append(self._make_finding(
                    "signed_commits",
                    f"Signed commit/tag pattern: {match.match_text}",
                    file_path=match.file_path,
                    line_number=match.line_number,
                    severity=Severity.INFORMATIONAL,
                ))

            # ===== License files =====
            for license_pattern in self.LICENSE_PATTERNS:
                for lf in self.find_files(license_pattern):
                    rel_path = str(lf.relative_to(self.repo_path))
                    stats["license_files"].append(rel_path)
                    findings.append(self._make_finding(
                        "license_file_found",
                        f"License file: {rel_path}",
                        file_path=rel_path,
                        severity=Severity.INFORMATIONAL,
                    ))

            # ===== Compute aggregate ratios =====
            total_pins = stats["exact_pins"] + stats["open_ended_pins"] + stats["compatible_pins"]
            if total_pins > 0:
                stats["pin_strength_ratio"] = round(
                    (stats["exact_pins"] + stats["hash_pins"]) / total_pins, 3
                )

            total_actions = stats["actions_sha_pinned"] + stats["actions_float_tagged"]
            if total_actions > 0:
                stats["action_pin_ratio"] = round(
                    stats["actions_sha_pinned"] / total_actions, 3
                )

            result.findings = findings
            result.summary_stats = stats
            result.success = True

        except Exception as e:
            result.success = False
            result.error_message = str(e)

        return result

    # ==================================================================
    # P0 scan methods
    # ==================================================================

    def _scan_pin_strength(self, findings: list, stats: dict) -> None:
        """Classify version pins as exact, compatible, or open-ended."""
        dep_globs = [
            "**/*requirements*.txt",
            "**/*requirements*.in",
            "**/pyproject.toml",
            "**/setup.cfg",
            "**/Pipfile",
        ]

        for glob_pat in dep_globs:
            for fpath in self.find_files(glob_pat):
                rel_path = str(fpath.relative_to(self.repo_path))
                try:
                    content = fpath.read_text(errors="replace")
                except OSError:
                    continue

                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue

                    if self.HASH_PIN_RE.search(stripped):
                        stats["hash_pins"] += 1
                    if self.EXACT_PIN_RE.search(stripped):
                        stats["exact_pins"] += 1
                    elif self.OPEN_ENDED_PIN_RE.search(stripped):
                        stats["open_ended_pins"] += 1
                        findings.append(self._make_finding(
                            "open_ended_version_pin",
                            f"Open-ended version pin (no upper bound): {stripped[:80]}",
                            file_path=rel_path,
                            line_number=i,
                            snippet=stripped[:120],
                            severity=Severity.HIGH,
                            confidence=0.9,
                        ))
                    elif self.COMPATIBLE_PIN_RE.search(stripped):
                        stats["compatible_pins"] += 1

        # Summary finding
        total = stats["exact_pins"] + stats["open_ended_pins"] + stats["compatible_pins"]
        if total > 0 and stats["open_ended_pins"] > 0:
            pct = stats["open_ended_pins"] / total * 100
            findings.append(self._make_finding(
                "pin_strength_summary",
                (
                    f"Pin strength: {stats['exact_pins']} exact, "
                    f"{stats['compatible_pins']} compatible, "
                    f"{stats['open_ended_pins']} open-ended ({pct:.0f}%), "
                    f"{stats['hash_pins']} hash-verified"
                ),
                severity=Severity.HIGH if pct > 30 else Severity.MEDIUM,
            ))

    def _scan_hash_verification(self, findings: list, stats: dict) -> None:
        """Detect --require-hashes usage in pip install commands."""
        matches = self.grep(
            r"--require-hashes",
            glob="**/*",
            ignore_case=False,
        )
        stats["require_hashes_count"] = len(matches)
        for match in matches[:5]:
            findings.append(self._make_finding(
                "require_hashes_enforced",
                f"Hash verification enforced: {match.line_content[:80]}",
                file_path=match.file_path,
                line_number=match.line_number,
                severity=Severity.INFORMATIONAL,
                confidence=0.95,
            ))

        if len(matches) == 0:
            findings.append(self._make_finding(
                "require_hashes_missing",
                "No --require-hashes flag found in any pip install command",
                severity=Severity.MEDIUM,
                confidence=0.8,
            ))

    def _scan_bare_pip_install(self, findings: list, stats: dict) -> None:
        """Detect bare pip install without version constraints."""
        target_globs = ["**/*.sh", "**/Makefile", "**/Dockerfile*", "**/*.yml", "**/*.yaml"]
        for glob_pat in target_globs:
            for fpath in self.find_files(glob_pat):
                rel_path = str(fpath.relative_to(self.repo_path))
                try:
                    content = fpath.read_text(errors="replace")
                except OSError:
                    continue

                for i, line in enumerate(content.splitlines(), 1):
                    if self.BARE_PIP_INSTALL_RE.search(line):
                        stats["bare_pip_install_count"] += 1
                        findings.append(self._make_finding(
                            "bare_pip_install",
                            f"Bare pip install without version constraint: {line.strip()[:80]}",
                            file_path=rel_path,
                            line_number=i,
                            snippet=line.strip()[:120],
                            severity=Severity.HIGH,
                            confidence=0.85,
                        ))

    def _scan_action_pinning(self, findings: list, stats: dict) -> None:
        """Classify GitHub Actions as SHA-pinned vs floating-tag."""
        workflow_files = self.find_files(".github/workflows/*.yml") + \
                         self.find_files(".github/workflows/*.yaml")

        for wf in workflow_files:
            rel_path = str(wf.relative_to(self.repo_path))
            try:
                content = wf.read_text(errors="replace")
            except OSError:
                continue

            for i, line in enumerate(content.splitlines(), 1):
                if self.ACTION_SHA_PIN_RE.search(line):
                    stats["actions_sha_pinned"] += 1
                    findings.append(self._make_finding(
                        "action_sha_pinned",
                        f"GitHub Action pinned to commit SHA: {line.strip()[:80]}",
                        file_path=rel_path,
                        line_number=i,
                        severity=Severity.INFORMATIONAL,
                        confidence=0.95,
                    ))
                elif self.ACTION_FLOAT_TAG_RE.search(line):
                    stats["actions_float_tagged"] += 1
                    findings.append(self._make_finding(
                        "action_floating_tag",
                        f"GitHub Action uses floating tag (not SHA-pinned): {line.strip()[:80]}",
                        file_path=rel_path,
                        line_number=i,
                        severity=Severity.HIGH,
                        confidence=0.9,
                    ))

        # Summary
        total = stats["actions_sha_pinned"] + stats["actions_float_tagged"]
        if total > 0 and stats["actions_float_tagged"] > 0:
            findings.append(self._make_finding(
                "action_pin_summary",
                (
                    f"CI/CD action pinning: {stats['actions_sha_pinned']} SHA-pinned, "
                    f"{stats['actions_float_tagged']} floating-tag "
                    f"({stats['actions_float_tagged']/total*100:.0f}% unpinned)"
                ),
                severity=Severity.HIGH,
            ))

    def _scan_pull_request_target(self, findings: list, stats: dict) -> None:
        """Detect dangerous pull_request_target workflow trigger."""
        matches = self.grep(
            r"pull_request_target",
            glob=".github/workflows/*.yml",
            ignore_case=False,
        )
        # Also check .yaml extension
        matches += self.grep(
            r"pull_request_target",
            glob=".github/workflows/*.yaml",
            ignore_case=False,
        )
        stats["pull_request_target"] = len(matches)
        for match in matches:
            findings.append(self._make_finding(
                "pull_request_target_trigger",
                (
                    f"Dangerous pull_request_target workflow trigger detected. "
                    f"This can expose secrets to fork PRs: {match.line_content[:60]}"
                ),
                file_path=match.file_path,
                line_number=match.line_number,
                severity=Severity.CRITICAL,
                confidence=0.95,
            ))

    def _scan_pth_files(self, findings: list, stats: dict) -> None:
        """Detect .pth files and references (import-time code execution vector)."""
        for glob_pat in self.PTH_FILE_GLOBS:
            pth_files = self.find_files(glob_pat)
            stats["pth_files_found"] += len(pth_files)
            for pf in pth_files:
                rel_path = str(pf.relative_to(self.repo_path))
                findings.append(self._make_finding(
                    "pth_file_found",
                    (
                        f".pth file detected: {rel_path}. "
                        f"These execute Python code at import time and are a "
                        f"known supply chain attack vector (LiteLLM 1.82.8)."
                    ),
                    file_path=rel_path,
                    severity=Severity.HIGH,
                    confidence=0.9,
                ))

        # Check for .pth references in build/deploy scripts
        pth_refs = self.grep(
            r"\.pth\b",
            glob="**/*",
            ignore_case=False,
        )
        # Filter out false positives (documentation, this scanner itself, etc.)
        real_refs = [
            m for m in pth_refs
            if not m.file_path.endswith((".md", ".rst", ".txt"))
            and "supply_chain" not in m.file_path
        ]
        stats["pth_references"] = len(real_refs)
        for match in real_refs[:5]:
            findings.append(self._make_finding(
                "pth_reference",
                f".pth file reference in build/code: {match.line_content[:80]}",
                file_path=match.file_path,
                line_number=match.line_number,
                severity=Severity.MEDIUM,
                confidence=0.7,
            ))

    def _scan_container_security(self, findings: list, stats: dict) -> None:
        """Detect Docker socket mounts, privileged containers, host access."""
        compose_globs = [
            "**/docker-compose*.yml",
            "**/docker-compose*.yaml",
            "**/compose*.yml",
            "**/compose*.yaml",
            "**/*.yml",
            "**/*.yaml",
        ]

        # Docker socket
        socket_matches = self.grep(
            r"/var/run/docker\.sock",
            glob="**/*",
            ignore_case=False,
        )
        stats["docker_socket_mounts"] = len(socket_matches)
        for match in socket_matches[:5]:
            findings.append(self._make_finding(
                "docker_socket_mount",
                (
                    f"Docker socket mount detected: {match.line_content.strip()[:80]}. "
                    f"Equivalent to root access on host — enables container escape."
                ),
                file_path=match.file_path,
                line_number=match.line_number,
                severity=Severity.CRITICAL,
                confidence=0.95,
            ))

        # Privileged containers
        priv_matches = self.grep(
            r"privileged:\s*true",
            glob="**/*",
            ignore_case=True,
        )
        stats["privileged_containers"] = len(priv_matches)
        for match in priv_matches[:5]:
            findings.append(self._make_finding(
                "privileged_container",
                f"Privileged container detected: {match.line_content.strip()[:80]}",
                file_path=match.file_path,
                line_number=match.line_number,
                severity=Severity.CRITICAL,
                confidence=0.9,
            ))

        # hostPID / hostNetwork
        for pattern, category, label in [
            (r"hostPID:\s*true", "host_pid", "hostPID"),
            (r"hostNetwork:\s*true|network_mode:\s*[\"']?host", "host_network", "hostNetwork"),
        ]:
            matches = self.grep(pattern, glob="**/*", ignore_case=True)
            stats["host_pid_network"] += len(matches)
            for match in matches[:3]:
                findings.append(self._make_finding(
                    category,
                    f"{label} access detected: {match.line_content.strip()[:80]}",
                    file_path=match.file_path,
                    line_number=match.line_number,
                    severity=Severity.HIGH,
                    confidence=0.9,
                ))

        # Read-only filesystem (positive)
        ro_matches = self.grep(r"read_only:\s*true", glob="**/*", ignore_case=True)
        stats["read_only_fs"] = len(ro_matches)
        for match in ro_matches[:3]:
            findings.append(self._make_finding(
                "read_only_filesystem",
                f"Read-only filesystem enforced: {match.line_content.strip()[:80]}",
                file_path=match.file_path,
                line_number=match.line_number,
                severity=Severity.INFORMATIONAL,
                confidence=0.9,
            ))

        # Seccomp profiles (positive)
        seccomp_matches = self.grep(
            r"seccomp|security_opt.*seccomp",
            glob="**/*", ignore_case=True,
        )
        stats["seccomp_profiles"] = len(seccomp_matches)
        for match in seccomp_matches[:3]:
            findings.append(self._make_finding(
                "seccomp_profile",
                f"Seccomp profile reference: {match.line_content.strip()[:80]}",
                file_path=match.file_path,
                line_number=match.line_number,
                severity=Severity.INFORMATIONAL,
                confidence=0.85,
            ))

    def _scan_network_egress(self, findings: list, stats: dict) -> None:
        """Detect network egress policies (K8s NetworkPolicy, iptables, etc.)."""
        egress_matches = self.grep(
            "|".join(self.NETWORK_EGRESS_PATTERNS),
            glob="**/*",
            ignore_case=True,
        )
        stats["network_egress_policies"] = len(egress_matches)
        for match in egress_matches[:5]:
            findings.append(self._make_finding(
                "network_egress_policy",
                f"Network egress policy: {match.match_text} in {match.file_path}",
                file_path=match.file_path,
                line_number=match.line_number,
                severity=Severity.INFORMATIONAL,
                confidence=0.8,
            ))

        if len(egress_matches) == 0:
            findings.append(self._make_finding(
                "network_egress_missing",
                (
                    "No network egress policies detected. Containers have unrestricted "
                    "outbound access, enabling C2 callbacks from compromised dependencies."
                ),
                severity=Severity.HIGH,
                confidence=0.7,
            ))
