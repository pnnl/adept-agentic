"""
ASOPB Import Validation

Verifies all public exports are importable and key module interfaces are intact.
Used by Makefile target 'test-all-container' for pre-test validation.

Exit 0 on success, 1 on import failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def validate_imports() -> bool:
    """Validate all critical ASOPB imports."""
    errors = []

    try:
        from asopb.config import EvalConfig, RedTeamConfig
    except ImportError as e:
        errors.append(f"config: {e}")

    try:
        from asopb.redteam import PromptfooIngester, ReportIngesterBase, RedTeamRegistry
    except ImportError as e:
        errors.append(f"redteam: {e}")

    try:
        from asopb.redteam.promptfoo_ingester import (
            build_azure_category_map,
            build_adept_category_map,
            OWASP_DOMAIN_MAP,
            ADEPT_DOMAIN_MAP,
        )
    except ImportError as e:
        errors.append(f"promptfoo_ingester maps: {e}")

    try:
        from asopb.domains.registry import DomainRegistry
    except ImportError as e:
        errors.append(f"domains.registry: {e}")

    try:
        from asopb.evaluator import Evaluator, ASPICalculator
    except ImportError as e:
        errors.append(f"evaluator: {e}")

    try:
        from asopb.scoring import ASPICalculator as ScoringASPICalculator
    except ImportError as e:
        errors.append(f"scoring: {e}")

    try:
        from asopb.models import (
            RedTeamReport,
            RedTeamScenario,
            DomainResult,
            ControlScore,
            EvaluationReport,
        )
    except ImportError as e:
        errors.append(f"models: {e}")

    try:
        from asopb.aivss import AIVSSCalculator, AgentProfileBuilder
    except ImportError as e:
        errors.append(f"aivss: {e}")

    if errors:
        print("IMPORT VALIDATION FAILED:")
        for err in errors:
            print(f"  - {err}")
        return False

    # Summary
    print(f"Imports OK: {len(OWASP_DOMAIN_MAP)} OWASP + {len(ADEPT_DOMAIN_MAP)} ADEPT categories")
    cfg = RedTeamConfig(promptfoo_output_paths=[Path("/tmp/test.json")])
    print(f"RedTeamConfig.promptfoo_output_paths: {cfg.promptfoo_output_paths}")

    registry = DomainRegistry(EvalConfig())
    evaluators = registry.get_all_evaluators()
    print(f"DomainRegistry: {len(evaluators)} evaluators registered")

    return True


if __name__ == "__main__":
    success = validate_imports()
    sys.exit(0 if success else 1)
