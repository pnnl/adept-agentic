#!/usr/bin/env python3
"""Validate parity between _DEFAULT_MODEL_ENV_VARS and config/llm.yaml.example.

Checks:
1. Every purpose in _DEFAULT_MODEL_ENV_VARS has a corresponding entry in llm.yaml.example
2. Every provider key in llm.yaml.example is a valid ProviderType enum value
3. defaults.provider is a valid ProviderType
4. Every purpose in llm.yaml.example has a description field
5. fallback.provider (if set) is a valid ProviderType

Exit codes:
  0 = all checks pass
  1 = parity violations found

Usage:
    python scripts/config/validate_config_parity.py
    make validate-config-parity
"""

import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agentic_framework_pkg.core.llm_config import (
    ProviderType,
    _DEFAULT_MODEL_ENV_VARS,
)


def main() -> int:
    yaml_example = PROJECT_ROOT / "config" / "llm.yaml.example"
    if not yaml_example.exists():
        print(f"FAIL: {yaml_example} does not exist")
        return 1

    with open(yaml_example) as f:
        config = yaml.safe_load(f)

    if not config or not isinstance(config, dict):
        print(f"FAIL: {yaml_example} is empty or not a mapping")
        return 1

    failures = []

    # Check 1: All purposes from _DEFAULT_MODEL_ENV_VARS are in example
    yaml_purposes = set(config.get("purposes", {}).keys())
    code_purposes = set(_DEFAULT_MODEL_ENV_VARS.keys())

    missing_in_yaml = code_purposes - yaml_purposes
    if missing_in_yaml:
        failures.append(
            f"Purposes in _DEFAULT_MODEL_ENV_VARS but missing from llm.yaml.example: "
            f"{sorted(missing_in_yaml)}"
        )

    extra_in_yaml = yaml_purposes - code_purposes
    if extra_in_yaml:
        # Advisory only — YAML can define extra purposes (domain-specific)
        print(f"INFO: Extra purposes in llm.yaml.example (not in code): {sorted(extra_in_yaml)}")

    # Check 2: All provider keys are valid ProviderType values
    yaml_providers = set(config.get("providers", {}).keys())
    valid_providers = {e.value for e in ProviderType}
    invalid_providers = yaml_providers - valid_providers
    if invalid_providers:
        failures.append(
            f"Invalid provider keys in llm.yaml.example: {sorted(invalid_providers)}. "
            f"Valid: {sorted(valid_providers)}"
        )

    # Check 3: Defaults provider is valid
    defaults = config.get("defaults", {})
    if defaults.get("provider") and defaults["provider"] not in valid_providers:
        failures.append(
            f"defaults.provider '{defaults['provider']}' is not a valid ProviderType"
        )

    # Check 4: Every purpose has a description
    purposes_missing_desc = []
    for name, cfg in config.get("purposes", {}).items():
        if not cfg or not cfg.get("description"):
            purposes_missing_desc.append(name)
    if purposes_missing_desc:
        failures.append(
            f"Purposes missing 'description' field: {sorted(purposes_missing_desc)}"
        )

    # Check 5: Fallback provider is valid
    fallback = config.get("fallback", {})
    if fallback and fallback.get("provider") and fallback["provider"] not in valid_providers:
        failures.append(
            f"fallback.provider '{fallback['provider']}' is not a valid ProviderType"
        )

    if failures:
        print("CONFIG PARITY FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"PASS: {len(yaml_purposes)} purposes, {len(yaml_providers)} providers — all valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
