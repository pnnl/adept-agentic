"""
Contract tests for all ASOPB domain evaluators (D1-D8).

Validates the evaluator contract:
- Instantiation with EvalConfig
- Control definitions (correct count, valid IDs, severity, mappings)
- score_controls() with empty results (graceful degradation)
- score_controls() with findings (T2 floor raised, evidence constructed)
- Negative evidence capping (T2 floor reduced on vulnerabilities)
- Required scanners/analyzers declared

These tests catch AttributeErrors, import failures, and contract violations
without needing a live scanner pipeline.
"""

import asyncio
from typing import Type

import pytest

from asopb.config import EvalConfig
from asopb.domains.base import DomainEvaluator
from asopb.domains.d1_model_integrity import D1ModelIntegrityEvaluator
from asopb.domains.d2_orchestration import D2OrchestrationEvaluator
from asopb.domains.d3_tool_security import D3ToolSecurityEvaluator
from asopb.domains.d4_identity import D4IdentityEvaluator
from asopb.domains.d5_federation import D5FederationEvaluator
from asopb.domains.d6_observability import D6ObservabilityEvaluator
from asopb.domains.d7_itot import D7ItOtEvaluator
from asopb.domains.d8_supply_chain import D8SupplyChainEvaluator
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


ALL_EVALUATORS: list[tuple[str, Type[DomainEvaluator], int]] = [
    ("D1", D1ModelIntegrityEvaluator, 5),
    ("D2", D2OrchestrationEvaluator, 5),
    ("D3", D3ToolSecurityEvaluator, 5),
    ("D4", D4IdentityEvaluator, 6),
    ("D5", D5FederationEvaluator, 5),
    ("D6", D6ObservabilityEvaluator, 5),
    ("D7", D7ItOtEvaluator, 5),
    ("D8", D8SupplyChainEvaluator, 8),
]


@pytest.fixture
def config():
    return EvalConfig(skip_llm=True)


def _make_scan_result(tool_name: str, findings: list[ScanFinding] | None = None) -> ScanResult:
    return ScanResult(tool_name=tool_name, success=True, findings=findings or [])


def _make_finding(category: str, severity: Severity = Severity.MEDIUM) -> ScanFinding:
    return ScanFinding(
        finding_id=f"test:{category}:file.py:1",
        category=category,
        severity=severity,
        file_path="src/file.py",
        line_number=1,
        message=f"Test finding for {category}",
    )


class TestAllEvaluatorsContract:
    """Contract tests applied to every domain evaluator."""

    @pytest.mark.parametrize("domain_id,evaluator_cls,expected_controls", ALL_EVALUATORS)
    def test_instantiation(self, config, domain_id, evaluator_cls, expected_controls):
        """All evaluators instantiate without error."""
        evaluator = evaluator_cls(config)
        assert evaluator.domain_id == domain_id
        assert evaluator.domain_name != ""
        assert evaluator.weight > 0

    @pytest.mark.parametrize("domain_id,evaluator_cls,expected_controls", ALL_EVALUATORS)
    def test_control_count(self, config, domain_id, evaluator_cls, expected_controls):
        """Each evaluator defines the expected number of controls."""
        evaluator = evaluator_cls(config)
        controls = evaluator.define_controls()
        assert len(controls) == expected_controls

    @pytest.mark.parametrize("domain_id,evaluator_cls,expected_controls", ALL_EVALUATORS)
    def test_control_ids_prefixed(self, config, domain_id, evaluator_cls, expected_controls):
        """All control IDs are prefixed with their domain ID."""
        evaluator = evaluator_cls(config)
        controls = evaluator.define_controls()
        for control in controls:
            assert control.control_id.startswith(domain_id + ".")
            assert control.domain_id == domain_id

    @pytest.mark.parametrize("domain_id,evaluator_cls,expected_controls", ALL_EVALUATORS)
    def test_controls_have_severity(self, config, domain_id, evaluator_cls, expected_controls):
        """All controls have a valid severity."""
        evaluator = evaluator_cls(config)
        controls = evaluator.define_controls()
        valid = {Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFORMATIONAL}
        for control in controls:
            assert control.severity in valid

    @pytest.mark.parametrize("domain_id,evaluator_cls,expected_controls", ALL_EVALUATORS)
    def test_controls_have_nist_mapping(self, config, domain_id, evaluator_cls, expected_controls):
        """All controls have at least one NIST mapping."""
        evaluator = evaluator_cls(config)
        controls = evaluator.define_controls()
        for control in controls:
            assert len(control.nist_mapping) > 0

    @pytest.mark.parametrize("domain_id,evaluator_cls,expected_controls", ALL_EVALUATORS)
    def test_required_scanners_declared(self, config, domain_id, evaluator_cls, expected_controls):
        """Each evaluator declares at least one required scanner."""
        evaluator = evaluator_cls(config)
        scanners = evaluator.required_scanners()
        assert len(scanners) >= 1
        assert "codebase" in scanners

    @pytest.mark.parametrize("domain_id,evaluator_cls,expected_controls", ALL_EVALUATORS)
    def test_required_analyzers_declared(self, config, domain_id, evaluator_cls, expected_controls):
        """Each evaluator declares analyzers (may be empty list)."""
        evaluator = evaluator_cls(config)
        analyzers = evaluator.required_analyzers()
        assert isinstance(analyzers, list)

    @pytest.mark.parametrize("domain_id,evaluator_cls,expected_controls", ALL_EVALUATORS)
    @pytest.mark.asyncio
    async def test_score_controls_empty_results(self, config, domain_id, evaluator_cls, expected_controls):
        """Evaluators score gracefully with empty scan results."""
        evaluator = evaluator_cls(config)
        scan_results = {s: _make_scan_result(s) for s in evaluator.required_scanners()}
        analyzer_results = {a: _make_scan_result(a) for a in evaluator.required_analyzers()}

        scores = await evaluator.score_controls(scan_results, analyzer_results)

        assert len(scores) == expected_controls
        for score in scores:
            assert score.control_id.startswith(domain_id + ".")
            assert score.t1_score >= 0
            assert score.t2_score >= 0
            assert score.t1_score <= 10
            assert score.t2_score <= 10

    @pytest.mark.parametrize("domain_id,evaluator_cls,expected_controls", ALL_EVALUATORS)
    @pytest.mark.asyncio
    async def test_score_controls_missing_scanners(self, config, domain_id, evaluator_cls, expected_controls):
        """Evaluators handle missing scanner results gracefully (no crash)."""
        evaluator = evaluator_cls(config)

        scores = await evaluator.score_controls({}, {})

        assert len(scores) == expected_controls
        for score in scores:
            assert score.t2_score <= 10.0
            assert score.t2_score >= 0.0


class TestD1ModelIntegrityScoring:
    """D1 scoring with realistic findings."""

    @pytest.mark.asyncio
    async def test_provenance_findings_raise_t2(self, config):
        evaluator = D1ModelIntegrityEvaluator(config)
        scan_results = {
            "supply_chain": _make_scan_result("supply_chain", [
                _make_finding("model_provenance", Severity.INFORMATIONAL),
            ]),
            "codebase": _make_scan_result("codebase", [
                _make_finding("registry_hash", Severity.INFORMATIONAL),
            ]),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep")}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d11 = next(s for s in scores if s.control_id == "D1.1")
        assert d11.t2_score > 0.0
        assert len(d11.evidence) > 0

    @pytest.mark.asyncio
    async def test_hash_validation_findings(self, config):
        evaluator = D1ModelIntegrityEvaluator(config)
        scan_results = {
            "supply_chain": _make_scan_result("supply_chain"),
            "codebase": _make_scan_result("codebase", [
                _make_finding("hash_validation", Severity.INFORMATIONAL),
                _make_finding("hash_algorithm", Severity.INFORMATIONAL),
            ]),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep")}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d12 = next(s for s in scores if s.control_id == "D1.2")
        assert d12.t2_score > 0.0

    @pytest.mark.asyncio
    async def test_unsigned_deployment_negative_evidence(self, config):
        evaluator = D1ModelIntegrityEvaluator(config)
        scan_results = {
            "supply_chain": _make_scan_result("supply_chain", [
                _make_finding("deployment_signing", Severity.INFORMATIONAL),
            ]),
            "codebase": _make_scan_result("codebase"),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep", [
            _make_finding("unsigned_deployment", Severity.HIGH),
        ])}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d14 = next(s for s in scores if s.control_id == "D1.4")
        assert d14.t2_score <= 3.0


class TestD2OrchestrationScoring:
    """D2 scoring with realistic findings."""

    @pytest.mark.asyncio
    async def test_isolation_findings_raise_t2(self, config):
        evaluator = D2OrchestrationEvaluator(config)
        scan_results = {
            "sandbox": _make_scan_result("sandbox", [
                _make_finding("agent_isolation", Severity.INFORMATIONAL),
            ]),
            "codebase": _make_scan_result("codebase", [
                _make_finding("sandbox_execution", Severity.INFORMATIONAL),
            ]),
        }
        analyzer_results = {
            "semgrep": _make_scan_result("semgrep"),
            "bandit": _make_scan_result("bandit"),
        }

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d21 = next(s for s in scores if s.control_id == "D2.1")
        assert d21.t2_score > 0.0
        assert len(d21.evidence) >= 2

    @pytest.mark.asyncio
    async def test_shared_memory_caps_t2(self, config):
        evaluator = D2OrchestrationEvaluator(config)
        scan_results = {
            "sandbox": _make_scan_result("sandbox", [
                _make_finding("agent_isolation", Severity.INFORMATIONAL),
            ]),
            "codebase": _make_scan_result("codebase", [
                _make_finding("shared_memory", Severity.HIGH),
            ]),
        }
        analyzer_results = {
            "semgrep": _make_scan_result("semgrep"),
            "bandit": _make_scan_result("bandit"),
        }

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d21 = next(s for s in scores if s.control_id == "D2.1")
        assert d21.t2_score <= 2.0


class TestD3ToolSecurityScoring:
    """D3 scoring with realistic findings."""

    @pytest.mark.asyncio
    async def test_tool_auth_findings(self, config):
        evaluator = D3ToolSecurityEvaluator(config)
        scan_results = {
            "tools": _make_scan_result("tools", [
                _make_finding("tool_auth", Severity.INFORMATIONAL),
            ]),
            "codebase": _make_scan_result("codebase", [
                _make_finding("api_key_validation", Severity.INFORMATIONAL),
            ]),
        }
        analyzer_results = {
            "semgrep": _make_scan_result("semgrep"),
            "bandit": _make_scan_result("bandit"),
        }

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d31 = next(s for s in scores if s.control_id == "D3.1")
        assert d31.t2_score > 0.0

    @pytest.mark.asyncio
    async def test_schema_validation_findings(self, config):
        evaluator = D3ToolSecurityEvaluator(config)
        scan_results = {
            "tools": _make_scan_result("tools"),
            "codebase": _make_scan_result("codebase", [
                _make_finding("pydantic_model", Severity.INFORMATIONAL),
                _make_finding("input_validation", Severity.INFORMATIONAL),
            ]),
        }
        analyzer_results = {
            "semgrep": _make_scan_result("semgrep"),
            "bandit": _make_scan_result("bandit"),
        }

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d32 = next(s for s in scores if s.control_id == "D3.2")
        assert d32.t2_score > 0.0

    @pytest.mark.asyncio
    async def test_unauth_tool_access_caps_t2(self, config):
        evaluator = D3ToolSecurityEvaluator(config)
        scan_results = {
            "tools": _make_scan_result("tools", [
                _make_finding("tool_auth", Severity.INFORMATIONAL),
                _make_finding("unauth_tool_access", Severity.HIGH),
            ]),
            "codebase": _make_scan_result("codebase"),
        }
        analyzer_results = {
            "semgrep": _make_scan_result("semgrep"),
            "bandit": _make_scan_result("bandit"),
        }

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d31 = next(s for s in scores if s.control_id == "D3.1")
        assert d31.t2_score <= 3.0


class TestD5FederationScoring:
    """D5 scoring with realistic findings."""

    @pytest.mark.asyncio
    async def test_discovery_findings(self, config):
        evaluator = D5FederationEvaluator(config)
        scan_results = {
            "federation": _make_scan_result("federation", [
                _make_finding("agent_discovery", Severity.INFORMATIONAL),
            ]),
            "codebase": _make_scan_result("codebase", [
                _make_finding("service_registry", Severity.INFORMATIONAL),
            ]),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep")}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d51 = next(s for s in scores if s.control_id == "D5.1")
        assert d51.t2_score > 0.0

    @pytest.mark.asyncio
    async def test_missing_boundary_caps_t2(self, config):
        evaluator = D5FederationEvaluator(config)
        scan_results = {
            "federation": _make_scan_result("federation", [
                _make_finding("trust_boundary", Severity.INFORMATIONAL),
                _make_finding("missing_boundary", Severity.HIGH),
            ]),
            "codebase": _make_scan_result("codebase"),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep")}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d52 = next(s for s in scores if s.control_id == "D5.2")
        assert d52.t2_score <= 3.0


class TestD6ObservabilityScoring:
    """D6 scoring with realistic findings."""

    @pytest.mark.asyncio
    async def test_structured_logging_findings(self, config):
        evaluator = D6ObservabilityEvaluator(config)
        scan_results = {
            "observability": _make_scan_result("observability", [
                _make_finding("structured_logging", Severity.INFORMATIONAL),
            ]),
            "codebase": _make_scan_result("codebase", [
                _make_finding("json_logging", Severity.INFORMATIONAL),
            ]),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep")}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d61 = next(s for s in scores if s.control_id == "D6.1")
        assert d61.t2_score > 0.0

    @pytest.mark.asyncio
    async def test_opentelemetry_findings(self, config):
        evaluator = D6ObservabilityEvaluator(config)
        scan_results = {
            "observability": _make_scan_result("observability"),
            "codebase": _make_scan_result("codebase", [
                _make_finding("opentelemetry", Severity.INFORMATIONAL),
                _make_finding("trace_propagation", Severity.INFORMATIONAL),
            ]),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep")}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d63 = next(s for s in scores if s.control_id == "D6.3")
        assert d63.t2_score > 0.0

    @pytest.mark.asyncio
    async def test_mutable_log_caps_t2(self, config):
        evaluator = D6ObservabilityEvaluator(config)
        scan_results = {
            "observability": _make_scan_result("observability", [
                _make_finding("log_immutability", Severity.INFORMATIONAL),
            ]),
            "codebase": _make_scan_result("codebase", [
                _make_finding("mutable_log", Severity.HIGH),
            ]),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep")}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d65 = next(s for s in scores if s.control_id == "D6.5")
        assert d65.t2_score <= 3.0


class TestD7ItOtScoring:
    """D7 scoring with realistic findings."""

    @pytest.mark.asyncio
    async def test_ot_isolation_findings(self, config):
        evaluator = D7ItOtEvaluator(config)
        scan_results = {
            "itot": _make_scan_result("itot", [
                _make_finding("ot_isolation", Severity.INFORMATIONAL),
            ]),
            "codebase": _make_scan_result("codebase", [
                _make_finding("ot_rate_limiting", Severity.INFORMATIONAL),
            ]),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep")}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d71 = next(s for s in scores if s.control_id == "D7.1")
        assert d71.t2_score > 0.0

    @pytest.mark.asyncio
    async def test_unrestricted_ot_access_caps_t2(self, config):
        evaluator = D7ItOtEvaluator(config)
        scan_results = {
            "itot": _make_scan_result("itot", [
                _make_finding("ot_isolation", Severity.INFORMATIONAL),
                _make_finding("unrestricted_ot_access", Severity.HIGH),
            ]),
            "codebase": _make_scan_result("codebase"),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep")}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d71 = next(s for s in scores if s.control_id == "D7.1")
        assert d71.t2_score <= 3.0

    @pytest.mark.asyncio
    async def test_human_approval_findings(self, config):
        evaluator = D7ItOtEvaluator(config)
        scan_results = {
            "itot": _make_scan_result("itot", [
                _make_finding("human_approval", Severity.INFORMATIONAL),
            ]),
            "codebase": _make_scan_result("codebase", [
                _make_finding("approval_workflow", Severity.INFORMATIONAL),
                _make_finding("approval_logging", Severity.INFORMATIONAL),
            ]),
        }
        analyzer_results = {"semgrep": _make_scan_result("semgrep")}

        scores = await evaluator.score_controls(scan_results, analyzer_results)
        d74 = next(s for s in scores if s.control_id == "D7.4")
        assert d74.t2_score > 0.0
        assert len(d74.evidence) >= 2
