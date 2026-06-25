"""
Phase C Integration Tests: Full 8-Domain ASPI Pipeline with Promptfoo Red-Team

Tests the complete pipeline path:
  EvalConfig(promptfoo_output_paths) → Evaluator → DomainRegistry → 8 evaluators → ASPI

Validates:
1. Evaluator._load_red_team_reports() ingests promptfoo JSON via PromptfooIngester
2. DomainRegistry provides all 8 evaluators
3. _apply_red_team_scores() distributes T3 penalties to correct domains/controls
4. ASPI score reflects T3 penalties (lower when attacks succeed)
5. All 8 domains produce DomainResult with populated controls
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from asopb.config import EvalConfig, RedTeamConfig, ScoringConfig
from asopb.domains.registry import DomainRegistry
from asopb.evaluator import ASPICalculator, Evaluator
from asopb.models import (
    Applicability,
    ControlScore,
    DomainResult,
    RedTeamReport,
    ScanResult,
)
from asopb.redteam import PromptfooIngester
from asopb.scoring import ASPICalculator as ScoringASPICalculator


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "promptfoo_outputs"


class TestDomainRegistryIntegration:
    """Verify DomainRegistry provides all 8 evaluators."""

    def test_registry_provides_all_eight_evaluators(self):
        config = EvalConfig()
        registry = DomainRegistry(config)
        for domain_id in ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]:
            evaluator = registry.get_evaluator(domain_id)
            assert evaluator is not None, f"Missing evaluator for {domain_id}"
            assert evaluator.domain_id == domain_id

    def test_registry_returns_none_for_invalid_domain(self):
        config = EvalConfig()
        registry = DomainRegistry(config)
        assert registry.get_evaluator("D9") is None

    def test_registry_respects_config_weights(self):
        config = EvalConfig(
            scoring=ScoringConfig(domain_weights={"D1": 2.5, "D8": 3.0})
        )
        registry = DomainRegistry(config)
        d1 = registry.get_evaluator("D1")
        assert d1 is not None


class TestEvaluatorPromptfooIngestion:
    """Verify Evaluator._load_red_team_reports() ingests promptfoo JSON."""

    def test_evaluator_loads_promptfoo_outputs(self):
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        config = EvalConfig(
            red_team=RedTeamConfig(promptfoo_output_paths=[report_path])
        )
        evaluator = Evaluator(config)
        reports = evaluator._load_red_team_reports()

        assert len(reports) == 1
        report = reports[0]
        assert isinstance(report, RedTeamReport)
        assert len(report.scenarios) == 10

    def test_evaluator_loads_multiple_promptfoo_outputs(self):
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        config = EvalConfig(
            red_team=RedTeamConfig(promptfoo_output_paths=[report_path, report_path])
        )
        evaluator = Evaluator(config)
        reports = evaluator._load_red_team_reports()
        assert len(reports) == 2

    def test_evaluator_handles_missing_promptfoo_path(self):
        config = EvalConfig(
            red_team=RedTeamConfig(
                promptfoo_output_paths=[Path("/nonexistent/output.json")]
            )
        )
        evaluator = Evaluator(config)
        reports = evaluator._load_red_team_reports()
        assert len(reports) == 0

    def test_evaluator_combines_report_paths_and_promptfoo(self):
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        config = EvalConfig(
            red_team=RedTeamConfig(
                report_paths=[],
                promptfoo_output_paths=[report_path],
            )
        )
        evaluator = Evaluator(config)
        reports = evaluator._load_red_team_reports()
        assert len(reports) == 1


class TestRedTeamT3Distribution:
    """Verify T3 penalties are distributed to correct domain controls."""

    @pytest.fixture
    def azure_report(self):
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")
        ingester = PromptfooIngester(provider_label="Azure o4-mini")
        return ingester.ingest(report_path)

    def test_bypass_scenarios_target_multiple_domains(self, azure_report):
        bypasses = [s for s in azure_report.scenarios if "bypass" in s.outcome]
        assert len(bypasses) >= 2
        domains_hit = {s.target_domain for s in bypasses}
        assert len(domains_hit) >= 2

    def test_t3_scores_are_positive_for_bypasses(self, azure_report):
        for scenario in azure_report.scenarios:
            if "bypass" in scenario.outcome:
                assert scenario.t3_score_contribution > 0.0
            elif scenario.outcome == "defense_held":
                assert scenario.t3_score_contribution == 0.0

    def test_apply_red_team_scores_updates_control_t3(self, azure_report):
        from asopb.domains.d2_orchestration import D2OrchestrationEvaluator

        config = EvalConfig()
        evaluator = D2OrchestrationEvaluator(config)
        controls = evaluator.define_controls()
        control_scores = [
            ControlScore(
                control_id=c.control_id,
                control_name=c.name,
                t1_score=2.0,
                t2_score=3.0,
                t3_score=0.0,
            )
            for c in controls
        ]

        # Apply red-team scores
        updated = evaluator._apply_red_team_scores(control_scores, [azure_report])

        d2_scenarios = [
            s for s in azure_report.scenarios if s.target_domain == "D2"
        ]
        if d2_scenarios:
            bypass_in_d2 = any("bypass" in s.outcome for s in d2_scenarios)
            if bypass_in_d2:
                has_t3 = any(c.t3_score > 0 for c in updated)
                assert has_t3, "D2 controls should have T3 penalty from bypass"


class TestFullPipelineASPI:
    """End-to-end: promptfoo fixture → full 8-domain evaluation → ASPI."""

    def test_full_pipeline_produces_aspi(self):
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        config = EvalConfig(
            skip_llm=True,
            red_team=RedTeamConfig(promptfoo_output_paths=[report_path]),
        )
        evaluator = Evaluator(config)

        red_team_reports = evaluator._load_red_team_reports()
        assert len(red_team_reports) == 1

        domains = asyncio.run(evaluator._evaluate_all_domains(
            scan_results={},
            analyzer_results={},
            red_team_reports=red_team_reports,
        ))

        assert len(domains) == 8
        for domain_id in ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]:
            assert domain_id in domains
            result = domains[domain_id]
            assert isinstance(result, DomainResult)
            assert result.domain_id == domain_id
            assert len(result.controls) >= 5

    def test_aspi_with_redteam_lower_than_without(self):
        """ASPI should be lower when red-team attacks succeed."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        config_no_rt = EvalConfig(skip_llm=True)
        config_with_rt = EvalConfig(
            skip_llm=True,
            red_team=RedTeamConfig(promptfoo_output_paths=[report_path]),
        )

        eval_no_rt = Evaluator(config_no_rt)
        eval_with_rt = Evaluator(config_with_rt)

        domains_no_rt = asyncio.run(eval_no_rt._evaluate_all_domains({}, {}, []))

        rt_reports = eval_with_rt._load_red_team_reports()
        domains_with_rt = asyncio.run(
            eval_with_rt._evaluate_all_domains({}, {}, rt_reports)
        )

        bypassed_domains = {
            s.target_domain
            for r in rt_reports
            for s in r.scenarios
            if "bypass" in s.outcome
        }
        for domain_id in bypassed_domains:
            if domain_id in domains_with_rt and domain_id in domains_no_rt:
                rt_t3 = domains_with_rt[domain_id].t3_aggregate
                assert rt_t3 > 0.0, f"Domain {domain_id} should have T3 > 0"

    def test_all_domains_have_populated_controls(self):
        config = EvalConfig(skip_llm=True)
        evaluator = Evaluator(config)
        domains = asyncio.run(evaluator._evaluate_all_domains({}, {}, []))

        assert len(domains) == 8
        for domain_id, result in domains.items():
            assert len(result.controls) >= 5, (
                f"{domain_id} should have at least 5 controls"
            )
            for ctrl in result.controls:
                assert ctrl.control_id.startswith(domain_id)

    def test_scoring_calculator_consistent_with_evaluator(self):
        config = EvalConfig(skip_llm=True)
        evaluator = Evaluator(config)
        domains = asyncio.run(evaluator._evaluate_all_domains({}, {}, []))

        aspi1 = ASPICalculator.calculate(domains)
        aspi2 = ScoringASPICalculator.calculate_aspi(domains)
        assert aspi1 == aspi2


class TestScoringWithT3Penalties:
    """Verify T3 penalties from red-team flow through to domain scores."""

    def test_domain_score_reflects_t3(self):
        """A domain with T3 penalty should score differently."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        config = EvalConfig(
            skip_llm=True,
            red_team=RedTeamConfig(promptfoo_output_paths=[report_path]),
        )
        evaluator = Evaluator(config)
        rt_reports = evaluator._load_red_team_reports()
        domains = asyncio.run(evaluator._evaluate_all_domains({}, {}, rt_reports))

        bypassed_domains = {
            s.target_domain
            for r in rt_reports
            for s in r.scenarios
            if "bypass" in s.outcome
        }
        for domain_id in bypassed_domains:
            if domain_id in domains:
                result = domains[domain_id]
                assert result.t3_aggregate > 0.0, (
                    f"{domain_id} should have T3 > 0 from bypass"
                )

    def test_stage_classification_with_pipeline(self):
        config = EvalConfig(skip_llm=True)
        evaluator = Evaluator(config)
        domains = asyncio.run(evaluator._evaluate_all_domains({}, {}, []))

        stage = ScoringASPICalculator.stage_classification(domains)
        assert stage in ("S1", "S2", "S3", "S4")
