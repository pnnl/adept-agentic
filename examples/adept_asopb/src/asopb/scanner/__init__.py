"""
ASOPB Scanner Registry and Loader

Provides auto-discovery and management of all Layer 1 scanners.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Type

from asopb.scanner.base import ScannerBase


class ScannerRegistry:
    """Auto-discovers and manages scanner classes.

    Scanners are automatically discovered from the scanner package
    and indexed by name for easy lookup and batch execution.
    """

    def __init__(self):
        """Initialize the registry."""
        self._scanners: dict[str, Type[ScannerBase]] = {}
        self._discover()

    def _discover(self) -> None:
        """Auto-discover all scanner classes in this package."""
        scanner_dir = Path(__file__).parent

        # Exclude the base class and __init__
        exclude = {"base.py", "__init__.py"}

        for module_file in sorted(scanner_dir.glob("*.py")):
            if module_file.name in exclude:
                continue

            module_name = module_file.stem
            try:
                module = importlib.import_module(f"asopb.scanner.{module_name}")

                # Find all ScannerBase subclasses in the module
                for name, obj in inspect.getmembers(module):
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, ScannerBase)
                        and obj is not ScannerBase
                    ):
                        self._scanners[obj.name] = obj
            except (ImportError, AttributeError):
                # Skip modules that fail to import
                pass

    def get(self, name: str) -> Type[ScannerBase] | None:
        """Get a scanner class by name."""
        return self._scanners.get(name)

    def all(self) -> dict[str, Type[ScannerBase]]:
        """Return all registered scanner classes."""
        return dict(self._scanners)

    def list_names(self) -> list[str]:
        """Return sorted list of all registered scanner names."""
        return sorted(self._scanners.keys())


# Global registry instance
_registry = ScannerRegistry()


def get_registry() -> ScannerRegistry:
    """Get the global scanner registry."""
    return _registry


def get_scanner(name: str) -> Type[ScannerBase] | None:
    """Convenience function to get a scanner class."""
    return _registry.get(name)


# Explicit imports for direct access
from asopb.scanner.auth import AuthScanner
from asopb.scanner.codebase import CodebaseScanner
from asopb.scanner.federation import FederationScanner
from asopb.scanner.itot import ITOTScanner
from asopb.scanner.observability import ObservabilityScanner
from asopb.scanner.sandbox import SandboxScanner
from asopb.scanner.supply_chain import SupplyChainScanner
from asopb.scanner.tools import ToolScanner

__all__ = [
    "ScannerRegistry",
    "get_registry",
    "get_scanner",
    "AuthScanner",
    "CodebaseScanner",
    "FederationScanner",
    "ITOTScanner",
    "ObservabilityScanner",
    "SandboxScanner",
    "SupplyChainScanner",
    "ToolScanner",
]
