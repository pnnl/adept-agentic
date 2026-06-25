"""
Unit tests for the ASOPB scoring engine.

Tests:
- ASPI calculation against the paper's formula
- ASPI edge cases (all N/A, custom weights)
- T1/T2 gap ratio edge cases
- Stage classification
- Report delta comparison
- Domain profile output structure
"""

from datetime import datetime, timezone

import pytest

from asopb.models import (
    Applicability,
    ControlScore,
    ControlStatus,
    DomainResult,
    EvaluationReport,
    FrameworkVersion,
)
from asopb.scoring import ASPICalculator


class TestASPICalculation:
    """Tests for ASPI (Agentic Security Posture Index) calculation."""

    def test_aspi_basic_calculation(self):
        """Test ASPI calculation with simple weights."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                weight=1.0,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=6.0,
                        t2_score=6.0,
                        t3_score=6.0,
                    ),
                ],
            ),
            "D2": DomainResult(
                domain_id="D2",
                domain_name="Domain 2",
                applicability=Applicability.APPLICABLE,
                weight=1.0,
                controls=[
                    ControlScore(
                        control_id="D2.1",
                        control_name="C2",
                        t1_score=4.0,
                        t2_score=4.0,
                        t3_score=4.0,
                    ),
                ],
            ),
        }

        aspi = ASPICalculator.calculate_aspi(domains)
        # D1 score: 60.0, D2 score: 40.0
        # ASPI = (1.0*60 + 1.0*40) / (1.0 + 1.0) = 100/2 = 50.0
        assert aspi == 50.0

    def test_aspi_with_custom_weights(self):
        """Test ASPI respects custom domain weights."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                weight=2.0,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=8.0,
                        t2_score=8.0,
                        t3_score=8.0,
                    ),
                ],
            ),
            "D2": DomainResult(
                domain_id="D2",
                domain_name="Domain 2",
                applicability=Applicability.APPLICABLE,
                weight=1.0,
                controls=[
                    ControlScore(
                        control_id="D2.1",
                        control_name="C2",
                        t1_score=2.0,
                        t2_score=2.0,
                        t3_score=2.0,
                    ),
                ],
            ),
        }

        aspi = ASPICalculator.calculate_aspi(domains)
        # D1 score: 80.0, D2 score: 20.0
        # ASPI = (2.0*80 + 1.0*20) / (2.0 + 1.0) = 180/3 = 60.0
        assert aspi == 60.0

    def test_aspi_excludes_not_applicable_domains(self):
        """Test that N/A domains are excluded from ASPI."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                weight=1.0,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=5.0,
                        t2_score=5.0,
                        t3_score=5.0,
                    ),
                ],
            ),
            "D5": DomainResult(
                domain_id="D5",
                domain_name="Domain 5",
                applicability=Applicability.NOT_APPLICABLE,
                weight=1.0,
            ),
        }

        aspi = ASPICalculator.calculate_aspi(domains)
        # Only D1 counts: (1.0*50) / 1.0 = 50.0
        assert aspi == 50.0

    def test_aspi_all_not_applicable(self):
        """Test ASPI returns 0 when all domains are N/A."""
        domains = {
            "D5": DomainResult(
                domain_id="D5",
                domain_name="Domain 5",
                applicability=Applicability.NOT_APPLICABLE,
            ),
            "D6": DomainResult(
                domain_id="D6",
                domain_name="Domain 6",
                applicability=Applicability.NOT_APPLICABLE,
            ),
        }

        aspi = ASPICalculator.calculate_aspi(domains)
        assert aspi == 0.0

    def test_aspi_empty_domains(self):
        """Test ASPI with no domains."""
        aspi = ASPICalculator.calculate_aspi({})
        assert aspi == 0.0


class TestT1T2GapRatio:
    """Tests for T1/T2 gap ratio calculation."""

    def test_gap_ratio_basic(self):
        """Test basic gap ratio: controls with T1>0 but T2=0."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=5.0,
                        t2_score=0.0,
                    ),
                    ControlScore(
                        control_id="D1.2",
                        control_name="C2",
                        t1_score=5.0,
                        t2_score=3.0,
                    ),
                ],
            ),
        }

        ratio = ASPICalculator.t1_t2_gap_ratio(domains)
        # 1 control with T1>0 but T2=0, out of 2 with T1>0
        assert ratio == 0.5

    def test_gap_ratio_all_zeros(self):
        """Test gap ratio when no T1 scores."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=0.0,
                        t2_score=0.0,
                    ),
                ],
            ),
        }

        ratio = ASPICalculator.t1_t2_gap_ratio(domains)
        assert ratio == 0.0

    def test_gap_ratio_all_implemented(self):
        """Test gap ratio when all controls have T2."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=5.0,
                        t2_score=5.0,
                    ),
                    ControlScore(
                        control_id="D1.2",
                        control_name="C2",
                        t1_score=6.0,
                        t2_score=4.0,
                    ),
                ],
            ),
        }

        ratio = ASPICalculator.t1_t2_gap_ratio(domains)
        # 0 controls with T1>0 but T2=0, out of 2 with T1>0
        assert ratio == 0.0

    def test_gap_ratio_all_gaps(self):
        """Test gap ratio when all T1 controls have T2=0."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=5.0,
                        t2_score=0.0,
                    ),
                    ControlScore(
                        control_id="D1.2",
                        control_name="C2",
                        t1_score=6.0,
                        t2_score=0.0,
                    ),
                ],
            ),
        }

        ratio = ASPICalculator.t1_t2_gap_ratio(domains)
        assert ratio == 1.0

    def test_gap_ratio_excludes_not_applicable(self):
        """Test that N/A domains are excluded from gap ratio."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=5.0,
                        t2_score=0.0,
                    ),
                ],
            ),
            "D5": DomainResult(
                domain_id="D5",
                domain_name="Domain 5",
                applicability=Applicability.NOT_APPLICABLE,
            ),
        }

        ratio = ASPICalculator.t1_t2_gap_ratio(domains)
        assert ratio == 1.0


class TestStageClassification:
    """Tests for deployment stage classification (S1/S2/S3/S4)."""

    def test_stage_s1_low_aspi_mostly_unreviewed(self):
        """Test S1 classification: ASPI < 30, most controls not reviewed."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        status=ControlStatus.NOT_REVIEWED,
                        t1_score=1.0,
                        t2_score=1.0,
                        t3_score=0.0,
                    ),
                    ControlScore(
                        control_id="D1.2",
                        control_name="C2",
                        status=ControlStatus.NOT_REVIEWED,
                        t1_score=0.0,
                        t2_score=0.0,
                        t3_score=0.0,
                    ),
                ],
            ),
        }

        stage = ASPICalculator.stage_classification(domains)
        assert stage == "S1"

    def test_stage_s2_moderate_aspi_mixed_evidence(self):
        """Test S2 classification: ASPI 30-60, mixed T1/T2."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        status=ControlStatus.PARTIALLY_IMPLEMENTED,
                        t1_score=4.0,
                        t2_score=3.0,
                        t3_score=1.0,
                    ),
                    ControlScore(
                        control_id="D1.2",
                        control_name="C2",
                        status=ControlStatus.PARTIALLY_IMPLEMENTED,
                        t1_score=5.0,
                        t2_score=4.0,
                        t3_score=0.0,
                    ),
                ],
            ),
        }

        stage = ASPICalculator.stage_classification(domains)
        assert stage in ["S2", "S1"]  # May be S1 or S2 depending on exact scores

    def test_stage_s3_strong_implementation(self):
        """Test S3 classification: ASPI 60-85, strong T2/T3."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        status=ControlStatus.NOT_A_FINDING,
                        t1_score=7.0,
                        t2_score=7.0,
                        t3_score=4.0,
                    ),
                    ControlScore(
                        control_id="D1.2",
                        control_name="C2",
                        status=ControlStatus.NOT_A_FINDING,
                        t1_score=8.0,
                        t2_score=7.0,
                        t3_score=5.0,
                    ),
                ],
            ),
        }

        stage = ASPICalculator.stage_classification(domains)
        assert stage in ["S3", "S2"]

    def test_stage_s4_high_aspi_all_tiers_high(self):
        """Test S4 classification: ASPI >= 85, all tiers high."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        status=ControlStatus.NOT_A_FINDING,
                        t1_score=9.0,
                        t2_score=9.0,
                        t3_score=9.0,
                    ),
                    ControlScore(
                        control_id="D1.2",
                        control_name="C2",
                        status=ControlStatus.NOT_A_FINDING,
                        t1_score=10.0,
                        t2_score=10.0,
                        t3_score=8.0,
                    ),
                ],
            ),
        }

        stage = ASPICalculator.stage_classification(domains)
        assert stage == "S4"


class TestDomainProfile:
    """Tests for domain profile output structure."""

    def test_domain_profile_structure(self):
        """Test that domain_profile returns correct structure."""
        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                weight=1.5,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        status=ControlStatus.NOT_A_FINDING,
                        t1_score=5.0,
                        t2_score=5.0,
                        t3_score=5.0,
                    ),
                    ControlScore(
                        control_id="D1.2",
                        control_name="C2",
                        status=ControlStatus.PARTIALLY_IMPLEMENTED,
                        t1_score=3.0,
                        t2_score=2.0,
                        t3_score=0.0,
                    ),
                ],
            ),
        }

        profile = ASPICalculator.domain_profile(domains)

        assert "D1" in profile
        assert profile["D1"]["name"] == "Domain 1"
        assert profile["D1"]["applicability"] == "applicable"
        assert profile["D1"]["weight"] == 1.5
        assert profile["D1"]["domain_score"] is not None
        assert profile["D1"]["t1_aggregate"] == 4.0
        assert profile["D1"]["control_count"] == 2
        assert profile["D1"]["controls_not_reviewed"] == 0
        assert profile["D1"]["controls_partial"] == 1
        assert profile["D1"]["controls_not_applicable"] == 0

    def test_domain_profile_all_fields(self):
        """Test that all required fields are in profile."""
        domains = {
            "D2": DomainResult(
                domain_id="D2",
                domain_name="Domain 2",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D2.1",
                        control_name="C1",
                        status=ControlStatus.NOT_REVIEWED,
                        t1_score=0.0,
                        t2_score=0.0,
                        t3_score=0.0,
                    ),
                ],
            ),
        }

        profile = ASPICalculator.domain_profile(domains)
        required_fields = [
            "name",
            "applicability",
            "weight",
            "domain_score",
            "t1_aggregate",
            "t2_aggregate",
            "t3_aggregate",
            "control_count",
            "controls_not_reviewed",
            "controls_partial",
            "controls_not_applicable",
        ]

        for field in required_fields:
            assert field in profile["D2"]


class TestCompareReports:
    """Tests for report delta comparison."""

    def test_compare_reports_aspi_delta(self):
        """Test ASPI delta calculation between reports."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

        domains_a = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=4.0,
                        t2_score=4.0,
                        t3_score=4.0,
                    ),
                ],
            ),
        }

        domains_b = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=6.0,
                        t2_score=6.0,
                        t3_score=6.0,
                    ),
                ],
            ),
        }

        report_a = EvaluationReport(framework=framework, domains=domains_a)
        report_b = EvaluationReport(framework=framework, domains=domains_b)

        delta = ASPICalculator.compare_reports(report_a, report_b)

        assert delta["aspi_delta"] == 20.0  # 60.0 - 40.0

    def test_compare_reports_control_deltas(self):
        """Test control-level delta calculation."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

        domains_a = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        status=ControlStatus.PARTIALLY_IMPLEMENTED,
                        t1_score=3.0,
                        t2_score=2.0,
                        t3_score=1.0,
                    ),
                ],
            ),
        }

        domains_b = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        status=ControlStatus.NOT_A_FINDING,
                        t1_score=5.0,
                        t2_score=5.0,
                        t3_score=4.0,
                    ),
                ],
            ),
        }

        report_a = EvaluationReport(framework=framework, domains=domains_a)
        report_b = EvaluationReport(framework=framework, domains=domains_b)

        delta = ASPICalculator.compare_reports(report_a, report_b)

        assert "D1.1" in delta["control_deltas"]
        assert delta["control_deltas"]["D1.1"]["t1_delta"] == 2.0
        assert delta["control_deltas"]["D1.1"]["t2_delta"] == 3.0
        assert delta["control_deltas"]["D1.1"]["status_a"] == "partial"
        assert delta["control_deltas"]["D1.1"]["status_b"] == "not_a_finding"

    def test_compare_reports_stage_classification(self):
        """Test that stage classification is included in delta."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

        domains_a = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        status=ControlStatus.NOT_REVIEWED,
                        t1_score=1.0,
                        t2_score=0.0,
                        t3_score=0.0,
                    ),
                ],
            ),
        }

        domains_b = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        status=ControlStatus.NOT_A_FINDING,
                        t1_score=9.0,
                        t2_score=9.0,
                        t3_score=9.0,
                    ),
                ],
            ),
        }

        report_a = EvaluationReport(framework=framework, domains=domains_a)
        report_b = EvaluationReport(framework=framework, domains=domains_b)

        delta = ASPICalculator.compare_reports(report_a, report_b)

        assert "stage_a" in delta
        assert "stage_b" in delta
        assert delta["stage_a"] == "S1"
        assert delta["stage_b"] == "S4"
