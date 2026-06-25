"""
ASOPB Red-Team Plugin Factory

Abstract base classes and registry for red-team tools, attack simulators,
and external report ingesters. Implements plugin discovery and execution.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from asopb.models import RedTeamReport


class RedTeamPluginBase(ABC):
    """Abstract base class for red-team tools and simulators.

    Plugins implement attack scenarios, manual testing workflows, or
    automated attack simulations. All plugins support async execution
    in an isolated context.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this plugin.

        Returns:
            Plugin name (e.g., "prompt_injection", "federated_attack")
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of the plugin.

        Returns:
            Description string
        """
        pass

    @abstractmethod
    async def execute(
        self,
        repo_path: Path,
        config: dict[str, Any],
    ) -> RedTeamReport:
        """Execute the red-team attack or assessment.

        Args:
            repo_path: Path to the framework/agent code to assess
            config: Plugin-specific configuration dict

        Returns:
            RedTeamReport with scenario results and evidence
        """
        pass


class SimulatorPluginBase(RedTeamPluginBase):
    """Base class for automated attack simulators.

    Simulators manage environment setup/teardown and run deterministic
    or randomized attack sequences. They extend RedTeamPluginBase with
    lifecycle hooks for initialization and cleanup.
    """

    async def setup_environment(self, repo_path: Path) -> None:
        """Initialize the attack environment.

        Called before execute(). Simulators can use this to:
        - Instrument the code with logging
        - Set up mock services or test doubles
        - Prepare attack payload repositories
        - Enable debug modes

        Args:
            repo_path: Path to the framework code
        """
        pass

    async def teardown_environment(self, repo_path: Path) -> None:
        """Clean up the attack environment.

        Called after execute(). Simulators should:
        - Remove instrumentation
        - Shut down mock services
        - Clear temporary files
        - Disable debug modes

        Args:
            repo_path: Path to the framework code
        """
        pass

    async def execute(
        self,
        repo_path: Path,
        config: dict[str, Any],
    ) -> RedTeamReport:
        """Execute the simulator with lifecycle management.

        Calls setup_environment, runs the attack, then teardown_environment.

        Args:
            repo_path: Path to the framework code
            config: Simulator configuration

        Returns:
            RedTeamReport with results
        """
        try:
            await self.setup_environment(repo_path)
            report = await self._run_simulation(repo_path, config)
        finally:
            await self.teardown_environment(repo_path)
        return report

    @abstractmethod
    async def _run_simulation(
        self,
        repo_path: Path,
        config: dict[str, Any],
    ) -> RedTeamReport:
        """Run the attack simulation.

        Subclasses implement the actual attack logic here.

        Args:
            repo_path: Path to the framework code
            config: Simulator configuration

        Returns:
            RedTeamReport with results
        """
        pass


class ReportIngesterBase(ABC):
    """Abstract base class for importing external red-team JSON reports.

    Ingesters parse third-party red-team JSON outputs (e.g., from Gremlin,
    Chaos Monkey, or manual red-team teams) and transform them into
    standardized RedTeamReport objects.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this ingester.

        Returns:
            Ingester name (e.g., "gremlin", "chaos_monkey")
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description.

        Returns:
            Description string
        """
        pass

    @abstractmethod
    def ingest(self, report_path: Path) -> RedTeamReport:
        """Parse and ingest a red-team report file.

        Subclasses must transform the external JSON format into a
        RedTeamReport with proper control mappings and evidence.

        Args:
            report_path: Path to the external JSON report

        Returns:
            Standardized RedTeamReport
        """
        pass


class RedTeamRegistry:
    """Plugin registry and discovery system.

    Manages registration, discovery, and execution of red-team plugins
    and report ingesters. Supports both static registration and dynamic
    discovery via entry points.
    """

    def __init__(self) -> None:
        """Initialize the registry."""
        self._plugins: dict[str, type[RedTeamPluginBase]] = {}
        self._ingesters: dict[str, type[ReportIngesterBase]] = {}

    def register_plugin(self, cls: type[RedTeamPluginBase]) -> None:
        """Register a plugin class.

        Args:
            cls: Subclass of RedTeamPluginBase or SimulatorPluginBase
        """
        instance = cls()
        self._plugins[instance.name] = cls

    def register_ingester(self, cls: type[ReportIngesterBase]) -> None:
        """Register an ingester class.

        Args:
            cls: Subclass of ReportIngesterBase
        """
        instance = cls()
        self._ingesters[instance.name] = cls

    def discover_plugins(self) -> dict[str, type[RedTeamPluginBase]]:
        """Auto-discover plugins via entry points.

        Looks for entry point group "asopb.redteam.plugins" and dynamically
        imports all registered plugins.

        Returns:
            Dict mapping plugin name to plugin class
        """
        discovered = {}

        try:
            import importlib.metadata as importlib_metadata
        except ImportError:
            # Python < 3.8
            import importlib_metadata  # type: ignore

        try:
            entry_points = importlib_metadata.entry_points()
            # Handle both dict-like and list-like entry_points APIs
            if hasattr(entry_points, "select"):
                eps = entry_points.select(group="asopb.redteam.plugins")
            else:
                eps = entry_points.get("asopb.redteam.plugins", [])

            for ep in eps:
                try:
                    plugin_cls = ep.load()
                    if issubclass(
                        plugin_cls, RedTeamPluginBase
                    ) and plugin_cls not in [
                        RedTeamPluginBase,
                        SimulatorPluginBase,
                    ]:
                        instance = plugin_cls()
                        discovered[instance.name] = plugin_cls
                except Exception:
                    pass
        except Exception:
            pass

        return discovered

    def discover_ingesters(self) -> dict[str, type[ReportIngesterBase]]:
        """Auto-discover ingesters via entry points.

        Looks for entry point group "asopb.redteam.ingesters" and dynamically
        imports all registered ingesters.

        Returns:
            Dict mapping ingester name to ingester class
        """
        discovered = {}

        try:
            import importlib.metadata as importlib_metadata
        except ImportError:
            import importlib_metadata  # type: ignore

        try:
            entry_points = importlib_metadata.entry_points()
            # Handle both dict-like and list-like entry_points APIs
            if hasattr(entry_points, "select"):
                eps = entry_points.select(group="asopb.redteam.ingesters")
            else:
                eps = entry_points.get("asopb.redteam.ingesters", [])

            for ep in eps:
                try:
                    ingester_cls = ep.load()
                    if issubclass(
                        ingester_cls, ReportIngesterBase
                    ) and ingester_cls not in [ReportIngesterBase]:
                        instance = ingester_cls()
                        discovered[instance.name] = ingester_cls
                except Exception:
                    pass
        except Exception:
            pass

        return discovered

    def load_report(self, report_path: Path) -> RedTeamReport:
        """Load a red-team report via ingesters.

        Attempts to auto-detect the report format by trying all registered
        and discovered ingesters. Returns the first successful parse.

        Args:
            report_path: Path to the report file

        Returns:
            RedTeamReport

        Raises:
            ValueError: If no ingester can parse the report
        """
        ingesters = {**self._ingesters, **self.discover_ingesters()}

        for ingester_cls in ingesters.values():
            try:
                ingester = ingester_cls()
                return ingester.ingest(report_path)
            except Exception:
                continue

        raise ValueError(
            f"No ingester could parse report: {report_path}"
        )

    async def run_simulators(
        self,
        repo_path: Path,
        config: dict[str, Any],
    ) -> list[RedTeamReport]:
        """Run all registered simulator plugins.

        Discovers all SimulatorPluginBase subclasses and executes them
        concurrently against the target repository.

        Args:
            repo_path: Path to the framework code
            config: Configuration dict passed to all simulators

        Returns:
            List of RedTeamReport results
        """
        plugins = {**self._plugins, **self.discover_plugins()}
        simulators = [
            p
            for p in plugins.values()
            if issubclass(p, SimulatorPluginBase)
        ]

        if not simulators:
            return []

        tasks = [
            simulator_cls().execute(repo_path, config)
            for simulator_cls in simulators
        ]

        return await asyncio.gather(*tasks, return_exceptions=False)

    def list_plugins(self) -> dict[str, str]:
        """List all registered and discovered plugins.

        Returns:
            Dict mapping plugin name to description
        """
        all_plugins = {**self._plugins, **self.discover_plugins()}
        result = {}
        for name, cls in all_plugins.items():
            instance = cls()
            result[name] = instance.description
        return result

    def list_ingesters(self) -> dict[str, str]:
        """List all registered and discovered ingesters.

        Returns:
            Dict mapping ingester name to description
        """
        all_ingesters = {**self._ingesters, **self.discover_ingesters()}
        result = {}
        for name, cls in all_ingesters.items():
            instance = cls()
            result[name] = instance.description
        return result
