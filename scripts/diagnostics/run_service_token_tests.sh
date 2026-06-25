#!/bin/bash
# Service Token Management Test Execution Script
# Session 49 - Redis-based token management validation
#
# Features:
# - Runs all service token management tests
# - Uses nohup for background execution
# - Pipes output to timestamped log files in logs/
# - Provides real-time progress indicators
# - Comprehensive exit status reporting
#
# Usage:
#   ./scripts/testing/run_service_token_tests.sh [--unit|--integration|--all]

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
BLUE='\033[0;36m'
NC='\033[0m' # No Color

# Create logs directory
mkdir -p logs

# Timestamp for log files
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Log file paths
UNIT_LOG="logs/service_token_unit_tests_${TIMESTAMP}.log"
INTEGRATION_LOG="logs/service_token_integration_tests_${TIMESTAMP}.log"
E2E_LOG="logs/service_token_e2e_tests_${TIMESTAMP}.log"
SUMMARY_LOG="logs/service_token_test_summary_${TIMESTAMP}.log"

# Test mode (default: all)
TEST_MODE="${1:-all}"

echo -e "${GREEN}================================================================================================${NC}"
echo -e "${GREEN}Service Token Management Test Suite - Session 49${NC}"
echo -e "${GREEN}================================================================================================${NC}"
echo ""
echo -e "${BLUE}Test Mode: ${TEST_MODE}${NC}"
echo -e "${BLUE}Timestamp: ${TIMESTAMP}${NC}"
echo -e "${BLUE}Log Directory: logs/${NC}"
echo ""

# Function to run tests with nohup and logging
run_test_suite() {
    local TEST_NAME=$1
    local TEST_COMMAND=$2
    local LOG_FILE=$3

    echo -e "${YELLOW}→ Running ${TEST_NAME}...${NC}"
    echo -e "${BLUE}  Log: ${LOG_FILE}${NC}"

    # Run with nohup in background
    nohup bash -c "${TEST_COMMAND}" > "${LOG_FILE}" 2>&1 &
    local PID=$!

    echo -e "${BLUE}  PID: ${PID}${NC}"

    # Wait for completion
    wait $PID
    local EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}  ✅ ${TEST_NAME} PASSED${NC}"
        return 0
    else
        echo -e "${RED}  ❌ ${TEST_NAME} FAILED (exit code: ${EXIT_CODE})${NC}"
        echo -e "${YELLOW}  Check log: ${LOG_FILE}${NC}"
        return 1
    fi
}

# Test execution counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Function to track test results
track_result() {
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    if [ $1 -eq 0 ]; then
        PASSED_TESTS=$((PASSED_TESTS + 1))
        return 0
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
}

# ================================================================================================
# UNIT TESTS (Fast, Mocked)
# ================================================================================================

if [ "$TEST_MODE" == "unit" ] || [ "$TEST_MODE" == "all" ]; then
    echo -e "${GREEN}================================================================================================${NC}"
    echo -e "${GREEN}UNIT TESTS (Mocked Redis, Fast Execution)${NC}"
    echo -e "${GREEN}================================================================================================${NC}"
    echo ""

    # Test 1: Core Service Token Manager
    run_test_suite \
        "Core Service Token Manager" \
        "docker run --rm --user \$(id -u):\$(id -g) \
            -v \"\$(pwd)/src\":/app/src:ro \
            -v \"\$(pwd)/tests\":/app/tests:ro \
            -e PYTHONPATH=/app/src \
            -e HOME=/tmp \
            -w /tmp \
            agentic-framework-deps-base \
            /app/.venv/bin/pytest /app/tests/unit/agentic_framework_pkg/core/test_service_token_manager.py -v --tb=short --rootdir=/tmp -o cache_dir=/tmp/.pytest_cache" \
        "${UNIT_LOG}"
    track_result $?

    # Test 2: Orchestration Service Auth
    run_test_suite \
        "Orchestration Service Auth Redis Validation" \
        "docker run --rm --user \$(id -u):\$(id -g) \
            -v \"\$(pwd)/src\":/app/src:ro \
            -v \"\$(pwd)/tests\":/app/tests:ro \
            -e PYTHONPATH=/app/src \
            -e HOME=/tmp \
            -w /tmp \
            agentic-framework-deps-base \
            /app/.venv/bin/pytest /app/tests/unit/agentic_framework_pkg/orchestration_service/test_auth_redis_validation.py -v --tb=short --rootdir=/tmp -o cache_dir=/tmp/.pytest_cache" \
        "logs/service_token_orchestration_auth_unit_${TIMESTAMP}.log"
    track_result $?

    # Test 3: Agent Gateway Auth
    run_test_suite \
        "Agent Gateway Auth Redis Validation" \
        "docker run --rm --user \$(id -u):\$(id -g) \
            -v \"\$(pwd)/src\":/app/src:ro \
            -v \"\$(pwd)/tests\":/app/tests:ro \
            -e PYTHONPATH=/app/src \
            -e HOME=/tmp \
            -w /tmp \
            agentic-framework-deps-base \
            /app/.venv/bin/pytest /app/tests/unit/agentic_framework_pkg/agent_gateway/test_auth_redis_validation.py -v --tb=short --rootdir=/tmp -o cache_dir=/tmp/.pytest_cache" \
        "logs/service_token_agent_gateway_auth_unit_${TIMESTAMP}.log"
    track_result $?

    # Test 4: CLI Script
    run_test_suite \
        "CLI Script Redis Integration" \
        "docker run --rm --user \$(id -u):\$(id -g) \
            -v \"\$(pwd)/src\":/app/src:ro \
            -v \"\$(pwd)/tests\":/app/tests:ro \
            -v \"\$(pwd)/scripts\":/app/scripts:ro \
            -e PYTHONPATH=/app/src:/app/scripts/deps \
            -e HOME=/tmp \
            -w /tmp \
            agentic-framework-deps-base \
            /app/.venv/bin/pytest /app/tests/unit/scripts/test_create_service_api_token_redis.py -v --tb=short --rootdir=/tmp -o cache_dir=/tmp/.pytest_cache" \
        "logs/service_token_cli_script_unit_${TIMESTAMP}.log"
    track_result $?

    echo ""
fi

# ================================================================================================
# INTEGRATION TESTS (Real Redis, Slower)
# ================================================================================================

if [ "$TEST_MODE" == "integration" ] || [ "$TEST_MODE" == "all" ]; then
    echo -e "${GREEN}================================================================================================${NC}"
    echo -e "${GREEN}INTEGRATION TESTS (Real Redis Database 1, Full Stack)${NC}"
    echo -e "${GREEN}================================================================================================${NC}"
    echo ""

    # Integration Test: Dual-Mode Support
    run_test_suite \
        "Service Token Dual-Mode Integration" \
        "docker run --rm --user \$(id -u):\$(id -g) --network=agentic_framework_network \
            -v \"\$(pwd)/src\":/app/src:ro \
            -v \"\$(pwd)/tests\":/app/tests:ro \
            -v \"\$(pwd)/pyproject.toml\":/app/pyproject.toml:ro \
            -e PYTHONPATH=/app/src \
            -e HOME=/tmp \
            -e REDIS_URL=redis://redis:6379/1 \
            -w /tmp \
            agentic-framework-deps-base \
            /app/.venv/bin/pytest /app/tests/integration/test_service_token_dual_mode.py -v --tb=short" \
        "${INTEGRATION_LOG}"
    track_result $?

    # Security Test: Negative Tests and Attack Vectors
    run_test_suite \
        "Service Token Security (Negative Tests & Attack Vectors)" \
        "docker run --rm --user \$(id -u):\$(id -g) --network=agentic_framework_network \
            -v \"\$(pwd)/src\":/app/src:ro \
            -v \"\$(pwd)/tests\":/app/tests:ro \
            -v \"\$(pwd)/pyproject.toml\":/app/pyproject.toml:ro \
            -e PYTHONPATH=/app/src \
            -e HOME=/tmp \
            -e REDIS_URL=redis://redis:6379/1 \
            -w /tmp \
            agentic-framework-deps-base \
            /app/.venv/bin/pytest /app/tests/integration/test_service_token_security.py -v --tb=short" \
        "logs/service_token_security_integration_${TIMESTAMP}.log"
    track_result $?

    echo ""
fi

# ================================================================================================
# E2E TESTS (Real Services, Full Authentication Flow)
# ================================================================================================

if [ "$TEST_MODE" == "e2e" ] || [ "$TEST_MODE" == "all" ]; then
    echo -e "${GREEN}================================================================================================${NC}"
    echo -e "${GREEN}E2E TESTS (Real Services: Agent Gateway + Orchestration Service + Redis + Keycloak)${NC}"
    echo -e "${GREEN}================================================================================================${NC}"
    echo ""

    # Check if services are running
    if ! docker ps | grep -q "agent_gateway"; then
        echo -e "${RED}❌ ERROR: Services not running!${NC}"
        echo -e "${YELLOW}Start services with: make start${NC}"
        exit 1
    fi

    # E2E Test: Full token lifecycle
    run_test_suite \
        "Service Token E2E (Full Lifecycle)" \
        "docker run --rm --user \$(id -u):\$(id -g) --network=agentic_framework_network \
            --env-file ./.env-keycloak-credentials-dir/.env-keycloak-credentials \
            -v \"\$(pwd)/src\":/app/src:ro \
            -v \"\$(pwd)/tests\":/app/tests:ro \
            -v \"\$(pwd)/scripts\":/app/scripts:ro \
            -e PYTHONPATH=/app/src:/app/scripts/deps \
            -e HOME=/tmp \
            -e AGENT_GATEWAY_URL=http://agent_gateway:8081/v1 \
            -e REDIS_URL=redis://redis:6379/0 \
            -w /tmp \
            agentic-framework-deps-base \
            /app/.venv/bin/pytest /app/tests/e2e/test_service_token_redis_e2e.py -v -s --tb=short --rootdir=/tmp -o cache_dir=/tmp/.pytest_cache" \
        "${E2E_LOG}"
    track_result $?

    echo ""
fi

# ================================================================================================
# SUMMARY
# ================================================================================================

echo -e "${GREEN}================================================================================================${NC}"
echo -e "${GREEN}TEST EXECUTION SUMMARY${NC}"
echo -e "${GREEN}================================================================================================${NC}"
echo ""
echo -e "${BLUE}Timestamp: ${TIMESTAMP}${NC}"
echo -e "${BLUE}Total Tests: ${TOTAL_TESTS}${NC}"
echo -e "${GREEN}Passed: ${PASSED_TESTS}${NC}"
echo -e "${RED}Failed: ${FAILED_TESTS}${NC}"
echo ""

# Write summary to log file
{
    echo "Service Token Management Test Summary"
    echo "Timestamp: ${TIMESTAMP}"
    echo "Test Mode: ${TEST_MODE}"
    echo ""
    echo "Results:"
    echo "  Total: ${TOTAL_TESTS}"
    echo "  Passed: ${PASSED_TESTS}"
    echo "  Failed: ${FAILED_TESTS}"
    echo ""
    echo "Log Files:"
    [ -f "${UNIT_LOG}" ] && echo "  - ${UNIT_LOG}"
    [ -f "logs/service_token_orchestration_auth_unit_${TIMESTAMP}.log" ] && \
        echo "  - logs/service_token_orchestration_auth_unit_${TIMESTAMP}.log"
    [ -f "logs/service_token_agent_gateway_auth_unit_${TIMESTAMP}.log" ] && \
        echo "  - logs/service_token_agent_gateway_auth_unit_${TIMESTAMP}.log"
    [ -f "logs/service_token_cli_script_unit_${TIMESTAMP}.log" ] && \
        echo "  - logs/service_token_cli_script_unit_${TIMESTAMP}.log"
    [ -f "${INTEGRATION_LOG}" ] && echo "  - ${INTEGRATION_LOG}"
} > "${SUMMARY_LOG}"

echo -e "${BLUE}Summary saved to: ${SUMMARY_LOG}${NC}"
echo ""

# View last 50 lines of each log
if [ $FAILED_TESTS -gt 0 ]; then
    echo -e "${RED}================================================================================================${NC}"
    echo -e "${RED}FAILED TEST LOGS (Last 50 lines)${NC}"
    echo -e "${RED}================================================================================================${NC}"
    echo ""

    for LOG_FILE in logs/service_token_*_${TIMESTAMP}.log; do
        if [ -f "$LOG_FILE" ]; then
            if grep -q "FAILED" "$LOG_FILE" 2>/dev/null; then
                echo -e "${YELLOW}→ ${LOG_FILE}:${NC}"
                tail -50 "$LOG_FILE"
                echo ""
            fi
        fi
    done
fi

echo -e "${GREEN}================================================================================================${NC}"
echo -e "${GREEN}View Complete Logs:${NC}"
echo -e "${GREEN}================================================================================================${NC}"
echo ""
echo -e "${BLUE}# View all test logs${NC}"
echo -e "  ls -lth logs/service_token_*_${TIMESTAMP}.log"
echo ""
echo -e "${BLUE}# View specific log${NC}"
echo -e "  less ${UNIT_LOG}"
echo -e "  less ${INTEGRATION_LOG}"
echo ""
echo -e "${BLUE}# Search for failures${NC}"
echo -e "  grep -n \"FAILED\" logs/service_token_*_${TIMESTAMP}.log"
echo ""

# Exit with failure if any tests failed
if [ $FAILED_TESTS -gt 0 ]; then
    exit 1
else
    exit 0
fi
