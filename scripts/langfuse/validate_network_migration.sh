#!/bin/bash
# Validation script for Langfuse network migration (Session 50 Phase 1.1)
# Tests bidirectional connectivity between Langfuse and ADEPT services

set -e

echo "=========================================="
echo "Langfuse Network Migration Validation"
echo "Session 50 Phase 1.1"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0

# Test function
run_test() {
    local test_name="$1"
    local command="$2"
    local expected_pattern="$3"

    echo -n "Testing: $test_name... "

    if output=$(eval "$command" 2>&1); then
        if [[ -z "$expected_pattern" ]] || echo "$output" | grep -q "$expected_pattern"; then
            echo -e "${GREEN}PASSED${NC}"
            ((PASSED++))
            return 0
        else
            echo -e "${RED}FAILED${NC}"
            echo "  Expected pattern: $expected_pattern"
            echo "  Got: $output"
            ((FAILED++))
            return 1
        fi
    else
        echo -e "${RED}FAILED${NC}"
        echo "  Command failed: $output"
        ((FAILED++))
        return 1
    fi
}

echo "=== Test 1: Network Assignments ==="
echo ""

# Test 1.1: Langfuse-web on multiple networks
run_test "langfuse-web has frontend_net" \
    "docker inspect langfuse-web --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'" \
    "adept_frontend_network"

run_test "langfuse-web has application_net" \
    "docker inspect langfuse-web --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'" \
    "adept_application_network"

run_test "langfuse-web has adept_integration_network" \
    "docker inspect langfuse-web --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'" \
    "adept_integration_network"

echo ""

# Test 1.2: Langfuse-worker on application networks
run_test "langfuse-worker has application_net" \
    "docker inspect langfuse-worker --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'" \
    "adept_application_network"

run_test "langfuse-worker has adept_integration_network" \
    "docker inspect langfuse-worker --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'" \
    "adept_integration_network"

echo ""

# Test 1.3: Backend services isolated on adept_integration_network only
run_test "langfuse-postgres ONLY on adept_integration_network" \
    "docker inspect langfuse-postgres --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'" \
    "^adept_integration_network\$"

run_test "langfuse-redis ONLY on adept_integration_network" \
    "docker inspect langfuse-redis --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'" \
    "^adept_integration_network\$"

run_test "langfuse-clickhouse ONLY on adept_integration_network" \
    "docker inspect langfuse-clickhouse --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'" \
    "^adept_integration_network\$"

run_test "langfuse-minio ONLY on adept_integration_network" \
    "docker inspect langfuse-minio --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'" \
    "^adept_integration_network\$"

echo ""
echo "=== Test 2: Connectivity Tests ==="
echo ""

# Test 2.1: Langfuse-web can access agent_gateway
run_test "langfuse-web can ping agent_gateway" \
    "docker exec langfuse-web ping -c 2 agent_gateway" \
    "2 packets transmitted, 2 received"

run_test "langfuse-web can curl agent_gateway health endpoint" \
    "docker exec langfuse-web curl -s -o /dev/null -w '%{http_code}' http://agent_gateway:8081/health" \
    "200\|401"

echo ""

# Test 2.2: Langfuse-worker can access agent_gateway
run_test "langfuse-worker can ping agent_gateway" \
    "docker exec langfuse-worker ping -c 2 agent_gateway" \
    "2 packets transmitted, 2 received"

echo ""

# Test 2.3: ADEPT services can still reach langfuse-web (telemetry push)
run_test "agent_gateway can ping langfuse-web" \
    "docker exec agent_gateway ping -c 2 langfuse-web" \
    "2 packets transmitted, 2 received"

run_test "orchestration_service can ping langfuse-web" \
    "docker exec orchestration_service ping -c 2 langfuse-web" \
    "2 packets transmitted, 2 received"

echo ""

# Test 2.4: Backend services cannot reach agent_gateway (isolation test)
echo -n "Testing: langfuse-postgres CANNOT reach agent_gateway (should fail)... "
if docker exec langfuse-postgres ping -c 1 -W 2 agent_gateway &>/dev/null; then
    echo -e "${RED}FAILED${NC} - Backend service should NOT access application tier"
    ((FAILED++))
else
    echo -e "${GREEN}PASSED${NC} - Correctly isolated"
    ((PASSED++))
fi

echo ""
echo "=== Test 3: Security Labels ==="
echo ""

# Test 3.1: Tier labels
run_test "langfuse-web has tier=frontend label" \
    "docker inspect langfuse-web --format '{{index .Config.Labels \"tier\"}}'" \
    "frontend"

run_test "langfuse-worker has tier=application label" \
    "docker inspect langfuse-worker --format '{{index .Config.Labels \"tier\"}}'" \
    "application"

run_test "langfuse-postgres has tier=data label" \
    "docker inspect langfuse-postgres --format '{{index .Config.Labels \"tier\"}}'" \
    "data"

run_test "langfuse-redis has tier=data label" \
    "docker inspect langfuse-redis --format '{{index .Config.Labels \"tier\"}}'" \
    "data"

run_test "langfuse-clickhouse has tier=data label" \
    "docker inspect langfuse-clickhouse --format '{{index .Config.Labels \"tier\"}}'" \
    "data"

run_test "langfuse-minio has tier=data label" \
    "docker inspect langfuse-minio --format '{{index .Config.Labels \"tier\"}}'" \
    "data"

echo ""
echo "=== Test 4: Langfuse Service Health ==="
echo ""

# Test 4.1: Langfuse services are healthy
run_test "langfuse-web is healthy" \
    "docker inspect langfuse-web --format '{{.State.Health.Status}}'" \
    "healthy"

run_test "langfuse-postgres is healthy" \
    "docker inspect langfuse-postgres --format '{{.State.Health.Status}}'" \
    "healthy"

run_test "langfuse-redis is healthy" \
    "docker inspect langfuse-redis --format '{{.State.Health.Status}}'" \
    "healthy"

run_test "langfuse-clickhouse is healthy" \
    "docker inspect langfuse-clickhouse --format '{{.State.Health.Status}}'" \
    "healthy"

run_test "langfuse-minio is healthy" \
    "docker inspect langfuse-minio --format '{{.State.Health.Status}}'" \
    "healthy"

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    echo ""
    echo "Langfuse network migration successful:"
    echo "  ✅ Langfuse-web can access agent_gateway for trace replay"
    echo "  ✅ ADEPT services can push telemetry to Langfuse"
    echo "  ✅ Backend services remain isolated"
    echo "  ✅ Three-tier architecture maintained"
    exit 0
else
    echo -e "${RED}Some tests failed. Please review the output above.${NC}"
    exit 1
fi
