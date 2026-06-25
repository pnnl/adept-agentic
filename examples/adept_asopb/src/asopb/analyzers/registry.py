"""
Analyzer Registry

Manages analyzer lifecycle: registration, discovery, and orchestration.
Provides a unified interface to discover available analyzers and run them
against a repository.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from asopb.analyzers.base import AnalyzerBase
from asopb.models import ScanResult


class AnalyzerRegistry:
    """Manages analyzer lifecycle and orchestration.

    The registry maintains a set of available analyzers and provides methods
    to discover which ones are installed, run all available analyzers against
    a repository, and retrieve specific analyzers by name.

    This class is typically instantiated once per evaluation run and shared
    across the pipeline.
    """

    def __init__(self):
        """Initialize the registry with an empty analyzer set."""
        self._analyzers: dict[str, type[AnalyzerBase]] = {}
        self._instances: dict[str, AnalyzerBase] = {}

    def register(self, analyzer_cls: type[AnalyzerBase]) -> None:
        """Register an analyzer class.

        Args:
            analyzer_cls: Analyzer class (must subclass AnalyzerBase)

        Raises:
            TypeError: If analyzer_cls does not subclass AnalyzerBase
        """
        if not issubclass(analyzer_cls, AnalyzerBase):
            raise TypeError(f"{analyzer_cls.__name__} must subclass AnalyzerBase")
        self._analyzers[analyzer_cls.name] = analyzer_cls

    def discover_available(self, repo_path: Path, timeout: int = 300) -> list[AnalyzerBase]:
        """Discover which analyzers are available on this system.

        Instantiates each registered analyzer and checks is_available().
        Caches instances for later use via get().

        Args:
            repo_path: Path to the repository to analyze (resolved to absolute path)
            timeout: Timeout in seconds for analyzer subprocess commands

        Returns:
            List of available analyzer instances, ordered by registration
        """
        available = []
        for name, analyzer_cls in self._analyzers.items():
            instance = analyzer_cls(repo_path.resolve(), timeout=timeout)
            self._instances[name] = instance
            if instance.is_available():
                available.append(instance)
        return available

    async def run_all(self, repo_path: Path, timeout: int = 300) -> dict[str, ScanResult]:
        """Run all available analyzers against the repository.

        Discovers available analyzers, runs each one, and returns a dict
        mapping analyzer names to their results.

        Args:
            repo_path: Path to the repository
            timeout: Timeout in seconds for each analyzer

        Returns:
            Dict mapping analyzer names to ScanResult objects
        """
        available = self.discover_available(repo_path, timeout)
        results = {}
        for analyzer in available:
            result = await analyzer.analyze()
            results[analyzer.name] = result
        return results

    def get(self, name: str) -> Optional[AnalyzerBase]:
        """Get an analyzer instance by name.

        Returns a previously instantiated analyzer, or None if the analyzer
        has not been registered or instantiated.

        Args:
            name: Analyzer name (e.g., "semgrep", "bandit", "dockerfile")

        Returns:
            Analyzer instance if registered and instantiated, else None
        """
        return self._instances.get(name)
