"""
Unit tests for ASOPB configuration and pipeline scoring mode.

Tests:
- ScannerConfig.effective_scanners() filtering logic
- ScoringConfig.scoring_mode field
- PipelineScorer.score_domain() penalty calculation
- PipelineScorer.calculate_aspi() composite formula
- PipelineScorer with no findings (targets 100.0)
- PipelineScorer with critical findings (significant penalty)
- PipelineScorer D5/D7/D8 weight distribution
"""

import math

import pytest

from asopb.config import (
    AnalyzerConfig,
    EvalConfig,
    ScannerConfig,
    ScoringConfig,
)
from asopb.models import (
    Applicability,
    ControlScore,
    ControlStatus,
    DomainResult,
    EvaluationReport,
    FrameworkVersion,
    ScanFinding,
    ScanResult,
    Severity,
)
from asopb.scoring import ASPICalculator, PipelineScorer


# ---------------------------------------------------------------------------
# ScannerConfig Tests
# ---------------------------------------------------------------------------


class TestScannerConfig:
    """Tests for ScannerConfig filtering logic."""

    def test_effective_scanners_no_filter(self):
        config = ScannerConfig()
        available = ["auth", "crypto", "deps", "federation", "itot"]
        result = config.effective_scanners(available)
        assert result == available

    def test_effective_scanners_enabled_whitelist(self):
        config = ScannerConfig(enabled=["auth", "federation"])
        available = ["auth", "crypto", "deps", "federation", "itot"]
        result = config.effective_scanners(available)
        assert result == ["auth", "federation"]

    def test_effective_scanners_enabled_nonexistent_filtered(self):
        config = ScannerConfig(enabled=["auth", "nonexistent"])
        available = ["auth", "crypto", "deps"]
        result = config.effective_scanners(available)
        assert result == ["auth"]

    def test_effective_scanners_disabled_blacklist(self):
        config = ScannerConfig(disabled=["crypto", "deps"])
        available = ["auth", "crypto", "deps", "federation"]
        result = config.effective_scanners(available)
        assert result == ["auth", "federation"]

    def test_effective_scanners_enabled_and_disabled(self):
        config = ScannerConfig(enabled=["auth", "crypto", "deps"], disabled=["crypto"])
        available = ["auth", "crypto", "deps", "federation"]
        result = config.effective_scanners(available)
        assert result == ["auth", "deps"]

    def test_effective_scanners_empty_available(self):
        config = ScannerConfig(enabled=["auth"])
        result = config.effective_scanners([])
        assert result == []

    def test_effective_scanners_all_disabled(self):
        config = ScannerConfig(disabled=["auth", "crypto", "deps"])
        available = ["auth", "crypto", "deps"]
        result = config.effective_scanners(available)
        assert result == []


# ---------------------------------------------------------------------------
# ScoringConfig Tests
# ---------------------------------------------------------------------------


class TestScoringConfig:
    """Tests for ScoringConfig fields and defaults."""

    def test_default_scoring_mode(self):
        config = ScoringConfig()
        assert config.scoring_mode == "composite"

    def test_pipeline_scoring_mode(self):
        config = ScoringConfig(scoring_mode="pipeline")
        assert config.scoring_mode == "pipeline"

    def test_default_domain_weights(self):
        config = ScoringConfig()
        assert config.domain_weights["D1"] == 1.5
        assert config.domain_weights["D5"] == 1.0
        assert config.domain_weights["D7"] == 1.5

    def test_custom_domain_weights(self):
        config = ScoringConfig(domain_weights={"D1": 2.0, "D2": 0.5})
        assert config.domain_weights["D1"] == 2.0
        assert config.domain_weights["D2"] == 0.5

    def test_eval_config_contains_scanner_config(self):
        config = EvalConfig()
        assert isinstance(config.scanners, ScannerConfig)
        assert config.scanners.enabled == []
        assert config.scanners.disabled == []

    def test_eval_config_scoring_mode_propagation(self):
        config = EvalConfig()
        config.scoring.scoring_mode = "pipeline"
        assert config.scoring.scoring_mode == "pipeline"


# ---------------------------------------------------------------------------
# PipelineScorer Tests
# ---------------------------------------------------------------------------


class TestPipelineScorer:
    """Tests for the pipeline penalty-based scoring model."""

    def _make_domain(
        self,
        domain_id: str,
        status: ControlStatus = ControlStatus.NOT_A_FINDING,
    ) -> DomainResult:
        """Helper to create a domain with a single control."""
        controls = [
            ControlScore(
                control_id=f"{domain_id}.1",
                control_name="Test Control",
                status=status,
                t1_score=3.0,
                t2_score=2.0,
                t3_score=0.0,
            )
        ]
        return DomainResult(
            domain_id=domain_id,
            domain_name=f"Domain {domain_id}",
            applicability=Applicability.APPLICABLE,
            weight=1.0,
            controls=controls,
        )

    def _make_scan_results(
        self,
        scanner_name: str,
        findings: list[tuple[str, Severity]],
    ) -> dict[str, ScanResult]:
        """Helper to create scan results with specified findings."""
        scan_findings = []
        for i, (category, severity) in enumerate(findings):
            scan_findings.append(
                ScanFinding(
                    finding_id=f"F-{i}",
                    category=category,
                    severity=severity,
                    message=f"Test finding {i} ({severity.value})",
                )
            )
        return {
            scanner_name: ScanResult(
                tool_name=scanner_name,
                success=True,
                findings=scan_findings,
            )
        }

    def test_log_penalty_zero_count(self):
        assert PipelineScorer._log_penalty(0, 40.0) == 0.0

    def test_log_penalty_one_critical(self):
        result = PipelineScorer._log_penalty(1, 40.0)
        expected = 40.0 * math.log(2)
        assert abs(result - expected) < 0.001

    def test_log_penalty_many_low(self):
        result = PipelineScorer._log_penalty(100, 1.5)
        expected = 1.5 * math.log(101)
        assert abs(result - expected) < 0.001

    def test_score_domain_no_findings(self):
        domain = self._make_domain("D5")
        scan_results = self._make_scan_results("federation", [])
        score = PipelineScorer.score_domain(domain, scan_results)
        assert score == 100.0

    def test_score_domain_one_critical(self):
        domain = self._make_domain("D5")
        scan_results = self._make_scan_results(
            "federation",
            [("verified_credential", Severity.CRITICAL)],
        )
        score = PipelineScorer.score_domain(domain, scan_results)
        expected = max(0.0, round(100.0 - 40.0 * math.log(2), 1))
        assert score == expected
        assert score < 75.0

    def test_score_domain_multiple_low(self):
        domain = self._make_domain("D8")
        findings = [("pattern_match", Severity.LOW)] * 10
        scan_results = self._make_scan_results("supply_chain", findings)
        score = PipelineScorer.score_domain(domain, scan_results)
        expected_penalty = 0.5 * math.log(11)  # D8 low weight is 0.5
        expected = max(0.0, round(100.0 - expected_penalty, 1))
        assert score == expected
        assert score > 95.0

    def test_score_domain_mixed_severities(self):
        domain = self._make_domain("D5")
        findings = [
            ("cred_verified", Severity.CRITICAL),
            ("internal_infra", Severity.HIGH),
            ("pii_match", Severity.MEDIUM),
            ("pattern", Severity.LOW),
        ]
        scan_results = self._make_scan_results("federation", findings)
        score = PipelineScorer.score_domain(domain, scan_results)
        assert 0.0 <= score <= 100.0
        assert score < 60.0

    def test_score_domain_fallback_to_status(self):
        """Without scan_results, uses control status as proxy."""
        domain = self._make_domain("D5", status=ControlStatus.OPEN)
        score = PipelineScorer.score_domain(domain, scan_results=None)
        # One OPEN control = one "high" penalty
        expected_penalty = 15.0 * math.log(2)  # D5 high weight
        expected = max(0.0, round(100.0 - expected_penalty, 1))
        assert score == expected

    def test_calculate_aspi_d5_d7_d8_no_findings(self):
        domains = {
            "D5": self._make_domain("D5"),
            "D7": self._make_domain("D7"),
            "D8": self._make_domain("D8"),
        }
        aspi = PipelineScorer.calculate_aspi(domains)
        assert aspi == 100.0

    def test_calculate_aspi_d5_d7_d8_with_scan_results(self):
        """Verify D5=0.4, D8=0.4, D7=0.2 weighting."""
        domains = {
            "D5": self._make_domain("D5"),
            "D7": self._make_domain("D7"),
            "D8": self._make_domain("D8"),
        }
        # D7 has a critical finding via itot scanner
        scan_results = self._make_scan_results(
            "itot", [("toxicity", Severity.CRITICAL)]
        )
        aspi = PipelineScorer.calculate_aspi(domains, scan_results)
        d7_score = PipelineScorer.score_domain(domains["D7"], scan_results)
        expected = round((0.4 * 100.0 + 0.4 * 100.0 + 0.2 * d7_score) / 1.0, 1)
        assert aspi == expected

    def test_calculate_aspi_empty_domains(self):
        aspi = PipelineScorer.calculate_aspi({})
        assert aspi == 0.0

    def test_calculate_aspi_all_not_applicable(self):
        domains = {
            "D5": DomainResult(
                domain_id="D5",
                domain_name="Federation",
                applicability=Applicability.NOT_APPLICABLE,
                controls=[],
            ),
        }
        aspi = PipelineScorer.calculate_aspi(domains)
        assert aspi == 0.0

    def test_calculate_aspi_mixed_pipeline_and_other(self):
        """When non-pipeline domains are present, they get weight=1.0."""
        domains = {
            "D5": self._make_domain("D5"),
            "D1": self._make_domain("D1"),
        }
        aspi = PipelineScorer.calculate_aspi(domains)
        # D5 weight=0.4, D1 weight=1.0, both score 100 (no scan_results)
        expected = round((0.4 * 100 + 1.0 * 100) / 1.4, 1)
        assert aspi == expected

    def test_score_report_structure(self):
        report = EvaluationReport(
            report_id="test-001",
            framework=FrameworkVersion(name="test", version="1.0"),
            domains={
                "D5": self._make_domain("D5"),
                "D7": self._make_domain("D7"),
                "D8": self._make_domain("D8"),
            },
        )
        result = PipelineScorer.score_report(report)
        assert result["scoring_mode"] == "pipeline"
        assert result["aspi"] == 100.0
        assert result["stage"] == "S4 (Hardened)"
        assert "D5" in result["domain_scores"]
        assert "D7" in result["domain_scores"]
        assert "D8" in result["domain_scores"]
        assert "formula" in result

    def test_pipeline_targets_90_with_only_low_findings(self):
        """Low-severity findings should not drop below 90 (release gate pass)."""
        domains = {
            "D5": self._make_domain("D5"),
            "D7": self._make_domain("D7"),
            "D8": self._make_domain("D8"),
        }
        findings = [("pattern", Severity.LOW)] * 5
        scan_results = self._make_scan_results("federation", findings)
        aspi = PipelineScorer.calculate_aspi(domains, scan_results)
        assert aspi >= 90.0, f"ASPI {aspi} should be >= 90 with only low findings"


# ---------------------------------------------------------------------------
# AnalyzerConfig Tests
# ---------------------------------------------------------------------------


class TestAnalyzerConfig:
    """Tests for AnalyzerConfig disabled/enabled filtering."""

    def test_default_analyzers(self):
        config = AnalyzerConfig()
        assert "semgrep" in config.enabled
        assert "tls" in config.enabled
        assert len(config.disabled) == 0

    def test_effective_analyzers_via_eval_config(self):
        config = EvalConfig()
        config.analyzers.disabled = ["tls"]
        effective = config.effective_analyzers()
        assert "tls" not in effective
        assert "semgrep" in effective

    def test_disable_all_analyzers(self):
        config = EvalConfig()
        config.analyzers.disabled = config.analyzers.enabled.copy()
        effective = config.effective_analyzers()
        assert effective == []
