#!/bin/bash
#
# Import Validation Script
#
# Validates that all Python modules in src/ can be imported successfully.
# This catches import errors (ModuleNotFoundError, ImportError, etc.) before
# they reach production or even Docker builds.
#
# Usage:
#   ./scripts/validate-imports.sh                    # Validate all modules
#   ./scripts/validate-imports.sh --quick            # Quick check of critical modules only
#   ./scripts/validate-imports.sh --module <path>    # Validate specific module
#
# Integration:
#   - Run as part of linting workflow (make lint)
#   - Run in CI/CD before Docker builds
#   - Run before committing refactoring changes
#
# Exit Codes:
#   0: All imports successful
#   1: Import errors found
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Mode selection
MODE="full"
SPECIFIC_MODULE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            MODE="quick"
            shift
            ;;
        --module)
            SPECIFIC_MODULE="$2"
            MODE="specific"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--quick] [--module <path>]"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "  Import Validation"
echo "=========================================="
echo ""
echo "Mode: $MODE"
echo "Project Root: $PROJECT_ROOT"
echo ""

# Check if agentic-framework-deps-base image exists
if ! docker image inspect agentic-framework-deps-base &>/dev/null; then
    echo -e "${RED}❌ Error: agentic-framework-deps-base Docker image not found${NC}"
    echo "Please build the dependencies image first:"
    echo "  make build-deps"
    exit 1
fi

# Function to validate a single module import
validate_import() {
    local module_path="$1"
    local module_name="$2"

    echo -n "  Testing: $module_name ... "

    # Run import test in Docker container
    if docker run --rm \
        -v "$PROJECT_ROOT/src":/app/src:ro \
        -w /app \
        agentic-framework-deps-base \
        python3 -c "import sys; sys.path.insert(0, '/app/src'); import $module_name" 2>/dev/null; then
        echo -e "${GREEN}✅${NC}"
        return 0
    else
        echo -e "${RED}❌ FAILED${NC}"

        # Run again to show error
        echo ""
        echo -e "${RED}Import Error Details:${NC}"
        docker run --rm \
            -v "$PROJECT_ROOT/src":/app/src:ro \
            -w /app \
            agentic-framework-deps-base \
            python3 -c "import sys; sys.path.insert(0, '/app/src'); import $module_name" 2>&1 || true
        echo ""
        return 1
    fi
}

# Critical modules that should always be importable
CRITICAL_MODULES=(
    "agentic_framework_pkg.logger_config"
    "agentic_framework_pkg.orchestration_service.app"
    "agentic_framework_pkg.orchestration_service.persistence.schema_migrator"
    "agentic_framework_pkg.orchestration_service.persistence.session_persistence"
    "agentic_framework_pkg.orchestration_service.persistence_v2"
    "agentic_framework_pkg.orchestration_service.models.checkpoint_schema"
    "agentic_framework_pkg.orchestration_service.models.session_models"
    "agentic_framework_pkg.orchestration_service.hybrid_orchestration"
    "agentic_framework_pkg.orchestration_service.scientific_workflow.langchain_agent"
    "agentic_framework_pkg.orchestration_service.multi_agent_manager"
    "agentic_framework_pkg.agent_gateway.app"
    "agentic_framework_pkg.agent_gateway.auth"
    "agentic_framework_pkg.gateway_registry.main"
    "agentic_framework_pkg.core.llm_agnostic_layer"
    "agentic_framework_pkg.core.auth"
)

# Full list of all importable modules (for comprehensive check)
ALL_MODULES=(
    "${CRITICAL_MODULES[@]}"
    "agentic_framework_pkg.orchestration_service.context_manager"
    "agentic_framework_pkg.orchestration_service.external_tool_manager"
    "agentic_framework_pkg.orchestration_service.tool_manager"
    "agentic_framework_pkg.mcp_server.main"
    "agentic_framework_pkg.sandbox_mcp_server.main"
    "agentic_framework_pkg.hpc_mcp_server.main"
)

FAILED_IMPORTS=()

case $MODE in
    quick)
        echo "Running quick validation (critical modules only)..."
        echo ""
        for module in "${CRITICAL_MODULES[@]}"; do
            if ! validate_import "" "$module"; then
                FAILED_IMPORTS+=("$module")
            fi
        done
        ;;

    specific)
        echo "Validating specific module: $SPECIFIC_MODULE"
        echo ""
        if ! validate_import "" "$SPECIFIC_MODULE"; then
            FAILED_IMPORTS+=("$SPECIFIC_MODULE")
        fi
        ;;

    full)
        echo "Running full validation (all modules)..."
        echo ""
        for module in "${ALL_MODULES[@]}"; do
            if ! validate_import "" "$module"; then
                FAILED_IMPORTS+=("$module")
            fi
        done
        ;;
esac

echo ""
echo "=========================================="
echo "  Results"
echo "=========================================="

if [ ${#FAILED_IMPORTS[@]} -eq 0 ]; then
    echo -e "${GREEN}✅ All imports successful!${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}❌ ${#FAILED_IMPORTS[@]} import(s) failed:${NC}"
    for module in "${FAILED_IMPORTS[@]}"; do
        echo "  - $module"
    done
    echo ""
    echo "Fix these import errors before committing."
    echo ""
    exit 1
fi
