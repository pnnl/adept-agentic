"""
Unit tests for ASOPB core data models.

Tests:
- ControlScore composite calculation and floor enforcement
- DomainResult aggregation and domain_score calculation
- EvaluationReport ASPI calculation and gap ratios
- FrameworkVersion version_key generation
- ControlEvidence hash deduplication
- Report integrity hashing
"""

from datetime import datetime, timezone

import pytest

from asopb.models import (
    Applicability,
    ControlEvidence,
    ControlScore,
    ControlStatus,
    DomainResult,
    EvaluationReport,
    EvidenceSource,
    EvidenceTier,
    FrameworkVersion,
    RedTeamReport,
    RedTeamScenario,
)


class TestControlScore:
    """Tests for ControlScore composite and floor enforcement."""

    def test_composite_calculation(self):
        """Test that composite = (T1 + T2 + T3) / 3 * 10."""
        score = ControlScore(
            control_id="D1.1",
            control_name="Test Control",
            t1_score=5.0,
            t2_score=6.0,
            t3_score=7.0,
        )
        # (5 + 6 + 7) / 3 * 10 = 60.0
        assert score.composite == 60.0

    def test_composite_zero(self):
        """Test composite when all scores are zero."""
        score = ControlScore(
            control_id="D1.1",
            control_name="Test Control",
            t1_score=0.0,
            t2_score=0.0,
            t3_score=0.0,
        )
        assert score.composite == 0.0

    def test_composite_max(self):
        """Test composite when all scores are 10."""
        score = ControlScore(
            control_id="D1.1",
            control_name="Test Control",
            t1_score=10.0,
            t2_score=10.0,
            t3_score=10.0,
        )
        assert score.composite == 100.0

    def test_floor_enforcement_t1(self):
        """Test that T1 cannot be lowered below floor."""
        score = ControlScore(
            control_id="D1.1",
            control_name="Test Control",
            t1_score=2.0,
            t1_floor=5.0,
        )
        assert score.t1_score == 5.0  # Raised to floor

    def test_floor_enforcement_t2(self):
        """Test that T2 cannot be lowered below floor."""
        score = ControlScore(
            control_id="D1.1",
            control_name="Test Control",
            t2_score=1.0,
            t2_floor=4.0,
        )
        assert score.t2_score == 4.0  # Raised to floor

    def test_floor_enforcement_above_floor(self):
        """Test that scores above floor are not modified."""
        score = ControlScore(
            control_id="D1.1",
            control_name="Test Control",
            t1_score=7.0,
            t1_floor=3.0,
        )
        assert score.t1_score == 7.0  # Above floor, unchanged

    def test_evidence_list(self):
        """Test that evidence can be added to controls."""
        evidence = ControlEvidence(
            tier=EvidenceTier.T1_DESIGN,
            source=EvidenceSource.SCANNER,
            source_tool="scanner:auth",
            description="Test evidence",
        )
        score = ControlScore(
            control_id="D1.1",
            control_name="Test Control",
            evidence=[evidence],
        )
        assert len(score.evidence) == 1
        assert score.evidence[0].description == "Test evidence"


class TestDomainResult:
    """Tests for DomainResult aggregation."""

    def test_t1_aggregate(self):
        """Test T1 aggregate calculation."""
        controls = [
            ControlScore(
                control_id="D1.1",
                control_name="Control 1",
                t1_score=4.0,
            ),
            ControlScore(
                control_id="D1.2",
                control_name="Control 2",
                t1_score=6.0,
            ),
        ]
        domain = DomainResult(
            domain_id="D1",
            domain_name="Domain 1",
            controls=controls,
        )
        assert domain.t1_aggregate == 5.0  # (4 + 6) / 2

    def test_t2_aggregate(self):
        """Test T2 aggregate calculation."""
        controls = [
            ControlScore(
                control_id="D1.1",
                control_name="Control 1",
                t2_score=3.0,
            ),
            ControlScore(
                control_id="D1.2",
                control_name="Control 2",
                t2_score=7.0,
            ),
        ]
        domain = DomainResult(
            domain_id="D1",
            domain_name="Domain 1",
            controls=controls,
        )
        assert domain.t2_aggregate == 5.0

    def test_t3_aggregate(self):
        """Test T3 aggregate calculation."""
        controls = [
            ControlScore(
                control_id="D1.1",
                control_name="Control 1",
                t3_score=2.0,
            ),
            ControlScore(
                control_id="D1.2",
                control_name="Control 2",
                t3_score=8.0,
            ),
        ]
        domain = DomainResult(
            domain_id="D1",
            domain_name="Domain 1",
            controls=controls,
        )
        assert domain.t3_aggregate == 5.0

    def test_domain_score_calculation(self):
        """Test domain_score as average of composites."""
        controls = [
            ControlScore(
                control_id="D1.1",
                control_name="Control 1",
                t1_score=5.0,
                t2_score=6.0,
                t3_score=7.0,
            ),
            ControlScore(
                control_id="D1.2",
                control_name="Control 2",
                t1_score=7.0,
                t2_score=8.0,
                t3_score=9.0,
            ),
        ]
        domain = DomainResult(
            domain_id="D1",
            domain_name="Domain 1",
            controls=controls,
        )
        # Control 1 composite: (5+6+7)/3*10 = 60
        # Control 2 composite: (7+8+9)/3*10 = 80
        # Domain score: (60 + 80) / 2 = 70
        assert domain.domain_score == 70.0

    def test_domain_score_not_applicable(self):
        """Test that N/A domains return None score."""
        domain = DomainResult(
            domain_id="D5",
            domain_name="Domain 5",
            applicability=Applicability.NOT_APPLICABLE,
        )
        assert domain.domain_score is None

    def test_domain_score_empty_controls(self):
        """Test that domains with no controls return 0.0."""
        domain = DomainResult(
            domain_id="D1",
            domain_name="Domain 1",
            controls=[],
        )
        assert domain.domain_score == 0.0


class TestEvaluationReport:
    """Tests for EvaluationReport ASPI and gap calculations."""

    def test_aspi_calculation(self):
        """Test ASPI as weighted mean of domain scores."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

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
                        t1_score=5.0,
                        t2_score=5.0,
                        t3_score=5.0,
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
                        t1_score=7.0,
                        t2_score=7.0,
                        t3_score=7.0,
                    ),
                ],
            ),
        }

        report = EvaluationReport(
            framework=framework,
            domains=domains,
        )

        # D1 domain_score: (5+5+5)/3*10 = 50
        # D2 domain_score: (7+7+7)/3*10 = 70
        # ASPI = (1.5*50 + 1.0*70) / (1.5 + 1.0) = 145 / 2.5 = 58.0
        assert report.aspi == 58.0

    def test_aspi_excludes_not_applicable(self):
        """Test that N/A domains are excluded from ASPI."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

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

        report = EvaluationReport(
            framework=framework,
            domains=domains,
        )

        # Only D1 counts: (1.0*50) / 1.0 = 50.0
        assert report.aspi == 50.0

    def test_aspi_all_not_applicable(self):
        """Test that ASPI is 0 when all domains are N/A."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

        domains = {
            "D5": DomainResult(
                domain_id="D5",
                domain_name="Domain 5",
                applicability=Applicability.NOT_APPLICABLE,
            ),
        }

        report = EvaluationReport(
            framework=framework,
            domains=domains,
        )

        assert report.aspi == 0.0

    def test_t1_t2_gap_ratio_calculation(self):
        """Test T1/T2 gap ratio (controls with T1>0 but T2=0)."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

        domains = {
            "D1": DomainResult(
                domain_id="D1",
                domain_name="Domain 1",
                applicability=Applicability.APPLICABLE,
                controls=[
                    ControlScore(
                        control_id="D1.1",
                        control_name="C1",
                        t1_score=5.0,  # T1 > 0
                        t2_score=0.0,  # T2 = 0 (gap)
                    ),
                    ControlScore(
                        control_id="D1.2",
                        control_name="C2",
                        t1_score=5.0,  # T1 > 0
                        t2_score=3.0,  # T2 > 0 (no gap)
                    ),
                    ControlScore(
                        control_id="D1.3",
                        control_name="C3",
                        t1_score=0.0,  # T1 = 0 (not counted)
                        t2_score=0.0,
                    ),
                ],
            ),
        }

        report = EvaluationReport(
            framework=framework,
            domains=domains,
        )

        # 2 controls with T1>0, 1 with T1>0 but T2=0
        # Ratio: 1/2 = 0.5
        assert report.t1_t2_gap_ratio == 0.5

    def test_t1_t2_gap_ratio_no_t1(self):
        """Test gap ratio when no T1 scores present."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

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

        report = EvaluationReport(
            framework=framework,
            domains=domains,
        )

        assert report.t1_t2_gap_ratio == 0.0

    def test_report_hash_integrity(self):
        """Test that report hash changes when content changes."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

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
                        t3_score=5.0,
                    ),
                ],
            ),
        }

        report1 = EvaluationReport(
            framework=framework,
            domains=domains,
        )
        hash1 = report1.report_hash

        # Modify domain score slightly
        domains["D1"].controls[0].t1_score = 6.0

        report2 = EvaluationReport(
            framework=framework,
            domains=domains,
        )
        hash2 = report2.report_hash

        assert hash1 != hash2


class TestFrameworkVersion:
    """Tests for FrameworkVersion version_key generation."""

    def test_version_key_with_git_commit(self):
        """Test version_key prioritizes git_commit."""
        fv = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
            git_commit="abc123def456789",
            git_tag="v1.0.0",
        )
        assert fv.version_key == "test-framework:abc123def456"  # Commit shortened to 12 chars

    def test_version_key_with_version_only(self):
        """Test version_key falls back to semantic version."""
        fv = FrameworkVersion(
            name="test-framework",
            version="2.5.3",
        )
        assert fv.version_key == "test-framework:2.5.3"

    def test_version_key_with_tag(self):
        """Test version_key uses tag if no version."""
        fv = FrameworkVersion(
            name="test-framework",
            git_tag="release-1.0",
        )
        assert fv.version_key == "test-framework:release-1.0"

    def test_version_key_with_date_fallback(self):
        """Test version_key uses date if nothing else available."""
        fv = FrameworkVersion(
            name="test-framework",
        )
        key = fv.version_key
        assert key.startswith("test-framework:")
        assert len(key.split(":")[1]) == 8  # YYYYMMDD


class TestControlEvidence:
    """Tests for ControlEvidence hash deduplication."""

    def test_evidence_hash_generation(self):
        """Test that evidence hashes are generated consistently."""
        ev = ControlEvidence(
            tier=EvidenceTier.T2_IMPLEMENTATION,
            source=EvidenceSource.SCANNER,
            source_tool="scanner:auth",
            file_path="src/auth.py",
            line_range=(10, 20),
            description="JWT validation found",
        )

        # Hash should be consistent
        hash1 = ev.evidence_hash
        hash2 = ev.evidence_hash
        assert hash1 == hash2
        assert len(hash1) == 16  # SHA256 truncated to 16 chars

    def test_evidence_hash_different_for_changes(self):
        """Test that different evidence produces different hashes."""
        ev1 = ControlEvidence(
            tier=EvidenceTier.T2_IMPLEMENTATION,
            source=EvidenceSource.SCANNER,
            source_tool="scanner:auth",
            description="JWT validation found",
        )

        ev2 = ControlEvidence(
            tier=EvidenceTier.T2_IMPLEMENTATION,
            source=EvidenceSource.SCANNER,
            source_tool="scanner:auth",
            description="JWT validation NOT found",  # Different description
        )

        assert ev1.evidence_hash != ev2.evidence_hash

    def test_evidence_hash_ignores_timestamp(self):
        """Test that evidence hash ignores timestamp."""
        now = datetime.now(timezone.utc)

        ev1 = ControlEvidence(
            tier=EvidenceTier.T2_IMPLEMENTATION,
            source=EvidenceSource.SCANNER,
            source_tool="scanner:auth",
            description="Test",
            timestamp=now,
        )

        import time

        time.sleep(0.1)

        ev2 = ControlEvidence(
            tier=EvidenceTier.T2_IMPLEMENTATION,
            source=EvidenceSource.SCANNER,
            source_tool="scanner:auth",
            description="Test",
            timestamp=datetime.now(timezone.utc),
        )

        assert ev1.evidence_hash == ev2.evidence_hash


class TestRedTeamScenario:
    """Tests for RedTeamScenario and RedTeamReport construction."""

    def test_scenario_construction(self):
        """Test that RedTeamScenario can be constructed."""
        scenario = RedTeamScenario(
            scenario_id="RT-1",
            scenario_name="Prompt Injection Attack",
            attack_vector="Direct prompt injection in tool input",
            target_domain="D3",
            target_controls=["D3.1", "D3.2"],
            outcome="partial_bypass",
            outcome_description="Attacker was able to bypass content filtering",
            t3_score_contribution=5.0,
        )

        assert scenario.scenario_id == "RT-1"
        assert scenario.target_domain == "D3"
        assert len(scenario.target_controls) == 2
        assert scenario.t3_score_contribution == 5.0

    def test_red_team_report_construction(self):
        """Test that RedTeamReport can be constructed."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

        scenario = RedTeamScenario(
            scenario_id="RT-1",
            scenario_name="Test Attack",
            attack_vector="Test vector",
            target_domain="D3",
            outcome="defense_held",
            outcome_description="Defense successful",
        )

        report = RedTeamReport(
            report_id="rt-20250329-001",
            source="manual-red-team",
            framework_version=framework,
            scenarios=[scenario],
        )

        assert report.report_id == "rt-20250329-001"
        assert len(report.scenarios) == 1
        assert report.scenarios[0].scenario_id == "RT-1"
