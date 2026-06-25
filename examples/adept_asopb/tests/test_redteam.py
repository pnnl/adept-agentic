"""
Unit tests for red-team plugin system.

Tests:
- RedTeamPluginBase and SimulatorPluginBase construction
- RedTeamRegistry plugin registration
- Entry point discovery (mocked)
- Generic report ingestion
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from asopb.models import FrameworkVersion, RedTeamReport, RedTeamScenario
from asopb.redteam.base import (
    ReportIngesterBase,
    RedTeamPluginBase,
    RedTeamRegistry,
    SimulatorPluginBase,
)


# Test implementations
class MockRedTeamPlugin(RedTeamPluginBase):
    """Mock red-team plugin for testing."""

    @property
    def name(self) -> str:
        return "mock_plugin"

    @property
    def description(self) -> str:
        return "Mock red-team plugin for testing"

    async def execute(
        self,
        repo_path: Path,
        config: dict[str, Any],
    ) -> RedTeamReport:
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
            outcome_description="Test outcome",
        )

        return RedTeamReport(
            report_id="mock-rt-001",
            source="mock_plugin",
            framework_version=framework,
            scenarios=[scenario],
        )


class MockSimulatorPlugin(SimulatorPluginBase):
    """Mock simulator plugin for testing."""

    @property
    def name(self) -> str:
        return "mock_simulator"

    @property
    def description(self) -> str:
        return "Mock Simulator for testing"

    async def setup_environment(self, repo_path: Path) -> None:
        """Setup test environment."""
        pass

    async def teardown_environment(self, repo_path: Path) -> None:
        """Teardown test environment."""
        pass

    async def _run_simulation(
        self,
        repo_path: Path,
        config: dict[str, Any],
    ) -> RedTeamReport:
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

        scenario = RedTeamScenario(
            scenario_id="SIM-1",
            scenario_name="Simulated Attack",
            attack_vector="Simulated vector",
            target_domain="D1",
            outcome="partial_bypass",
            outcome_description="Simulator outcome",
            t3_score_contribution=3.0,
        )

        return RedTeamReport(
            report_id="mock-sim-001",
            source="mock_simulator",
            framework_version=framework,
            scenarios=[scenario],
        )


class MockReportIngester(ReportIngesterBase):
    """Mock report ingester for testing."""

    @property
    def name(self) -> str:
        return "mock_ingester"

    @property
    def description(self) -> str:
        return "Mock Ingester for testing"

    def ingest(self, report_path: Path) -> RedTeamReport:
        """Ingest mock JSON report."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

        scenario = RedTeamScenario(
            scenario_id="INGESTED-1",
            scenario_name="Ingested Report",
            attack_vector="External vector",
            target_domain="D5",
            outcome="full_bypass",
            outcome_description="Ingested outcome",
            t3_score_contribution=8.0,
        )

        return RedTeamReport(
            report_id="ingested-rt-001",
            source="mock_ingester",
            framework_version=framework,
            scenarios=[scenario],
        )


class TestRedTeamPluginBase:
    """Tests for RedTeamPluginBase."""

    @pytest.mark.asyncio
    async def test_plugin_execute(self, tmp_path: Path):
        """Test plugin execution."""
        plugin = MockRedTeamPlugin()

        report = await plugin.execute(tmp_path, {})

        assert report.report_id == "mock-rt-001"
        assert report.source == "mock_plugin"
        assert len(report.scenarios) == 1
        assert report.scenarios[0].scenario_id == "RT-1"

    def test_plugin_metadata(self):
        """Test plugin metadata."""
        plugin = MockRedTeamPlugin()

        assert plugin.name == "mock_plugin"
        assert "Mock" in plugin.description


class TestSimulatorPluginBase:
    """Tests for SimulatorPluginBase."""

    @pytest.mark.asyncio
    async def test_simulator_execute_with_lifecycle(self, tmp_path: Path):
        """Test simulator execution with setup/teardown."""
        simulator = MockSimulatorPlugin()

        # Execute should call setup -> _run_simulation -> teardown
        report = await simulator.execute(tmp_path, {})

        assert report.report_id == "mock-sim-001"
        assert report.source == "mock_simulator"
        assert len(report.scenarios) == 1
        assert report.scenarios[0].scenario_id == "SIM-1"

    def test_simulator_metadata(self):
        """Test simulator metadata."""
        simulator = MockSimulatorPlugin()

        assert simulator.name == "mock_simulator"
        assert "Simulator" in simulator.description


class TestReportIngesterBase:
    """Tests for ReportIngesterBase."""

    def test_ingester_ingest(self, tmp_path: Path):
        """Test report ingestion."""
        ingester = MockReportIngester()

        report_path = tmp_path / "mock_report.json"
        report_path.write_text("{}")  # Content doesn't matter for mock

        report = ingester.ingest(report_path)

        assert report.report_id == "ingested-rt-001"
        assert report.source == "mock_ingester"
        assert len(report.scenarios) == 1
        assert report.scenarios[0].outcome == "full_bypass"

    def test_ingester_metadata(self):
        """Test ingester metadata."""
        ingester = MockReportIngester()

        assert ingester.name == "mock_ingester"
        assert "Ingester" in ingester.description


class TestRedTeamRegistry:
    """Tests for RedTeamRegistry."""

    def test_registry_register_plugin(self):
        """Test registering a plugin."""
        registry = RedTeamRegistry()

        registry.register_plugin(MockRedTeamPlugin)

        plugins = registry.list_plugins()
        assert "mock_plugin" in plugins

    def test_registry_register_ingester(self):
        """Test registering an ingester."""
        registry = RedTeamRegistry()

        registry.register_ingester(MockReportIngester)

        ingesters = registry.list_ingesters()
        assert "mock_ingester" in ingesters

    def test_registry_multiple_plugins(self):
        """Test registering multiple plugins."""
        registry = RedTeamRegistry()

        registry.register_plugin(MockRedTeamPlugin)
        registry.register_plugin(MockSimulatorPlugin)

        plugins = registry.list_plugins()
        assert len(plugins) >= 2
        assert "mock_plugin" in plugins
        assert "mock_simulator" in plugins

    @pytest.mark.asyncio
    async def test_registry_run_simulators(self, tmp_path: Path):
        """Test running simulators from registry."""
        registry = RedTeamRegistry()

        registry.register_plugin(MockSimulatorPlugin)

        reports = await registry.run_simulators(tmp_path, {})

        assert len(reports) == 1
        assert reports[0].report_id == "mock-sim-001"

    @pytest.mark.asyncio
    async def test_registry_run_simulators_empty(self, tmp_path: Path):
        """Test running simulators when none registered."""
        registry = RedTeamRegistry()

        reports = await registry.run_simulators(tmp_path, {})

        assert len(reports) == 0

    def test_registry_load_report_with_ingester(self, tmp_path: Path):
        """Test loading report via ingester."""
        registry = RedTeamRegistry()

        registry.register_ingester(MockReportIngester)

        report_path = tmp_path / "test_report.json"
        report_path.write_text("{}")

        report = registry.load_report(report_path)

        assert report.report_id == "ingested-rt-001"
        assert report.source == "mock_ingester"

    def test_registry_load_report_no_ingester(self, tmp_path: Path):
        """Test loading report fails without matching ingester."""
        registry = RedTeamRegistry()

        report_path = tmp_path / "test_report.json"
        report_path.write_text("{}")

        with pytest.raises(ValueError):
            registry.load_report(report_path)


class TestRedTeamIntegration:
    """Integration tests for red-team system."""

    @pytest.mark.asyncio
    async def test_red_team_workflow(self, tmp_path: Path):
        """Test complete red-team workflow."""
        registry = RedTeamRegistry()

        # Register plugin and ingester
        registry.register_plugin(MockRedTeamPlugin)
        registry.register_ingester(MockReportIngester)

        # Run plugin
        plugin_report = await registry.run_simulators(tmp_path, {})
        assert len(plugin_report) == 0  # MockRedTeamPlugin is not a simulator

        # Create and ingest external report
        report_path = tmp_path / "external_report.json"
        report_path.write_text("{}")

        ingested_report = registry.load_report(report_path)
        assert ingested_report.source == "mock_ingester"

    def test_registry_discover_plugins_empty(self):
        """Test discovering plugins when none available."""
        registry = RedTeamRegistry()

        # Mock entry points will be empty
        discovered = registry.discover_plugins()

        # Should return empty dict if no actual entry points
        assert isinstance(discovered, dict)

    def test_registry_discover_ingesters_empty(self):
        """Test discovering ingesters when none available."""
        registry = RedTeamRegistry()

        # Mock entry points will be empty
        discovered = registry.discover_ingesters()

        # Should return empty dict if no actual entry points
        assert isinstance(discovered, dict)


class TestRedTeamScenarioConstruction:
    """Tests for constructing red-team scenarios and reports."""

    def test_scenario_with_evidence(self):
        """Test creating scenario with evidence."""
        from asopb.models import ControlEvidence, EvidenceSource, EvidenceTier

        evidence = ControlEvidence(
            tier=EvidenceTier.T3_ADVERSARIAL,
            source=EvidenceSource.RED_TEAM,
            source_tool="red_team:attack",
            description="Attack succeeded",
            confidence=0.95,
        )

        scenario = RedTeamScenario(
            scenario_id="RT-1",
            scenario_name="Attack Test",
            attack_vector="Test vector",
            target_domain="D3",
            target_controls=["D3.1", "D3.2"],
            outcome="defense_held",
            outcome_description="Defense successful",
            evidence=[evidence],
            t3_score_contribution=6.0,
        )

        assert len(scenario.evidence) == 1
        assert scenario.evidence[0].confidence == 0.95

    def test_red_team_report_with_multiple_scenarios(self):
        """Test creating report with multiple scenarios."""
        framework = FrameworkVersion(
            name="test-framework",
            version="1.0.0",
        )

        scenarios = [
            RedTeamScenario(
                scenario_id="RT-1",
                scenario_name="Attack 1",
                attack_vector="Vector 1",
                target_domain="D1",
                outcome="defense_held",
                outcome_description="Description 1",
            ),
            RedTeamScenario(
                scenario_id="RT-2",
                scenario_name="Attack 2",
                attack_vector="Vector 2",
                target_domain="D3",
                target_controls=["D3.1"],
                outcome="partial_bypass",
                outcome_description="Description 2",
                t3_score_contribution=4.0,
            ),
        ]

        report = RedTeamReport(
            report_id="rt-full-001",
            source="test-team",
            framework_version=framework,
            scenarios=scenarios,
        )

        assert len(report.scenarios) == 2
        assert report.scenarios[0].scenario_id == "RT-1"
        assert report.scenarios[1].t3_score_contribution == 4.0
