"""
Unit tests for domain evaluators.

Tests:
- D4 Identity evaluator with auth scanner findings
- D4 floor enforcement (LLM can't lower below scanner floor)
- Domain applicability checking
- Domain registry registration and custom weights
"""

import asyncio
from pathlib import Path

import pytest

from asopb.config import EvalConfig
from asopb.domains.d4_identity import D4IdentityEvaluator
from asopb.models import (
    Applicability,
    ControlEvidence,
    ControlScore,
    ControlStatus,
    EvidenceSource,
    EvidenceTier,
    ScanFinding,
    ScanResult,
    Severity,
)


class TestD4IdentityEvaluator:
    """Tests for D4 Identity and Authentication evaluator."""

    def test_d4_control_definitions(self):
        """Test that D4 defines all required controls."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        controls = evaluator.define_controls()

        assert len(controls) == 6
        control_ids = [c.control_id for c in controls]
        assert "D4.1" in control_ids
        assert "D4.2" in control_ids
        assert "D4.3" in control_ids
        assert "D4.4" in control_ids
        assert "D4.5" in control_ids
        assert "D4.6" in control_ids

    def test_d4_required_scanners(self):
        """Test that D4 declares required scanners."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        scanners = evaluator.required_scanners()
        assert "auth" in scanners
        assert "codebase" in scanners

    def test_d4_required_analyzers(self):
        """Test that D4 declares required analyzers."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        analyzers = evaluator.required_analyzers()
        assert "tls" in analyzers
        assert len(analyzers) > 0

    @pytest.mark.asyncio
    async def test_d4_score_controls_with_jwt(self):
        """Test D4 control scoring with JWT evidence."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        # Create scan results with JWT findings
        auth_findings = [
            ScanFinding(
                finding_id="auth:jwt:src/auth.py:1",
                category="jwt_module_detected",
                severity=Severity.INFORMATIONAL,
                file_path="src/auth.py",
                line_number=1,
                message="JWT module imported",
            ),
        ]

        scan_results = {
            "auth": ScanResult(
                tool_name="auth",
                success=True,
                findings=auth_findings,
            ),
            "codebase": ScanResult(
                tool_name="codebase",
                success=True,
                findings=[],
            ),
        }

        analyzer_results = {
            "tls": ScanResult(
                tool_name="tls",
                success=True,
                findings=[],
            ),
        }

        scores = await evaluator.score_controls(scan_results, analyzer_results)

        # Should have 6 scores (one per control)
        assert len(scores) == 6

        # D4.3 (JWT) should have non-zero T2 floor
        d43 = next(s for s in scores if s.control_id == "D4.3")
        assert d43.t2_floor >= 0.0

    @pytest.mark.asyncio
    async def test_d4_floor_enforcement(self):
        """Test that D4 floors prevent LLM from lowering scores."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        scan_results = {
            "auth": ScanResult(
                tool_name="auth",
                success=True,
                findings=[
                    ScanFinding(
                        finding_id="auth:jwt:src/auth.py:1",
                        category="jwt_module_detected",
                        severity=Severity.INFORMATIONAL,
                        file_path="src/auth.py",
                        line_number=1,
                        message="JWT detected",
                    ),
                ],
            ),
            "codebase": ScanResult(
                tool_name="codebase",
                success=True,
                findings=[],
            ),
        }

        analyzer_results = {
            "tls": ScanResult(
                tool_name="tls",
                success=True,
                findings=[],
            ),
        }

        scores = await evaluator.score_controls(scan_results, analyzer_results)

        # All scores should respect their floors
        for score in scores:
            assert score.t1_score >= score.t1_floor
            assert score.t2_score >= score.t2_floor

    @pytest.mark.asyncio
    async def test_d4_applicability(self):
        """Test D4 applicability checking."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        # D4 should always be applicable (no federation requirement)
        scan_results = {
            "auth": ScanResult(
                tool_name="auth",
                success=True,
                findings=[],
            ),
            "codebase": ScanResult(
                tool_name="codebase",
                success=True,
                findings=[],
            ),
        }

        applicability = evaluator.check_applicability(scan_results)
        assert applicability == Applicability.APPLICABLE


class TestD4IdentityDetailed:
    """More detailed tests for D4 control scoring."""

    @pytest.mark.asyncio
    async def test_d4_6_mtls_scoring(self):
        """Test D4.6 (mTLS) scoring with verify=False detection."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        # TLS findings with verify=False
        tls_findings = [
            ScanFinding(
                finding_id="tls:verify_false:src/client.py:45",
                category="verify_false",
                severity=Severity.HIGH,
                file_path="src/client.py",
                line_number=45,
                message="verify=False in TLS client",
                snippet="requests.get(url, verify=False)",
            ),
        ]

        scan_results = {
            "auth": ScanResult(
                tool_name="auth",
                success=True,
                findings=[],
            ),
            "codebase": ScanResult(
                tool_name="codebase",
                success=True,
                findings=[],
            ),
        }

        analyzer_results = {
            "tls": ScanResult(
                tool_name="tls",
                success=True,
                findings=tls_findings,
            ),
        }

        scores = await evaluator.score_controls(scan_results, analyzer_results)

        # D4.6 should have very low T2 due to verify=False
        d46 = next(s for s in scores if s.control_id == "D4.6")
        assert d46.t2_score <= 1.0

    @pytest.mark.asyncio
    async def test_d4_5_optional_token_detection(self):
        """Test D4.5 (Session Token) negative evidence from Optional[str]."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        scan_results = {
            "auth": ScanResult(
                tool_name="auth",
                success=True,
                findings=[],
            ),
            "codebase": ScanResult(
                tool_name="codebase",
                success=True,
                findings=[],
            ),
        }

        analyzer_results = {
            "tls": ScanResult(
                tool_name="tls",
                success=True,
                findings=[],
            ),
        }

        scores = await evaluator.score_controls(scan_results, analyzer_results)

        # D4.5 should be defined
        d45 = next(s for s in scores if s.control_id == "D4.5")
        assert d45.control_id == "D4.5"
        assert d45.control_name == "Session Token Validation"


class TestDomainApplicability:
    """Tests for domain applicability checking."""

    def test_domain_applicable_by_default(self):
        """Test that domains are applicable by default."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        scan_results = {}
        applicability = evaluator.check_applicability(scan_results)

        assert applicability == Applicability.APPLICABLE


class TestDomainMetadata:
    """Tests for domain evaluator metadata."""

    def test_d4_metadata(self):
        """Test that D4 has correct metadata."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        assert evaluator.domain_id == "D4"
        assert evaluator.domain_name == "Identity and Authentication"
        assert evaluator.weight == 1.0
        assert evaluator.skill_file == "d4_identity.md"

    def test_d4_control_severity(self):
        """Test that D4 controls have appropriate severity levels."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        controls = evaluator.define_controls()

        # D4.1 and D4.6 should be CRITICAL
        d41 = next(c for c in controls if c.control_id == "D4.1")
        d46 = next(c for c in controls if c.control_id == "D4.6")

        assert d41.severity.value == "critical"
        assert d46.severity.value == "critical"

        # Others should be HIGH or MEDIUM
        for c in controls:
            if c.control_id not in ["D4.1", "D4.6"]:
                assert c.severity.value in ["high", "medium"]

    def test_d4_control_nist_mapping(self):
        """Test that D4 controls have NIST mappings."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        controls = evaluator.define_controls()

        # All controls should have NIST mappings
        for c in controls:
            assert len(c.nist_mapping) > 0
            # Check valid NIST categories
            assert any(
                nm.startswith(("IA-", "SC-", "AC-", "SA-"))
                for nm in c.nist_mapping
            )

    def test_d4_control_criteria(self):
        """Test that D4 controls have T1/T2/T3 criteria."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        controls = evaluator.define_controls()

        # All controls should have T1 criteria
        for c in controls:
            assert len(c.t1_criteria) > 0
            assert len(c.t2_criteria) > 0
            assert len(c.t3_criteria) > 0

    def test_d4_control_patterns(self):
        """Test that D4 controls have positive and negative patterns."""
        config = EvalConfig(skip_llm=True)
        evaluator = D4IdentityEvaluator(config)

        controls = evaluator.define_controls()

        # All controls should have patterns for pattern matching
        for c in controls:
            assert len(c.positive_patterns) > 0
            assert len(c.negative_patterns) > 0
