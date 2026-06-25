"""
D8: Supply Chain and Ecosystem Domain Evaluator

Evaluates supply chain security for agentic systems using evidence from
the SupplyChainScanner (v2.0) and IOCAnalyzer.  Assesses dependency
visibility, vulnerability scanning, vendor trust, third-party code
security, ecosystem resilience, CI/CD pipeline security, runtime package
integrity, and network egress policy.

Controls:
  D8.1: Dependency visibility (are all dependencies tracked?)
  D8.2: Dependency vulnerability scanning (are vulnerabilities detected?)
  D8.3: Vendor trust and assessment (are vendors assessed?)
  D8.4: Third-party code security (is third-party code audited?)
  D8.5: Ecosystem resilience (is system resilient to ecosystem failures?)
  D8.6: CI/CD pipeline security (are actions SHA-pinned, secrets scoped?)
  D8.7: Runtime package integrity (.pth monitoring, hash verification)
  D8.8: Network egress policy (outbound connections restricted?)
"""

from __future__ import annotations

from typing import Optional

from asopb.config import EvalConfig
from asopb.models import (
    ControlDefinition,
    ControlEvidence,
    ControlScore,
    ControlStatus,
    EvidenceSource,
    EvidenceTier,
    ScanResult,
    Severity,
)

from .base import DomainEvaluator


class D8SupplyChainEvaluator(DomainEvaluator):
    """Supply Chain and Ecosystem domain evaluator."""

    domain_id = "D8"
    domain_name = "Supply Chain and Ecosystem"
    weight = 1.0
    skill_file = "d8_supply_chain.md"

    def define_controls(self) -> list[ControlDefinition]:
        """Define D8 controls for supply chain security."""
        return [
            ControlDefinition(
                control_id="D8.1",
                domain_id="D8",
                name="Dependency Visibility",
                description=(
                    "All direct and transitive dependencies are tracked and visible. "
                    "Dependency manifests (requirements.txt, go.mod, package.json, etc.) "
                    "are version-pinned and reproducible."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S1", "S2", "S3", "S4"],
                t1_criteria=[
                    "Dependency manifest files are documented",
                    "Version pinning strategy is specified",
                ],
                t2_criteria=[
                    "Dependency manifests present and properly formatted",
                    "Version pinning enforced (no floating versions)",
                    "Lock files (package-lock.json, go.sum, Pipfile.lock) in repo",
                ],
                nist_mapping=["SA-3"],
                owasp_mapping=["LLM01"],
                cwe_mapping=["CWE-829"],
                tags=["dependency", "supply-chain", "visibility"],
            ),
            ControlDefinition(
                control_id="D8.2",
                domain_id="D8",
                name="Dependency Vulnerability Scanning",
                description=(
                    "Dependencies are scanned for known vulnerabilities. Scanning "
                    "is automated and results are tracked."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Vulnerability scanning tool is specified",
                    "Scan frequency and remediation SLA are defined",
                ],
                t2_criteria=[
                    "Vulnerability scanner integrated in build pipeline",
                    "Scan results captured and tracked",
                    "Remediation plan for critical/high severity vulnerabilities",
                ],
                nist_mapping=["SI-2", "RA-5"],
                owasp_mapping=["LLM01"],
                cwe_mapping=["CWE-1035"],
                tags=["vulnerability", "dependency", "scanning"],
            ),
            ControlDefinition(
                control_id="D8.3",
                domain_id="D8",
                name="Vendor Trust and Assessment",
                description=(
                    "Third-party vendors and dependencies are assessed for trust. "
                    "Vendor track record, security practices, and maintenance status "
                    "are evaluated before adoption."
                ),
                severity=Severity.MEDIUM,
                applicable_stages=["S1", "S2"],
                t1_criteria=[
                    "Vendor assessment criteria are documented",
                    "Trusted vendor list or approval process is defined",
                ],
                t2_criteria=[
                    "Vendor assessment records maintained",
                    "High-risk dependencies flagged or quarantined",
                    "Maintenance status monitoring for dependencies",
                ],
                nist_mapping=["SA-3", "SA-9"],
                owasp_mapping=["LLM01"],
                cwe_mapping=["CWE-829"],
                tags=["vendor", "trust", "assessment"],
            ),
            ControlDefinition(
                control_id="D8.4",
                domain_id="D8",
                name="Third-Party Code Security",
                description=(
                    "Third-party code is audited or scanned. Supply chain attack "
                    "vectors are considered. Container images are signed."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S1", "S2"],
                t1_criteria=[
                    "Third-party code review strategy is documented",
                    "Supply chain attack risk is assessed",
                ],
                t2_criteria=[
                    "Static analysis applied to critical third-party code",
                    "Security advisory monitoring for third-party projects",
                    "Artifact signature verification for critical dependencies",
                ],
                nist_mapping=["SA-3", "SA-4"],
                owasp_mapping=["LLM01"],
                cwe_mapping=["CWE-829"],
                tags=["third-party", "code-review", "supply-chain"],
            ),
            ControlDefinition(
                control_id="D8.5",
                domain_id="D8",
                name="Ecosystem Resilience",
                description=(
                    "System is resilient to ecosystem failures: package repo outages, "
                    "deprecated dependencies, abandoned projects."
                ),
                severity=Severity.MEDIUM,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Ecosystem resilience strategy is documented",
                    "Fallback and offline capability is specified",
                ],
                t2_criteria=[
                    "Package caching or mirroring for critical dependencies",
                    "Deprecation handling for legacy dependencies",
                    "Offline build capability or vendored dependencies",
                ],
                nist_mapping=["SI-13"],
                owasp_mapping=["LLM01"],
                cwe_mapping=["CWE-829"],
                tags=["resilience", "ecosystem", "dependencies"],
            ),
            # ===== Post-LiteLLM controls (P0) =====
            ControlDefinition(
                control_id="D8.6",
                domain_id="D8",
                name="CI/CD Pipeline Security",
                description=(
                    "CI/CD pipelines use SHA-pinned actions (not floating tags), "
                    "secrets are scoped to minimum-necessary jobs, and dangerous "
                    "workflow triggers (pull_request_target) are restricted."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "CI/CD security policy documented",
                    "Action pinning strategy defined",
                    "Secret scoping rules specified",
                ],
                t2_criteria=[
                    "All GitHub Actions pinned to commit SHAs",
                    "Secrets scoped to minimum-necessary jobs",
                    "pull_request_target workflows restricted or absent",
                    "Dependabot/Renovate configured for action updates",
                ],
                t3_criteria=[
                    "Red-team demonstrates inability to exfiltrate CI/CD secrets",
                    "Simulated compromised action cannot publish packages",
                ],
                nist_mapping=["SA-3", "SA-15"],
                cwe_mapping=["CWE-829", "CWE-915"],
                tags=["ci-cd", "action-pinning", "supply-chain"],
            ),
            ControlDefinition(
                control_id="D8.7",
                domain_id="D8",
                name="Runtime Package Integrity",
                description=(
                    "Runtime integrity monitoring for installed packages. "
                    ".pth file allowlist enforced, --require-hashes used, "
                    "site-packages mounted read-only in production."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Runtime integrity monitoring strategy documented",
                    ".pth file policy defined",
                    "Post-install verification approach specified",
                ],
                t2_criteria=[
                    ".pth file allowlist enforced in container health checks",
                    "--require-hashes used in all pip install commands",
                    "site-packages mounted read-only in production",
                    "Periodic hash verification of installed packages against lock file",
                ],
                t3_criteria=[
                    "Injected .pth files detected and blocked",
                    "Simulated package modification triggers alert",
                ],
                nist_mapping=["SI-7", "SI-4"],
                cwe_mapping=["CWE-506", "CWE-494"],
                tags=["runtime-integrity", "pth", "hash-verification"],
            ),
            ControlDefinition(
                control_id="D8.8",
                domain_id="D8",
                name="Network Egress Policy",
                description=(
                    "Outbound network connections restricted to allowlisted endpoints. "
                    "Egress violations logged and alerted. DNS monitored."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Network egress policy documented",
                    "Allowlisted endpoints defined per service",
                    "Monitoring approach specified",
                ],
                t2_criteria=[
                    "Network policies restrict outbound to allowlisted endpoints",
                    "Egress violations logged and alerted",
                    "DNS resolution monitored for anomalous domains",
                ],
                t3_criteria=[
                    "C2 callback from compromised dependency blocked",
                    "Exfiltration to non-allowlisted domain fails and triggers alert",
                ],
                nist_mapping=["SC-7", "SI-4"],
                cwe_mapping=["CWE-941"],
                tags=["network-egress", "egress-policy", "supply-chain"],
            ),
        ]

    def required_scanners(self) -> list[str]:
        """Scanners required for D8 evaluation."""
        return ["supply_chain", "codebase"]

    def required_analyzers(self) -> list[str]:
        """Analyzers that enhance D8 scoring."""
        return ["pip_audit", "semgrep", "ioc_scanner"]

    async def score_controls(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Score D8 controls using supply chain scanner and IOC analyzer evidence."""
        controls = self.define_controls()
        scores: list[ControlScore] = []

        # Extract supply chain scanner stats
        sc = scan_results.get("supply_chain")
        sc_stats = sc.summary_stats if sc and sc.success else {}
        sc_findings = sc.findings if sc and sc.success else []

        # Extract IOC analyzer results
        ioc = analyzer_results.get("ioc_scanner")
        ioc_findings = ioc.findings if ioc and ioc.success else []
        ioc_stats = ioc.summary_stats if ioc and ioc.success else {}

        # Extract pip-audit results
        pip_audit = analyzer_results.get("pip_audit")
        pip_audit_findings = pip_audit.findings if pip_audit and pip_audit.success else []

        for control in controls:
            if control.control_id == "D8.1":
                scores.append(self._score_d8_1(control, sc_stats, sc_findings))
            elif control.control_id == "D8.2":
                scores.append(self._score_d8_2(control, sc_stats, sc_findings, pip_audit_findings))
            elif control.control_id == "D8.3":
                scores.append(self._score_d8_3(control, sc_stats, sc_findings))
            elif control.control_id == "D8.4":
                scores.append(self._score_d8_4(control, sc_stats, sc_findings, ioc_findings))
            elif control.control_id == "D8.5":
                scores.append(self._score_d8_5(control, sc_stats, sc_findings))
            elif control.control_id == "D8.6":
                scores.append(self._score_d8_6(control, sc_stats, sc_findings))
            elif control.control_id == "D8.7":
                scores.append(self._score_d8_7(control, sc_stats, sc_findings, ioc_findings))
            elif control.control_id == "D8.8":
                scores.append(self._score_d8_8(control, sc_stats, sc_findings))

        return scores

    # ==================================================================
    # Per-control scoring methods
    # ==================================================================

    def _score_d8_1(self, ctrl: ControlDefinition, stats: dict, findings: list) -> ControlScore:
        """D8.1: Dependency Visibility — lock files, version pinning."""
        evidence = []
        gaps = []
        t2 = 0.0

        lock_files = stats.get("lock_files", [])
        exact_pins = stats.get("exact_pins", 0)
        open_ended = stats.get("open_ended_pins", 0)
        hash_pins = stats.get("hash_pins", 0)
        pin_ratio = stats.get("pin_strength_ratio", 0.0)

        # Lock files present
        if lock_files:
            t2 += 2.0
            evidence.append(self._ev(
                f"{len(lock_files)} lock file(s) found: {', '.join(lock_files[:5])}",
            ))
        else:
            gaps.append("No dependency lock files found")

        # Pinning strength
        if pin_ratio >= 0.9:
            t2 += 4.0
            evidence.append(self._ev(
                f"Strong pinning: {exact_pins} exact + {hash_pins} hash-verified "
                f"(ratio: {pin_ratio:.0%})",
            ))
        elif pin_ratio >= 0.5:
            t2 += 2.0
            evidence.append(self._ev(
                f"Moderate pinning: ratio {pin_ratio:.0%} "
                f"({open_ended} open-ended pins remain)",
            ))
        elif exact_pins > 0:
            t2 += 1.0
            evidence.append(self._ev(
                f"Weak pinning: {open_ended} open-ended, {exact_pins} exact",
            ))
            gaps.append(f"{open_ended} open-ended version pins (>=X without upper bound)")
        else:
            gaps.append("No version pinning detected")

        # Hash verification bonus
        if hash_pins > 0:
            t2 += 1.5
            evidence.append(self._ev(
                f"{hash_pins} hash-pinned dependencies (SHA-256 verification)",
            ))

        # SBOM presence
        sbom_files = stats.get("sbom_files", [])
        if sbom_files:
            t2 += 1.5
            evidence.append(self._ev(f"SBOM file(s) found: {', '.join(sbom_files[:3])}"))
        else:
            gaps.append("No SBOM (Software Bill of Materials) found")

        t2 = min(t2, 10.0)
        status = self._status_from_score(t2)

        return self._make_control_score(
            ctrl.control_id, ctrl.name,
            t1=min(t2 + 2.0, 10.0),  # T1 credit for having manifests
            t2=t2,
            status=status,
            evidence=evidence,
            gaps=gaps,
        )

    def _score_d8_2(self, ctrl: ControlDefinition, stats: dict, findings: list,
                     pip_audit_findings: list) -> ControlScore:
        """D8.2: Dependency Vulnerability Scanning."""
        evidence = []
        gaps = []
        t2 = 0.0

        dep_scanning = stats.get("dependency_scanning", 0)
        if dep_scanning > 0:
            t2 += 3.0
            evidence.append(self._ev(
                f"Dependency scanning tools referenced ({dep_scanning} instances)",
            ))
        else:
            gaps.append("No dependency scanning tools detected (pip-audit, Snyk, Trivy, etc.)")

        # pip-audit results
        if pip_audit_findings:
            crit_high = sum(
                1 for f in pip_audit_findings
                if f.severity in (Severity.CRITICAL, Severity.HIGH)
            )
            if crit_high == 0:
                t2 += 4.0
                evidence.append(self._ev(
                    f"pip-audit: {len(pip_audit_findings)} findings, 0 critical/high",
                ))
            else:
                t2 += 1.0
                evidence.append(self._ev(
                    f"pip-audit: {crit_high} critical/high vulnerabilities detected",
                ))
                gaps.append(f"{crit_high} unresolved critical/high vulnerabilities")
        elif dep_scanning == 0:
            gaps.append("pip-audit not available — no vulnerability scan data")

        # CI/CD integration for scanning
        cicd_pipelines = stats.get("cicd_pipelines", [])
        if cicd_pipelines and dep_scanning > 0:
            t2 += 2.0
            evidence.append(self._ev("Scanning appears integrated in CI/CD pipeline"))

        t2 = min(t2, 10.0)
        return self._make_control_score(
            ctrl.control_id, ctrl.name,
            t1=min(t2 + 2.0, 10.0),
            t2=t2,
            status=self._status_from_score(t2),
            evidence=evidence, gaps=gaps,
        )

    def _score_d8_3(self, ctrl: ControlDefinition, stats: dict, findings: list) -> ControlScore:
        """D8.3: Vendor Trust and Assessment."""
        evidence = []
        gaps = []
        t2 = 0.0

        license_files = stats.get("license_files", [])
        if license_files:
            t2 += 2.0
            evidence.append(self._ev(f"License files present ({len(license_files)})"))

        dep_scanning = stats.get("dependency_scanning", 0)
        if dep_scanning > 0:
            t2 += 2.0
            evidence.append(self._ev("Dependency scanning indicates vendor monitoring"))

        # Signed commits suggest code provenance awareness
        signed = stats.get("signed_commits", 0)
        if signed > 0:
            t2 += 1.5
            evidence.append(self._ev(f"Signed commit patterns detected ({signed})"))

        if t2 < 3.0:
            gaps.append("No formal vendor assessment process detected")

        t2 = min(t2, 10.0)
        return self._make_control_score(
            ctrl.control_id, ctrl.name,
            t1=min(t2 + 2.0, 10.0), t2=t2,
            status=self._status_from_score(t2),
            evidence=evidence, gaps=gaps,
        )

    def _score_d8_4(self, ctrl: ControlDefinition, stats: dict, findings: list,
                     ioc_findings: list) -> ControlScore:
        """D8.4: Third-Party Code Security — signing, attestation, IOC checks."""
        evidence = []
        gaps = []
        t2 = 0.0

        signing = stats.get("container_signing", 0)
        if signing > 0:
            t2 += 3.0
            evidence.append(self._ev(
                f"Container signing/attestation patterns ({signing} references)",
            ))
        else:
            gaps.append("No container image signing detected (cosign/notation/sigstore)")

        repro = stats.get("reproducible_builds", 0)
        if repro > 0:
            t2 += 2.0
            evidence.append(self._ev(f"Reproducible build patterns ({repro})"))

        # IOC check — compromised versions are a severe penalty
        compromised = sum(
            1 for f in ioc_findings
            if f.category == "compromised_version"
        )
        if compromised > 0:
            t2 = max(t2 - 5.0, 0.0)
            evidence.append(self._ev(
                f"CRITICAL: {compromised} known compromised package version(s) detected!",
            ))
            gaps.append(f"{compromised} known compromised package version(s) in dependency files")

        t2 = min(t2, 10.0)
        return self._make_control_score(
            ctrl.control_id, ctrl.name,
            t1=min(t2 + 2.0, 10.0), t2=t2,
            status=self._status_from_score(t2),
            evidence=evidence, gaps=gaps,
        )

    def _score_d8_5(self, ctrl: ControlDefinition, stats: dict, findings: list) -> ControlScore:
        """D8.5: Ecosystem Resilience — offline builds, caching, vendoring."""
        evidence = []
        gaps = []
        t2 = 0.0

        lock_files = stats.get("lock_files", [])
        if lock_files:
            t2 += 2.0
            evidence.append(self._ev("Lock files enable reproducible builds"))

        repro = stats.get("reproducible_builds", 0)
        if repro > 0:
            t2 += 2.0
            evidence.append(self._ev("Reproducible build infrastructure detected"))

        hash_pins = stats.get("hash_pins", 0)
        if hash_pins > 0:
            t2 += 2.0
            evidence.append(self._ev("Hash-pinned dependencies enable offline verification"))
        else:
            gaps.append("No hash-pinned dependencies — offline rebuild may fail")

        if t2 < 3.0:
            gaps.append("No package caching, mirroring, or vendoring detected")

        t2 = min(t2, 10.0)
        return self._make_control_score(
            ctrl.control_id, ctrl.name,
            t1=min(t2 + 2.0, 10.0), t2=t2,
            status=self._status_from_score(t2),
            evidence=evidence, gaps=gaps,
        )

    def _score_d8_6(self, ctrl: ControlDefinition, stats: dict, findings: list) -> ControlScore:
        """D8.6: CI/CD Pipeline Security — action pinning, pull_request_target."""
        evidence = []
        gaps = []
        t2 = 0.0

        sha_pinned = stats.get("actions_sha_pinned", 0)
        float_tagged = stats.get("actions_float_tagged", 0)
        action_ratio = stats.get("action_pin_ratio", 0.0)
        prt = stats.get("pull_request_target", 0)

        # Action pinning
        total_actions = sha_pinned + float_tagged
        if total_actions > 0:
            if action_ratio >= 0.95:
                t2 += 5.0
                evidence.append(self._ev(
                    f"Excellent: {sha_pinned}/{total_actions} actions SHA-pinned "
                    f"({action_ratio:.0%})",
                ))
            elif action_ratio >= 0.5:
                t2 += 2.5
                evidence.append(self._ev(
                    f"Partial: {sha_pinned}/{total_actions} actions SHA-pinned "
                    f"({action_ratio:.0%})",
                ))
                gaps.append(
                    f"{float_tagged} GitHub Actions use floating tags "
                    f"(vulnerable to tag-rewriting attacks like Trivy/LiteLLM)"
                )
            else:
                t2 += 0.5
                gaps.append(
                    f"Most actions use floating tags ({float_tagged}/{total_actions}). "
                    f"Pin to commit SHAs to prevent supply chain attacks."
                )
        elif stats.get("cicd_pipelines"):
            # Has CI/CD but no GitHub Actions (might use GitLab, Jenkins, etc.)
            t2 += 1.0
            evidence.append(self._ev("CI/CD detected but not GitHub Actions — manual review needed"))

        # pull_request_target
        if prt > 0:
            t2 = max(t2 - 3.0, 0.0)
            evidence.append(self._ev(
                f"DANGER: {prt} pull_request_target trigger(s) — can expose secrets to fork PRs",
            ))
            gaps.append(
                "pull_request_target workflow trigger detected. "
                "This is the vector that compromised Trivy → LiteLLM."
            )
        elif total_actions > 0:
            t2 += 1.5
            evidence.append(self._ev("No pull_request_target triggers found"))

        # Dependency update automation
        dep_scanning = stats.get("dependency_scanning", 0)
        if dep_scanning > 0 and total_actions > 0:
            t2 += 1.5
            evidence.append(self._ev("Dependency scanning in CI/CD context"))

        t2 = min(t2, 10.0)
        return self._make_control_score(
            ctrl.control_id, ctrl.name,
            t1=min(t2 + 2.0, 10.0), t2=t2,
            status=self._status_from_score(t2),
            evidence=evidence, gaps=gaps,
        )

    def _score_d8_7(self, ctrl: ControlDefinition, stats: dict, findings: list,
                     ioc_findings: list) -> ControlScore:
        """D8.7: Runtime Package Integrity — .pth, --require-hashes, read-only fs."""
        evidence = []
        gaps = []
        t2 = 0.0

        # --require-hashes
        require_hashes = stats.get("require_hashes_count", 0)
        if require_hashes > 0:
            t2 += 3.0
            evidence.append(self._ev(
                f"--require-hashes found in {require_hashes} location(s)",
            ))
        else:
            gaps.append("No --require-hashes flag in any pip install command")

        # Bare pip install (penalty)
        bare_pip = stats.get("bare_pip_install_count", 0)
        if bare_pip > 0:
            t2 = max(t2 - 1.5, 0.0)
            evidence.append(self._ev(
                f"{bare_pip} bare pip install command(s) without version constraint",
            ))
            gaps.append(
                f"{bare_pip} pip install commands without version constraints "
                f"(allows installation of compromised future versions)"
            )

        # .pth files
        pth_found = stats.get("pth_files_found", 0)
        pth_ioc = sum(1 for f in ioc_findings if f.category == "pth_file")
        if pth_found == 0 and pth_ioc == 0:
            t2 += 2.0
            evidence.append(self._ev("No .pth files detected"))
        else:
            t2 = max(t2 - 2.0, 0.0)
            gaps.append(f"{pth_found + pth_ioc} .pth file(s) detected — import-time execution risk")

        # Read-only filesystem
        ro_fs = stats.get("read_only_fs", 0)
        if ro_fs > 0:
            t2 += 2.0
            evidence.append(self._ev(
                f"Read-only filesystem enforced ({ro_fs} container(s))",
            ))
        else:
            gaps.append("No read-only filesystem in container configs")

        # Seccomp
        seccomp = stats.get("seccomp_profiles", 0)
        if seccomp > 0:
            t2 += 1.0
            evidence.append(self._ev(f"Seccomp profiles detected ({seccomp})"))

        t2 = min(t2, 10.0)
        return self._make_control_score(
            ctrl.control_id, ctrl.name,
            t1=min(t2 + 2.0, 10.0), t2=t2,
            status=self._status_from_score(t2),
            evidence=evidence, gaps=gaps,
        )

    def _score_d8_8(self, ctrl: ControlDefinition, stats: dict, findings: list) -> ControlScore:
        """D8.8: Network Egress Policy."""
        evidence = []
        gaps = []
        t2 = 0.0

        egress = stats.get("network_egress_policies", 0)
        if egress > 0:
            t2 += 5.0
            evidence.append(self._ev(
                f"Network egress policy patterns detected ({egress} references)",
            ))
        else:
            gaps.append(
                "No network egress policies detected. Containers have unrestricted "
                "outbound access, enabling C2 callbacks from compromised dependencies."
            )

        # Docker socket is a counter-indicator (enables bypassing network policies)
        docker_sock = stats.get("docker_socket_mounts", 0)
        if docker_sock > 0:
            t2 = max(t2 - 2.0, 0.0)
            evidence.append(self._ev(
                f"Docker socket mounted in {docker_sock} container(s) — "
                f"can bypass network policies via new container creation",
            ))
            gaps.append("Docker socket mount undermines network egress restrictions")

        # Privileged containers
        priv = stats.get("privileged_containers", 0)
        if priv > 0:
            t2 = max(t2 - 1.5, 0.0)
            gaps.append(f"{priv} privileged container(s) — can bypass network restrictions")

        t2 = min(t2, 10.0)
        return self._make_control_score(
            ctrl.control_id, ctrl.name,
            t1=min(t2 + 2.0, 10.0), t2=t2,
            status=self._status_from_score(t2),
            evidence=evidence, gaps=gaps,
        )

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _status_from_score(t2: float) -> ControlStatus:
        """Map a T2 score to a STIG-style status."""
        if t2 >= 7.0:
            return ControlStatus.NOT_A_FINDING
        elif t2 >= 3.0:
            return ControlStatus.PARTIALLY_IMPLEMENTED
        elif t2 > 0.0:
            return ControlStatus.OPEN
        else:
            return ControlStatus.NOT_REVIEWED

    @staticmethod
    def _ev(description: str) -> ControlEvidence:
        """Shorthand to create a T2 scanner evidence item."""
        return ControlEvidence(
            tier=EvidenceTier.T2_IMPLEMENTATION,
            source=EvidenceSource.SCANNER,
            source_tool="scanner:supply_chain",
            description=description,
            confidence=0.85,
        )
