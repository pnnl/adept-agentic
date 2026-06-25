#!/usr/bin/env bash
# validate-yaml-offline.sh — Offline SkyPilot YAML validation
#
# Validates task YAMLs without cloud credentials:
#   1. YAML syntax (yamllint)
#   2. Shell syntax in setup/run blocks (bash -n)
#   3. Required set -euo pipefail in shell blocks
#
# Usage:
#   ./scripts/validate-yaml-offline.sh [yaml_dir]
#   Default: /app/skypilot/tasks/

set -euo pipefail

YAML_DIR="${1:-/app/skypilot/tasks}"
ERRORS=0

echo "============================================"
echo "SkyPilot YAML Offline Validation"
echo "============================================"

# --- 1. YAML Syntax ---
echo ""
echo "--- Step 1: YAML Syntax (yamllint) ---"

YAMLLINT_CONFIG=$(cat <<'YLCFG'
extends: relaxed
rules:
  line-length: {max: 200}
  truthy: disable
  comments-indentation: disable
YLCFG
)

for yaml_file in "$YAML_DIR"/*.yaml; do
  filename=$(basename "$yaml_file")
  echo -n "  ${filename}: "
  if echo "$YAMLLINT_CONFIG" | yamllint -c /dev/stdin "$yaml_file" 2>&1; then
    echo "PASS"
  else
    echo "FAIL"
    ERRORS=$((ERRORS + 1))
  fi
done

# --- 2. Shell Syntax ---
echo ""
echo "--- Step 2: Shell Syntax (bash -n) ---"

for yaml_file in "$YAML_DIR"/*.yaml; do
  filename=$(basename "$yaml_file")
  for block in setup run; do
    echo -n "  ${filename} [${block}]: "
    # Extract shell block from YAML
    SHELL_BLOCK=$(python3 -c "
import yaml, sys
with open('${yaml_file}') as f:
    data = yaml.safe_load(f)
block = data.get('${block}', '')
if block:
    print(block)
else:
    sys.exit(1)
" 2>/dev/null) || { echo "SKIP (no ${block} block)"; continue; }

    # Validate with bash -n
    if echo "$SHELL_BLOCK" | bash -n 2>&1; then
      echo "PASS"
    else
      echo "FAIL"
      ERRORS=$((ERRORS + 1))
    fi
  done
done

# --- 3. Required Patterns ---
echo ""
echo "--- Step 3: Required Shell Patterns ---"

for yaml_file in "$YAML_DIR"/*.yaml; do
  filename=$(basename "$yaml_file")

  # Check for set -euo pipefail in setup block
  echo -n "  ${filename} [set -euo pipefail in setup]: "
  if grep -q 'set -euo pipefail' "$yaml_file"; then
    echo "PASS"
  else
    echo "FAIL — setup block must start with 'set -euo pipefail'"
    ERRORS=$((ERRORS + 1))
  fi

  # Check for make start in run block
  echo -n "  ${filename} [make start in run]: "
  if grep -q 'make start' "$yaml_file"; then
    echo "PASS"
  else
    echo "FAIL — run block must call 'make start'"
    ERRORS=$((ERRORS + 1))
  fi

  # Check for validate-service-health in run block
  echo -n "  ${filename} [health check in run]: "
  if grep -q 'validate-service-health' "$yaml_file"; then
    echo "PASS"
  else
    echo "FAIL — run block must call 'make validate-service-health'"
    ERRORS=$((ERRORS + 1))
  fi
done

# --- Summary ---
echo ""
echo "============================================"
if [ $ERRORS -eq 0 ]; then
  echo "ALL CHECKS PASSED"
  exit 0
else
  echo "FAILED: ${ERRORS} check(s) failed"
  exit 1
fi
