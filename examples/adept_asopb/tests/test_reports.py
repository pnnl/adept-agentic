"""
Unit tests for evaluation report generation and export.

Tests:
- Report JSON serialization
- Report evidence bundle creation
- Report integrity across serialization/deserialization
"""

import json
from pathlib import Path

import pytest

from asopb.models import (
    Applicability,
    ControlScore,
    ControlStatus,
    DomainResult,
    EvaluationReport,
    FrameworkVersion,
)


class TestReportSerialization:
    """Tests for report JSON serialization."""

    def test_report_to_json(self, sample_evaluation_report: EvaluationReport):
        """Test converting report to JSON."""
        json_str = sample_evaluation_report.model_dump_json(indent=2)

        assert isinstance(json_str, str)
        assert "aspi" in json_str
        assert sample_evaluation_report.framework.name in json_str

    def test_report_from_json(self, sample_evaluation_report: EvaluationReport):
        """Test loading report from JSON."""
        json_str = sample_evaluation_report.model_dump_json()

        loaded = EvaluationReport.model_validate_json(json_str)

        assert loaded.report_id == sample_evaluation_report.report_id
        assert loaded.framework.name == sample_evaluation_report.framework.name
        assert loaded.aspi == sample_evaluation_report.aspi

    def test_report_roundtrip_integrity(
        self, sample_evaluation_report: EvaluationReport
    ):
        """Test that report survives JSON roundtrip intact."""
        original_aspi = sample_evaluation_report.aspi
        original_domains = len(sample_evaluation_report.domains)

        json_str = sample_evaluation_report.model_dump_json()
        loaded = EvaluationReport.model_validate_json(json_str)

        assert loaded.aspi == original_aspi
        assert len(loaded.domains) == original_domains
        assert loaded.report_hash == sample_evaluation_report.report_hash


class TestReportExport:
    """Tests for exporting reports as evidence bundles."""

    def test_to_evidence_bundle(
        self, sample_evaluation_report: EvaluationReport, tmp_path: Path
    ):
        """Test exporting report to evidence bundle."""
        bundle_dir = sample_evaluation_report.to_evidence_bundle(tmp_path)

        assert bundle_dir.exists()
        assert (bundle_dir / "report.json").exists()
        assert (bundle_dir / "evidence").exists()
        assert (bundle_dir / "scans").exists()

    def test_evidence_bundle_report_file(
        self, sample_evaluation_report: EvaluationReport, tmp_path: Path
    ):
        """Test that bundle contains main report.json."""
        bundle_dir = sample_evaluation_report.to_evidence_bundle(tmp_path)

        report_file = bundle_dir / "report.json"
        assert report_file.exists()

        report_data = json.loads(report_file.read_text())
        assert report_data["report_id"] == sample_evaluation_report.report_id

    def test_evidence_bundle_domain_evidence(
        self, sample_evaluation_report: EvaluationReport, tmp_path: Path
    ):
        """Test that bundle contains per-domain evidence files."""
        bundle_dir = sample_evaluation_report.to_evidence_bundle(tmp_path)

        evidence_dir = bundle_dir / "evidence"
        assert evidence_dir.exists()

        # Should have files for applicable domains
        domain_files = list(evidence_dir.glob("*.json"))
        assert len(domain_files) > 0

    def test_evidence_bundle_structure(
        self, sample_evaluation_report: EvaluationReport, tmp_path: Path
    ):
        """Test complete bundle directory structure."""
        bundle_dir = sample_evaluation_report.to_evidence_bundle(tmp_path)

        # Check all expected directories exist
        assert (bundle_dir / "report.json").is_file()
        assert (bundle_dir / "evidence").is_dir()
        assert (bundle_dir / "scans").is_dir()

        # Main report should be loadable
        report_json = (bundle_dir / "report.json").read_text()
        report_data = json.loads(report_json)
        assert "report_id" in report_data
        assert "aspi" in report_data
        assert "domains" in report_data


class TestReportValidity:
    """Tests for report validity and constraint enforcement."""

    def test_aspi_bounds(self, sample_evaluation_report: EvaluationReport):
        """Test that ASPI is always within 0-100."""
        assert 0.0 <= sample_evaluation_report.aspi <= 100.0

    def test_gap_ratio_bounds(self, sample_evaluation_report: EvaluationReport):
        """Test that gap ratio is within 0-1."""
        assert 0.0 <= sample_evaluation_report.t1_t2_gap_ratio <= 1.0

    def test_control_composite_bounds(self):
        """Test that control composite is within 0-100."""
        score = ControlScore(
            control_id="D1.1",
            control_name="Control 1",
            t1_score=7.0,
            t2_score=8.0,
            t3_score=9.0,
        )

        assert 0.0 <= score.composite <= 100.0

    def test_domain_score_bounds(self):
        """Test that domain score is within 0-100."""
        domain = DomainResult(
            domain_id="D1",
            domain_name="Domain 1",
            applicability=Applicability.APPLICABLE,
            controls=[
                ControlScore(
                    control_id="D1.1",
                    control_name="C1",
                    t1_score=10.0,
                    t2_score=10.0,
                    t3_score=10.0,
                ),
            ],
        )

        assert domain.domain_score is not None
        assert 0.0 <= domain.domain_score <= 100.0

    def test_report_hash_consistency(self, sample_evaluation_report: EvaluationReport):
        """Test that report hash is consistent across calls."""
        hash1 = sample_evaluation_report.report_hash
        hash2 = sample_evaluation_report.report_hash

        assert hash1 == hash2
        assert len(hash1) == 20  # Truncated to 20 chars


class TestReportMetadata:
    """Tests for report metadata."""

    def test_report_has_timestamp(self, sample_evaluation_report: EvaluationReport):
        """Test that reports include timestamp."""
        assert sample_evaluation_report.timestamp is not None

    def test_report_has_framework_info(self, sample_evaluation_report: EvaluationReport):
        """Test that reports include framework version info."""
        assert sample_evaluation_report.framework is not None
        assert sample_evaluation_report.framework.name is not None

    def test_report_has_asopb_version(self, sample_evaluation_report: EvaluationReport):
        """Test that reports include ASOPB version."""
        assert sample_evaluation_report.asopb_version is not None
        assert len(sample_evaluation_report.asopb_version) > 0

    def test_report_evaluation_duration(self, sample_evaluation_report: EvaluationReport):
        """Test that report can include evaluation duration."""
        assert sample_evaluation_report.evaluation_duration_seconds is not None
        assert sample_evaluation_report.evaluation_duration_seconds > 0

    def test_report_llm_stats(self, sample_evaluation_report: EvaluationReport):
        """Test that report includes LLM usage stats."""
        assert sample_evaluation_report.llm_calls_made >= 0
        assert sample_evaluation_report.llm_tokens_used >= 0


class TestReportDomains:
    """Tests for report domain handling."""

    def test_report_domains_dict(self, sample_evaluation_report: EvaluationReport):
        """Test that report domains are properly structured."""
        assert isinstance(sample_evaluation_report.domains, dict)
        assert len(sample_evaluation_report.domains) > 0

    def test_report_domains_have_ids(self, sample_evaluation_report: EvaluationReport):
        """Test that all domains have proper IDs."""
        for domain_id, domain in sample_evaluation_report.domains.items():
            assert domain.domain_id == domain_id

    def test_report_domains_have_names(self, sample_evaluation_report: EvaluationReport):
        """Test that all domains have names."""
        for domain in sample_evaluation_report.domains.values():
            assert len(domain.domain_name) > 0

    def test_report_applicable_and_not_applicable(
        self, sample_evaluation_report: EvaluationReport
    ):
        """Test report can have both applicable and N/A domains."""
        applicable_count = sum(
            1
            for d in sample_evaluation_report.domains.values()
            if d.applicability == Applicability.APPLICABLE
        )

        not_applicable_count = sum(
            1
            for d in sample_evaluation_report.domains.values()
            if d.applicability == Applicability.NOT_APPLICABLE
        )

        # Sample report has both
        assert applicable_count > 0
        assert not_applicable_count > 0


class TestReportControls:
    """Tests for report control handling."""

    def test_report_has_controls(self, sample_evaluation_report: EvaluationReport):
        """Test that report domains have controls."""
        has_controls = False
        for domain in sample_evaluation_report.domains.values():
            if len(domain.controls) > 0:
                has_controls = True
                break

        assert has_controls

    def test_control_status_values(self, sample_evaluation_report: EvaluationReport):
        """Test that all controls have valid status."""
        for domain in sample_evaluation_report.domains.values():
            for control in domain.controls:
                assert control.status in [
                    ControlStatus.NOT_APPLICABLE,
                    ControlStatus.NOT_REVIEWED,
                    ControlStatus.NOT_A_FINDING,
                    ControlStatus.OPEN,
                    ControlStatus.PARTIALLY_IMPLEMENTED,
                ]

    def test_control_scores_in_range(self, sample_evaluation_report: EvaluationReport):
        """Test that all control scores are within valid range."""
        for domain in sample_evaluation_report.domains.values():
            for control in domain.controls:
                assert 0 <= control.t1_score <= 10
                assert 0 <= control.t2_score <= 10
                assert 0 <= control.t3_score <= 10
                assert 0 <= control.composite <= 100


class TestReportWarningsAndSkipped:
    """Tests for report warnings and skipped analyzers."""

    def test_report_warnings_list(self, sample_evaluation_report: EvaluationReport):
        """Test that report can include warnings."""
        assert isinstance(sample_evaluation_report.warnings, list)

    def test_report_skipped_analyzers(self, sample_evaluation_report: EvaluationReport):
        """Test that report can list skipped analyzers."""
        assert isinstance(sample_evaluation_report.analyzers_skipped, list)

    def test_report_with_warnings(self):
        """Test creating report with warnings."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[],
            ),
        }

        report = EvaluationReport(
            framework=framework,
            domains=domains,
            warnings=[
                "Some analysis was skipped",
                "External tool not available",
            ],
        )

        assert len(report.warnings) == 2
        assert "skipped" in report.warnings[0].lower()
