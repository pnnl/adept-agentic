"""
Domain Registry

Registers all ASOPB domain evaluators (D1–D8) and manages control definitions.
Merges built-in controls with custom YAML-based controls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from asopb.config import EvalConfig
from asopb.models import ControlDefinition, ScanResult

from .base import DomainEvaluator
from .d1_model_integrity import D1ModelIntegrityEvaluator
from .d2_orchestration import D2OrchestrationEvaluator
from .d3_tool_security import D3ToolSecurityEvaluator
from .d4_identity import D4IdentityEvaluator
from .d5_federation import D5FederationEvaluator
from .d6_observability import D6ObservabilityEvaluator
from .d7_itot import D7ItOtEvaluator
from .d8_supply_chain import D8SupplyChainEvaluator


class DomainRegistry:
    """Registry for all ASOPB domain evaluators.

    Manages:
      - Domain evaluator instances
      - Control definitions (built-in + custom)
      - Filtering by applicability and config
    """

    def __init__(self, config: EvalConfig, llm_client: Any = None):
        """Initialize the domain registry.

        Args:
            config: EvalConfig with domain weights, custom controls path, etc.
            llm_client: Optional LLM client for T1 enhancement
        """
        self.config = config
        self.llm_client = llm_client

        # Instantiate all domain evaluators
        self._evaluators: dict[str, DomainEvaluator] = {
            "D1": D1ModelIntegrityEvaluator(config, llm_client),
            "D2": D2OrchestrationEvaluator(config, llm_client),
            "D3": D3ToolSecurityEvaluator(config, llm_client),
            "D4": D4IdentityEvaluator(config, llm_client),
            "D5": D5FederationEvaluator(config, llm_client),
            "D6": D6ObservabilityEvaluator(config, llm_client),
            "D7": D7ItOtEvaluator(config, llm_client),
            "D8": D8SupplyChainEvaluator(config, llm_client),
        }

        # Merge custom controls from YAML if provided
        self._custom_controls: dict[str, ControlDefinition] = {}
        if config.scoring.custom_controls_path:
            self._load_custom_controls(config.scoring.custom_controls_path)

    def _load_custom_controls(self, controls_path: Path) -> None:
        """Load custom control definitions from a YAML file.

        YAML format:
          controls:
            - control_id: "D4.7"
              domain_id: "D4"
              name: "Custom Control"
              description: "..."
              severity: "high"
              t1_criteria: [...]
              ...
        """
        try:
            import yaml
            with open(controls_path) as f:
                data = yaml.safe_load(f) or {}

            for control_data in data.get("controls", []):
                control = ControlDefinition(**control_data)
                self._custom_controls[control.control_id] = control
        except Exception as e:
            if self.config.verbose:
                print(f"Warning: Failed to load custom controls from {controls_path}: {e}")

    def get_evaluator(self, domain_id: str) -> Optional[DomainEvaluator]:
        """Get a domain evaluator by ID."""
        return self._evaluators.get(domain_id)

    def get_all_evaluators(self) -> list[DomainEvaluator]:
        """Get all registered evaluators."""
        return list(self._evaluators.values())

    def get_applicable_evaluators(
        self,
        scan_results: dict[str, ScanResult],
    ) -> list[DomainEvaluator]:
        """Get evaluators that are applicable to the target system.

        Filters by:
          1. config.domains_to_evaluate (if specified)
          2. Evaluator-specific applicability checks

        Returns evaluators in domain order (D1–D8).
        """
        evaluators = []

        for domain_id in ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]:
            evaluator = self._evaluators.get(domain_id)
            if not evaluator:
                continue

            # Check config filter
            if self.config.scoring.domains_to_evaluate:
                if domain_id not in self.config.scoring.domains_to_evaluate:
                    continue

            # Check domain applicability
            applicability = evaluator.check_applicability(scan_results)
            from asopb.models import Applicability
            if applicability == Applicability.NOT_APPLICABLE:
                continue

            evaluators.append(evaluator)

        return evaluators

    def get_control_definitions(self, domain_id: str) -> list[ControlDefinition]:
        """Get all control definitions for a domain (built-in + custom).

        Returns built-in controls for the domain, merged with any custom
        controls that belong to the same domain.
        """
        evaluator = self._evaluators.get(domain_id)
        if not evaluator:
            return []

        # Get built-in controls
        controls = evaluator.define_controls()

        # Merge custom controls for this domain
        for control_id, custom_control in self._custom_controls.items():
            if custom_control.domain_id == domain_id:
                # Replace built-in control if it exists, otherwise append
                found = False
                for i, built_in in enumerate(controls):
                    if built_in.control_id == control_id:
                        controls[i] = custom_control
                        found = True
                        break
                if not found:
                    controls.append(custom_control)

        return controls

    def get_all_control_definitions(self) -> dict[str, ControlDefinition]:
        """Get all control definitions (built-in + custom) as a flat dict."""
        all_controls: dict[str, ControlDefinition] = {}

        for domain_id in ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]:
            for control in self.get_control_definitions(domain_id):
                all_controls[control.control_id] = control

        return all_controls

    def get_domain_weight(self, domain_id: str) -> float:
        """Get the weight for a domain (from config or evaluator default)."""
        evaluator = self._evaluators.get(domain_id)
        if not evaluator:
            return 1.0

        # Config weights override evaluator defaults
        if domain_id in self.config.scoring.domain_weights:
            return self.config.scoring.domain_weights[domain_id]

        return evaluator.weight
