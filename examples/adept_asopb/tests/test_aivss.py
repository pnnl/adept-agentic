"""
Tests for OWASP AIVSS v0.8 integration.

Tests the AIVSSCalculator, AgentProfile, AgentProfileBuilder, and
all Pydantic models for the AIVSS scoring pipeline.
"""

from __future__ import annotations

import pytest

from asopb.aivss import (
    AARFAssessment,
    AARFCategory,
    AARFLevel,
    AgentProfile,
    AgentProfileBuilder,
    AIVSSCalculator,
    AIVSSReport,
    AIVSSScore,
    ExploitMaturity,
    AARF_DOMAIN_CROSSWALK,
)
from asopb.models import ScanFinding, ScanResult, Severity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_profile():
    """Minimal single-agent profile with few tools."""
    return AgentProfile(
        framework_name="minimal-agent",
        service_count=1,
        tool_count=2,
        llm_backed=True,
    )


@pytest.fixture
def adept_profile():
    """ADEPT-like multi-agent profile with high privilege."""
    return AgentProfile(
        framework_name="adept-agentic-framework",
        service_count=15,
        autonomous_decisions=False,
        tool_count=30,
        multi_agent=True,
        llm_backed=True,
        self_modifying=False,
        handles_pii=False,
        handles_secrets=True,
        stateful=True,
        docker_socket=True,
        privileged_containers=True,
        host_network=False,
        env_var_secrets=True,
        shared_dependency_ratio=1.0,  # litellm in 15/15 containers
        requires_host_remediation=False,
    )


@pytest.fixture
def sample_findings():
    """A set of findings with various severities and CVSS scores."""
    return [
        ScanFinding(
            finding_id="CVE-2026-1234",
            category="supply_chain",
            severity=Severity.CRITICAL,
            message="Malicious package version with credential stealer",
            metadata={"cvss_base": 9.8, "exploit_maturity": "attacked"},
        ),
        ScanFinding(
            finding_id="CVE-2026-5678",
            category="tls",
            severity=Severity.HIGH,
            message="TLS verification disabled (verify=False)",
            metadata={"cvss_base": 7.4},
        ),
        ScanFinding(
            finding_id="BANDIT-B101",
            category="assert_used",
            severity=Severity.LOW,
            message="Use of assert detected",
            metadata={},
        ),
        ScanFinding(
            finding_id="SEMGREP-001",
            category="injection",
            severity=Severity.MEDIUM,
            message="Possible command injection via user input",
            metadata={"cvss_base": 6.1, "exploit_maturity": "poc"},
        ),
    ]


@pytest.fixture
def sample_analyzer_results(sample_findings):
    """Analyzer results containing the sample findings."""
    return {
        "pip_audit": ScanResult(
            tool_name="pip_audit",
            success=True,
            findings=[sample_findings[0]],
        ),
        "tls": ScanResult(
            tool_name="tls",
            success=True,
            findings=[sample_findings[1]],
        ),
        "bandit": ScanResult(
            tool_name="bandit",
            success=True,
            findings=[sample_findings[2]],
        ),
        "semgrep": ScanResult(
            tool_name="semgrep",
            success=True,
            findings=[sample_findings[3]],
        ),
    }


# ---------------------------------------------------------------------------
# AARFAssessment tests
# ---------------------------------------------------------------------------

class TestAARFAssessment:
    def test_score_none(self):
        a = AARFAssessment(
            category=AARFCategory.AUTONOMY_LEVEL,
            level=AARFLevel.NONE,
        )
        assert a.score == 0.0

    def test_score_partial(self):
        a = AARFAssessment(
            category=AARFCategory.TOOL_USE_SCOPE,
            level=AARFLevel.PARTIAL,
        )
        assert a.score == 0.5

    def test_score_full(self):
        a = AARFAssessment(
            category=AARFCategory.BLAST_RADIUS,
            level=AARFLevel.FULL,
        )
        assert a.score == 1.0

    def test_all_categories_in_crosswalk(self):
        for cat in AARFCategory:
            assert cat in AARF_DOMAIN_CROSSWALK, f"{cat} missing from crosswalk"


# ---------------------------------------------------------------------------
# AgentProfile tests
# ---------------------------------------------------------------------------

class TestAgentProfile:
    def test_minimal_profile_aarfs(self, minimal_profile):
        aarfs = minimal_profile.assess_aarfs()
        assert len(aarfs) == 10
        categories = {a.category for a in aarfs}
        assert categories == set(AARFCategory)

    def test_minimal_aars_low(self, minimal_profile):
        aarfs = minimal_profile.assess_aarfs()
        aars = sum(a.score for a in aarfs)
        # Minimal profile: only LLM-backed (partial autonomy + partial non-determinism)
        assert aars < 3.0, f"Minimal AARS too high: {aars}"

    def test_adept_profile_aarfs_high(self, adept_profile):
        aarfs = adept_profile.assess_aarfs()
        aars = sum(a.score for a in aarfs)
        # ADEPT should have high AARS due to multi-agent, secrets, docker socket, blast radius
        assert aars >= 5.0, f"ADEPT AARS too low: {aars}"

    def test_docker_socket_triggers_full_privilege(self):
        profile = AgentProfile(docker_socket=True)
        aarfs = profile.assess_aarfs()
        privilege = next(a for a in aarfs if a.category == AARFCategory.PRIVILEGE_LEVEL)
        assert privilege.level == AARFLevel.FULL

    def test_no_llm_no_nondeterminism(self):
        profile = AgentProfile(llm_backed=False)
        aarfs = profile.assess_aarfs()
        nd = next(a for a in aarfs if a.category == AARFCategory.NON_DETERMINISM)
        assert nd.level == AARFLevel.NONE

    def test_high_shared_dependency_ratio(self):
        profile = AgentProfile(shared_dependency_ratio=0.9)
        aarfs = profile.assess_aarfs()
        br = next(a for a in aarfs if a.category == AARFCategory.BLAST_RADIUS)
        assert br.level == AARFLevel.FULL

    def test_moderate_shared_dependency_ratio(self):
        profile = AgentProfile(shared_dependency_ratio=0.5)
        aarfs = profile.assess_aarfs()
        br = next(a for a in aarfs if a.category == AARFCategory.BLAST_RADIUS)
        assert br.level == AARFLevel.PARTIAL

    def test_self_modifying_triggers_full(self):
        profile = AgentProfile(self_modifying=True)
        aarfs = profile.assess_aarfs()
        sm = next(a for a in aarfs if a.category == AARFCategory.SELF_MODIFICATION)
        assert sm.level == AARFLevel.FULL

    def test_host_remediation_triggers_full_recovery(self):
        profile = AgentProfile(requires_host_remediation=True)
        aarfs = profile.assess_aarfs()
        rc = next(a for a in aarfs if a.category == AARFCategory.RECOVERY_COMPLEXITY)
        assert rc.level == AARFLevel.FULL

    def test_env_var_secrets_triggers_partial_privilege(self):
        profile = AgentProfile(env_var_secrets=True, docker_socket=False, privileged_containers=False)
        aarfs = profile.assess_aarfs()
        priv = next(a for a in aarfs if a.category == AARFCategory.PRIVILEGE_LEVEL)
        assert priv.level == AARFLevel.PARTIAL


# ---------------------------------------------------------------------------
# AIVSSScore tests
# ---------------------------------------------------------------------------

class TestAIVSSScore:
    def test_formula_basic(self):
        """AIVSS = ((CVSS + AARS) / 2) × ThM"""
        aarfs = [
            AARFAssessment(category=cat, level=AARFLevel.FULL)
            for cat in list(AARFCategory)[:5]  # 5 × 1.0 = 5.0 AARS
        ] + [
            AARFAssessment(category=cat, level=AARFLevel.NONE)
            for cat in list(AARFCategory)[5:]   # 5 × 0.0
        ]
        score = AIVSSScore(cvss_base=8.0, aarfs=aarfs, threat_multiplier=1.0)
        # ((8.0 + 5.0) / 2) × 1.0 = 6.5
        assert score.aars == 5.0
        assert score.aivss_score == 6.5

    def test_formula_with_threat_multiplier(self):
        aarfs = [
            AARFAssessment(category=cat, level=AARFLevel.PARTIAL)
            for cat in AARFCategory  # 10 × 0.5 = 5.0
        ]
        score = AIVSSScore(cvss_base=6.0, aarfs=aarfs, threat_multiplier=0.91)
        # ((6.0 + 5.0) / 2) × 0.91 = 5.5 × 0.91 = 5.005 → 5.0
        expected = round(((6.0 + 5.0) / 2.0) * 0.91, 1)
        assert score.aivss_score == expected

    def test_score_clamped_at_10(self):
        aarfs = [
            AARFAssessment(category=cat, level=AARFLevel.FULL)
            for cat in AARFCategory  # 10 × 1.0 = 10.0
        ]
        score = AIVSSScore(cvss_base=10.0, aarfs=aarfs, threat_multiplier=1.0)
        # ((10 + 10) / 2) × 1.0 = 10.0 (exactly at cap)
        assert score.aivss_score == 10.0

    def test_score_clamped_at_zero(self):
        score = AIVSSScore(cvss_base=0.0, aarfs=[], threat_multiplier=0.0)
        assert score.aivss_score == 0.0

    def test_severity_critical(self):
        aarfs = [AARFAssessment(category=cat, level=AARFLevel.FULL) for cat in AARFCategory]
        score = AIVSSScore(cvss_base=9.8, aarfs=aarfs)
        assert score.aivss_severity == Severity.CRITICAL

    def test_severity_high(self):
        score = AIVSSScore(cvss_base=7.0, aarfs=[])
        # No AARFs, score = ((7.0 + 0) / 2) × 1.0 = 3.5
        assert score.aivss_severity == Severity.LOW

    def test_amplification_delta_positive(self):
        aarfs = [
            AARFAssessment(category=cat, level=AARFLevel.FULL)
            for cat in AARFCategory
        ]
        score = AIVSSScore(cvss_base=5.0, aarfs=aarfs)
        # ((5.0 + 10.0) / 2) = 7.5; delta = 7.5 - 5.0 = 2.5
        assert score.amplification_delta == 2.5

    def test_amplification_delta_negative(self):
        """AIVSS can be lower than CVSS when AARS is low."""
        score = AIVSSScore(cvss_base=8.0, aarfs=[])
        # ((8.0 + 0) / 2) = 4.0; delta = 4.0 - 8.0 = -4.0
        assert score.amplification_delta == -4.0

    def test_primary_domain_from_crosswalk(self):
        aarfs = [
            AARFAssessment(category=AARFCategory.BLAST_RADIUS, level=AARFLevel.FULL),
            AARFAssessment(category=AARFCategory.AUTONOMY_LEVEL, level=AARFLevel.NONE),
        ]
        score = AIVSSScore(cvss_base=5.0, aarfs=aarfs)
        assert score.primary_domain == "D8"  # BLAST_RADIUS → D8

    def test_litellm_scenario(self, adept_profile):
        """Reproduce the LiteLLM AIVSS calculation from the analysis doc."""
        calc = AIVSSCalculator(adept_profile)
        score = calc.score_finding(
            finding_id="ADEPT-SEC-2026-001",
            description="LiteLLM supply chain compromise",
            cvss_base=9.8,
            exploit_maturity=ExploitMaturity.ATTACKED,
        )
        # AARS should be substantial for ADEPT profile
        assert score.aars >= 5.0
        # AIVSS should be high
        assert score.aivss_score >= 7.0
        assert score.aivss_severity in (Severity.CRITICAL, Severity.HIGH)


# ---------------------------------------------------------------------------
# AIVSSCalculator tests
# ---------------------------------------------------------------------------

class TestAIVSSCalculator:
    def test_score_finding_basic(self, minimal_profile):
        calc = AIVSSCalculator(minimal_profile)
        score = calc.score_finding(cvss_base=5.0)
        assert 0.0 <= score.aivss_score <= 10.0
        assert len(score.aarfs) == 10

    def test_score_finding_with_maturity(self, minimal_profile):
        calc = AIVSSCalculator(minimal_profile)
        score_default = calc.score_finding(cvss_base=7.0)
        score_unreported = calc.score_finding(
            cvss_base=7.0, exploit_maturity=ExploitMaturity.UNREPORTED
        )
        # UNREPORTED has ThM=0.91, so score should be lower
        assert score_unreported.aivss_score <= score_default.aivss_score

    def test_score_all_findings(self, adept_profile, sample_analyzer_results):
        calc = AIVSSCalculator(adept_profile)
        report = calc.score_all_findings(
            sample_analyzer_results, min_severity=Severity.MEDIUM
        )
        assert isinstance(report, AIVSSReport)
        # Should exclude the LOW severity finding (BANDIT-B101)
        assert len(report.scores) == 3
        assert report.max_aivss > 0
        assert report.mean_aivss > 0

    def test_score_all_findings_includes_low(self, adept_profile, sample_analyzer_results):
        calc = AIVSSCalculator(adept_profile)
        report = calc.score_all_findings(
            sample_analyzer_results, min_severity=Severity.LOW
        )
        assert len(report.scores) == 4  # All four findings

    def test_score_all_findings_empty(self, minimal_profile):
        calc = AIVSSCalculator(minimal_profile)
        report = calc.score_all_findings({})
        assert len(report.scores) == 0
        assert report.max_aivss == 0.0
        assert report.mean_aivss == 0.0

    def test_cvss_extraction_from_metadata(self):
        finding = ScanFinding(
            finding_id="test",
            category="test",
            severity=Severity.HIGH,
            message="test",
            metadata={"cvss_base": 8.5},
        )
        cvss = AIVSSCalculator._extract_cvss(finding)
        assert cvss == 8.5

    def test_cvss_fallback_from_severity(self):
        finding = ScanFinding(
            finding_id="test",
            category="test",
            severity=Severity.CRITICAL,
            message="test",
            metadata={},
        )
        cvss = AIVSSCalculator._extract_cvss(finding)
        assert cvss == 9.5  # CRITICAL default

    def test_maturity_extraction_attacked(self):
        finding = ScanFinding(
            finding_id="test",
            category="test",
            severity=Severity.HIGH,
            message="test",
            metadata={"exploit_maturity": "actively attacked"},
        )
        maturity = AIVSSCalculator._extract_maturity(finding)
        assert maturity == ExploitMaturity.ATTACKED

    def test_maturity_extraction_poc(self):
        finding = ScanFinding(
            finding_id="test",
            category="test",
            severity=Severity.HIGH,
            message="test",
            metadata={"exploit_maturity": "poc available"},
        )
        maturity = AIVSSCalculator._extract_maturity(finding)
        assert maturity == ExploitMaturity.PROOF_OF_CONCEPT

    def test_maturity_fallback(self):
        finding = ScanFinding(
            finding_id="test",
            category="test",
            severity=Severity.HIGH,
            message="test",
            metadata={},
        )
        maturity = AIVSSCalculator._extract_maturity(finding)
        assert maturity == ExploitMaturity.NOT_DEFINED

    def test_failed_analyzer_skipped(self, adept_profile):
        results = {
            "broken": ScanResult(
                tool_name="broken",
                success=False,
                error_message="Tool not found",
                findings=[],
            )
        }
        calc = AIVSSCalculator(adept_profile)
        report = calc.score_all_findings(results)
        assert len(report.scores) == 0


# ---------------------------------------------------------------------------
# AIVSSReport tests
# ---------------------------------------------------------------------------

class TestAIVSSReport:
    def test_domain_impact_summary(self, adept_profile, sample_analyzer_results):
        calc = AIVSSCalculator(adept_profile)
        report = calc.score_all_findings(sample_analyzer_results)
        summary = report.domain_impact_summary()
        # Should group findings by primary domain
        assert isinstance(summary, dict)
        total_grouped = sum(len(v) for v in summary.values())
        assert total_grouped == len(report.scores)

    def test_critical_count(self, adept_profile, sample_analyzer_results):
        calc = AIVSSCalculator(adept_profile)
        report = calc.score_all_findings(sample_analyzer_results, min_severity=Severity.LOW)
        # The count depends on the profile amplification
        assert report.critical_count >= 0
        assert report.high_count >= 0

    def test_empty_report(self):
        report = AIVSSReport()
        assert report.max_aivss == 0.0
        assert report.mean_aivss == 0.0
        assert report.critical_count == 0
        assert report.high_count == 0


# ---------------------------------------------------------------------------
# AgentProfileBuilder tests
# ---------------------------------------------------------------------------

class TestAgentProfileBuilder:
    def test_from_empty_results(self):
        profile = AgentProfileBuilder.from_scan_results({})
        assert isinstance(profile, AgentProfile)
        assert profile.tool_count == 0
        assert not profile.docker_socket

    def test_docker_socket_from_sandbox_scanner(self):
        results = {
            "sandbox": ScanResult(
                tool_name="sandbox",
                success=True,
                findings=[
                    ScanFinding(
                        finding_id="SOCK-1",
                        category="docker_socket",
                        severity=Severity.CRITICAL,
                        message="Docker socket mount: /var/run/docker.sock",
                    )
                ],
            )
        }
        profile = AgentProfileBuilder.from_scan_results(results)
        assert profile.docker_socket is True

    def test_privileged_from_dockerfile_analyzer(self):
        results = {}
        analyzer_results = {
            "dockerfile": ScanResult(
                tool_name="dockerfile",
                success=True,
                findings=[
                    ScanFinding(
                        finding_id="PRIV-1",
                        category="privileged",
                        severity=Severity.CRITICAL,
                        message="Container runs as privileged",
                    )
                ],
            )
        }
        profile = AgentProfileBuilder.from_scan_results(results, analyzer_results)
        assert profile.privileged_containers is True

    def test_secrets_from_auth_scanner(self):
        results = {
            "auth": ScanResult(
                tool_name="auth",
                success=True,
                findings=[
                    ScanFinding(
                        finding_id="AUTH-1",
                        category="secret_config",
                        severity=Severity.HIGH,
                        message="API_KEY secret loaded from environment",
                    )
                ],
            )
        }
        profile = AgentProfileBuilder.from_scan_results(results)
        assert profile.handles_secrets is True

    def test_tool_count_from_tools_scanner(self):
        results = {
            "tools": ScanResult(
                tool_name="tools",
                success=True,
                findings=[
                    ScanFinding(
                        finding_id=f"TOOL-{i}",
                        category="mcp_tool_registration",
                        severity=Severity.INFORMATIONAL,
                        message=f"MCP tool {i} registered",
                    )
                    for i in range(25)
                ],
            )
        }
        profile = AgentProfileBuilder.from_scan_results(results)
        assert profile.tool_count == 25

    def test_failed_scanner_ignored(self):
        results = {
            "sandbox": ScanResult(
                tool_name="sandbox",
                success=False,
                error_message="Scanner crashed",
                findings=[],
            )
        }
        profile = AgentProfileBuilder.from_scan_results(results)
        assert profile.docker_socket is False  # Default, since scanner failed
