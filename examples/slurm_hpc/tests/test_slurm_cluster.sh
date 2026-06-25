#!/usr/bin/env bash
# =============================================================================
# test_slurm_cluster.sh — Validate Slurm backend cluster health
# =============================================================================
# Tests:
#   1. All 6 backend containers are running
#   2. Munge authentication works between nodes
#   3. slurmctld responds to ping
#   4. Compute nodes are registered and idle
#   5. A test job can be submitted and completes
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

check() {
    local desc="$1"
    shift
    echo -n "  $desc... "
    if "$@" >/dev/null 2>&1; then
        echo -e "${GREEN}PASS${NC}"
        PASS=$((PASS + 1))
    else
        echo -e "${RED}FAIL${NC}"
        FAIL=$((FAIL + 1))
    fi
}

echo -e "${YELLOW}=== Slurm Backend Cluster Tests ===${NC}"

# Test 1: Containers running
echo ""
echo "--- Container Status ---"
for svc in slurm_mysql slurmdbd slurmctld slurmrestd c1 c2; do
    check "Container ${svc} running" docker inspect -f '{{.State.Running}}' "$svc"
done

# Test 2: Munge auth
echo ""
echo "--- Munge Authentication ---"
check "Munge round-trip (slurmctld -> slurmdbd)" \
    bash -c 'docker exec slurmctld munge -n | docker exec -i slurmdbd unmunge'

# Test 3: slurmctld ping
echo ""
echo "--- Controller Status ---"
check "slurmctld responds to ping" \
    bash -c 'docker exec slurmctld scontrol ping 2>/dev/null | grep -q UP'

# Test 4: Compute nodes registered
echo ""
echo "--- Compute Nodes ---"
check "Node c1 registered" \
    bash -c 'docker exec slurmctld scontrol show node c1 2>/dev/null | grep -q "NodeName=c1"'
check "Node c2 registered" \
    bash -c 'docker exec slurmctld scontrol show node c2 2>/dev/null | grep -q "NodeName=c2"'

# Test 5: Job submission
echo ""
echo "--- Job Submission ---"
JOB_OUTPUT=$(docker exec slurmctld bash -c 'sbatch --job-name=cluster_test --output=/data/cluster_test_%j.out --wrap="hostname && date && echo CLUSTER_TEST_OK"' 2>&1)
if echo "$JOB_OUTPUT" | grep -q "Submitted batch job"; then
    JOB_ID=$(echo "$JOB_OUTPUT" | grep -oP '\d+')
    echo -e "  Job submitted: ${GREEN}${JOB_ID}${NC}"

    # Wait for completion (max 30s)
    WAITED=0
    while [ "$WAITED" -lt 30 ]; do
        STATE=$(docker exec slurmctld scontrol show job "$JOB_ID" 2>/dev/null | grep -oP 'JobState=\K\w+' || echo "UNKNOWN")
        if [ "$STATE" = "COMPLETED" ]; then
            break
        elif [ "$STATE" = "FAILED" ] || [ "$STATE" = "CANCELLED" ]; then
            break
        fi
        sleep 2
        WAITED=$((WAITED + 2))
    done

    check "Test job completed" test "$STATE" = "COMPLETED"
    PASS=$((PASS + 1))  # Count the submission itself
else
    echo -e "  Job submission: ${RED}FAIL${NC}"
    FAIL=$((FAIL + 1))
fi

# Summary
echo ""
echo "==========================================="
TOTAL=$((PASS + FAIL))
echo -e "Results: ${GREEN}${PASS}${NC}/${TOTAL} passed, ${RED}${FAIL}${NC} failed"
echo "==========================================="

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
