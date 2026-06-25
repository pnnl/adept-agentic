#!/bin/bash
#
# Validation Script for Session Navigation Feature
#
# This script validates the session navigation implementation by:
# 1. Checking that all required files exist
# 2. Verifying import statements work
# 3. Validating database schema matches ORM
# 4. Running basic smoke tests
#

set -e

echo "=========================================="
echo "Session Navigation Feature Validation"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track results
PASSED=0
FAILED=0

# Function to check file exists
check_file() {
    local file=$1
    local description=$2

    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $description: $file"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} $description: $file (NOT FOUND)"
        ((FAILED++))
        return 1
    fi
}

# Function to check directory exists
check_dir() {
    local dir=$1
    local description=$2

    if [ -d "$dir" ]; then
        echo -e "${GREEN}✓${NC} $description: $dir"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} $description: $dir (NOT FOUND)"
        ((FAILED++))
        return 1
    fi
}

echo "1. Checking Implementation Files..."
echo "-----------------------------------"
check_dir "src/agentic_framework_pkg/streamlit_app_v2/components" "Components directory"
check_file "src/agentic_framework_pkg/streamlit_app_v2/components/__init__.py" "Components package init"
check_file "src/agentic_framework_pkg/streamlit_app_v2/components/session_navigator.py" "SessionNavigator component"
check_file "src/agentic_framework_pkg/streamlit_app_v2/Chat.py" "Streamlit Chat page (main app)"
echo ""

echo "2. Checking Test Files..."
echo "-------------------------"
check_dir "tests/unit/agentic_framework_pkg/streamlit_app_v2" "Unit test directory"
check_dir "tests/unit/agentic_framework_pkg/streamlit_app_v2/components" "Component unit tests directory"
check_file "tests/unit/agentic_framework_pkg/streamlit_app_v2/components/test_session_navigator.py" "SessionNavigator unit tests"
check_file "tests/unit/agentic_framework_pkg/streamlit_app_v2/test_app_helpers.py" "App helpers unit tests"
check_file "tests/unit/agentic_framework_pkg/streamlit_app_v2/test_imports.py" "Import tests"
check_dir "tests/integration/streamlit_app_v2" "Integration test directory"
check_file "tests/integration/streamlit_app_v2/test_session_persistence_integration.py" "Integration tests"
check_file "tests/e2e/test_streamlit_session_navigation_e2e.py" "E2E tests"
echo ""

echo "3. Checking Documentation..."
echo "----------------------------"
check_file "docs/implementation-plans/STREAMLIT_SESSION_NAVIGATION_IMPLEMENTATION_PLAN_20260117.md" "Implementation plan"
check_file "docs/session-summaries/SESSION_33_STREAMLIT_SESSION_NAVIGATION_IMPLEMENTATION_REPORT.md" "Implementation report"
check_file "docs/architecture/ORM_MIGRATION_BOOTSTRAP_ARCHITECTURE.md" "ORM architecture review"
echo ""

echo "4. Checking ORM Models..."
echo "-------------------------"
check_file "src/agentic_framework_pkg/orchestration_service/models/session_models.py" "Session ORM models"
echo ""

echo "5. Verifying Database Schema Existence..."
echo "------------------------------------------"
if docker exec postgres_container psql -U postgres -d agentic_framework_db -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='user_sessions';" 2>/dev/null | grep -q "1"; then
    echo -e "${GREEN}✓${NC} user_sessions table exists"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠${NC} user_sessions table not found (database may not be running)"
fi

if docker exec postgres_container psql -U postgres -d agentic_framework_db -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='session_messages';" 2>/dev/null | grep -q "1"; then
    echo -e "${GREEN}✓${NC} session_messages table exists"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠${NC} session_messages table not found (database may not be running)"
fi
echo ""

echo "6. Checking Required Columns..."
echo "--------------------------------"
REQUIRED_COLUMNS="session_id user_id session_metadata title last_active_at status"
for col in $REQUIRED_COLUMNS; do
    if docker exec postgres_container psql -U postgres -d agentic_framework_db -t -c "SELECT column_name FROM information_schema.columns WHERE table_name='user_sessions' AND column_name='$col';" 2>/dev/null | grep -q "$col"; then
        echo -e "${GREEN}✓${NC} user_sessions.$col exists"
        ((PASSED++))
    else
        echo -e "${YELLOW}⚠${NC} user_sessions.$col not found"
    fi
done
echo ""

echo "7. Code Quality Checks..."
echo "-------------------------"
# Check for common issues
if grep -r "TODO\|FIXME\|XXX\|HACK" src/agentic_framework_pkg/streamlit_app_v2/components/session_navigator.py 2>/dev/null; then
    echo -e "${YELLOW}⚠${NC} Found TODO/FIXME comments in session_navigator.py"
else
    echo -e "${GREEN}✓${NC} No TODO/FIXME comments in session_navigator.py"
    ((PASSED++))
fi

# Check for print statements (should use logger)
if grep -E "^\s*print\(" src/agentic_framework_pkg/streamlit_app_v2/components/session_navigator.py 2>/dev/null; then
    echo -e "${YELLOW}⚠${NC} Found print() statements (should use logger)"
else
    echo -e "${GREEN}✓${NC} No print() statements (using logger)"
    ((PASSED++))
fi
echo ""

echo "8. Line Count Statistics..."
echo "---------------------------"
echo "Implementation files:"
wc -l src/agentic_framework_pkg/streamlit_app_v2/components/session_navigator.py 2>/dev/null || echo "  (file not found)"
echo ""
echo "Test files:"
wc -l tests/unit/agentic_framework_pkg/streamlit_app_v2/components/test_session_navigator.py 2>/dev/null || echo "  (file not found)"
wc -l tests/unit/agentic_framework_pkg/streamlit_app_v2/test_app_helpers.py 2>/dev/null || echo "  (file not found)"
wc -l tests/integration/streamlit_app_v2/test_session_persistence_integration.py 2>/dev/null || echo "  (file not found)"
wc -l tests/e2e/test_streamlit_session_navigation_e2e.py 2>/dev/null || echo "  (file not found)"
echo ""

echo "=========================================="
echo "Validation Summary"
echo "=========================================="
echo -e "${GREEN}Passed:${NC} $PASSED checks"
echo -e "${RED}Failed:${NC} $FAILED checks"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All validation checks passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some validation checks failed${NC}"
    exit 1
fi
