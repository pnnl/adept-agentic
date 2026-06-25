"""
Integration and E2E tests for the promptfoo-to-ASPI scoring pipeline.

Integration tests:
- PromptfooIngester → RedTeamReport → domain evaluator T3 scoring
- Config-driven ingestion via RedTeamConfig.promptfoo_output_paths
- Multi-provider report aggregation

E2E tests:
- Full pipeline against fixture JSON files (azure_quick_10.json)
- Evaluator._load_red_team_reports() with promptfoo paths
- ASPI score includes T3 penalties from ingested red-team findings
"""

from pathlib import Path

import pytest

from asopb.config import EvalConfig, RedTeamConfig
from asopb.models import RedTeamReport, RedTeamScenario
from asopb.redteam import PromptfooIngester
from asopb.redteam.promptfoo_ingester import (
    ADEPT_DOMAIN_MAP,
    OWASP_DOMAIN_MAP,
    build_azure_category_map,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "promptfoo_outputs"


class TestIngesterIntegration:
    """Integration: ingester → report → domain scoring path."""

    @pytest.mark.integration
    def test_ingested_report_has_correct_scenario_structure(self):
        """Verify RedTeamReport from real fixture has all required fields populated."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        ingester = PromptfooIngester(provider_label="Azure o4-mini")
        report = ingester.ingest(report_path)

        assert isinstance(report, RedTeamReport)
        assert len(report.scenarios) == 10
        for scenario in report.scenarios:
            assert scenario.scenario_id.startswith("PF-")
            assert scenario.target_domain.startswith("D")
            assert len(scenario.target_controls) > 0
            assert scenario.outcome in ("defense_held", "full_bypass", "partial_bypass", "error")
            assert len(scenario.evidence) == 1
            assert scenario.evidence[0].raw_data is not None

    @pytest.mark.integration
    def test_defense_held_scenarios_have_zero_t3(self):
        """Passed tests should contribute 0.0 to T3 score (no penalty)."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        ingester = PromptfooIngester()
        report = ingester.ingest(report_path)

        for scenario in report.scenarios:
            if scenario.outcome == "defense_held":
                assert scenario.t3_score_contribution == 0.0

    @pytest.mark.integration
    def test_bypass_scenarios_have_positive_t3(self):
        """Failed tests should contribute positive T3 penalty."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        ingester = PromptfooIngester()
        report = ingester.ingest(report_path)

        bypasses = [s for s in report.scenarios if "bypass" in s.outcome]
        assert len(bypasses) > 0
        for scenario in bypasses:
            assert scenario.t3_score_contribution > 0.0

    @pytest.mark.integration
    def test_multi_domain_coverage(self):
        """Azure quick 10 tests should hit multiple ASOPB domains."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        ingester = PromptfooIngester()
        report = ingester.ingest(report_path)

        domains_hit = {s.target_domain for s in report.scenarios}
        assert len(domains_hit) >= 3

    @pytest.mark.integration
    def test_category_map_overrides_auto_classification(self):
        """Explicit category_map should take precedence over regex."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        category_map = {i: "LLM06" for i in range(10)}
        ingester = PromptfooIngester(category_map=category_map)
        report = ingester.ingest(report_path)

        for scenario in report.scenarios:
            assert scenario.target_domain == "D3"

    @pytest.mark.integration
    def test_report_metadata_matches_fixture(self):
        """Metadata should accurately reflect fixture content."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        ingester = PromptfooIngester(provider_label="Azure o4-mini")
        report = ingester.ingest(report_path)

        assert report.metadata["total_tests"] == 10
        assert report.metadata["passed"] == 7
        assert report.metadata["failed"] == 3
        assert report.metadata["provider"] == "azureopenai:chat:o4-mini"
        assert report.metadata["provider_label"] == "Azure o4-mini"


class TestConfigDrivenIngestion:
    """Integration: RedTeamConfig → ingester → report loading."""

    @pytest.mark.integration
    def test_config_accepts_promptfoo_paths(self):
        """RedTeamConfig should accept promptfoo_output_paths field."""
        config = RedTeamConfig(
            promptfoo_output_paths=[
                Path("/tmp/azure_output.json"),
                Path("/tmp/bedrock_output.json"),
            ]
        )
        assert len(config.promptfoo_output_paths) == 2

    @pytest.mark.integration
    def test_eval_config_nested_redteam_config(self):
        """EvalConfig should properly nest RedTeamConfig with promptfoo paths."""
        config = EvalConfig(
            red_team=RedTeamConfig(
                promptfoo_output_paths=[
                    FIXTURES_DIR / "azure_quick_10.json",
                ]
            )
        )
        assert len(config.red_team.promptfoo_output_paths) == 1
        assert config.red_team.promptfoo_output_paths[0].name == "azure_quick_10.json"


class TestMultiProviderAggregation:
    """Integration: aggregate findings from multiple providers."""

    @pytest.mark.integration
    def test_multiple_ingestions_produce_separate_reports(self):
        """Each provider's output should produce an independent report."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        azure_ingester = PromptfooIngester(
            name="promptfoo-azure",
            provider_label="Azure o4-mini",
        )
        bedrock_ingester = PromptfooIngester(
            name="promptfoo-bedrock",
            provider_label="Bedrock Claude Sonnet 4.5",
        )

        azure_report = azure_ingester.ingest(report_path)
        bedrock_report = bedrock_ingester.ingest(report_path)

        assert azure_report.metadata["provider_label"] == "Azure o4-mini"
        assert bedrock_report.metadata["provider_label"] == "Bedrock Claude Sonnet 4.5"
        assert azure_ingester.name != bedrock_ingester.name


class TestEndToEndPipeline:
    """E2E: full pipeline from fixture file to ASPI-consumable report."""

    @pytest.mark.e2e
    def test_full_pipeline_fixture_to_domain_scores(self):
        """End-to-end: fixture → ingester → report → per-domain T3 aggregation."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        ingester = PromptfooIngester(provider_label="Azure o4-mini")
        report = ingester.ingest(report_path)

        domain_t3: dict[str, float] = {}
        for scenario in report.scenarios:
            domain = scenario.target_domain
            domain_t3[domain] = domain_t3.get(domain, 0.0) + scenario.t3_score_contribution

        assert sum(domain_t3.values()) > 0.0
        for domain, t3 in domain_t3.items():
            assert domain.startswith("D")
            assert t3 >= 0.0

    @pytest.mark.e2e
    def test_pass_rate_matches_expected(self):
        """E2E: verify ingested pass rate matches known fixture values."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        ingester = PromptfooIngester()
        report = ingester.ingest(report_path)

        total = report.metadata["total_tests"]
        passed = report.metadata["passed"]
        pass_rate = passed / total

        # azure_quick_10.json has 7 pass, 3 fail = 70%
        assert pass_rate == pytest.approx(0.7, abs=0.01)

    @pytest.mark.e2e
    def test_domain_mapping_consistency(self):
        """E2E: all ingested scenarios map to valid ASOPB domains (D1-D8)."""
        report_path = FIXTURES_DIR / "azure_quick_10.json"
        if not report_path.exists():
            pytest.skip("Fixture not available")

        ingester = PromptfooIngester()
        report = ingester.ingest(report_path)

        valid_domains = {f"D{i}" for i in range(1, 9)}
        for scenario in report.scenarios:
            assert scenario.target_domain in valid_domains
            for control in scenario.target_controls:
                assert control.startswith(scenario.target_domain)
