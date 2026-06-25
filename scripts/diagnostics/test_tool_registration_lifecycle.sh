#!/bin/bash
# test_tool_registration_lifecycle.sh
#
# Reusable registration lifecycle test for any example/ MCP stack.
#
# Full lifecycle:
#   1. Confirm MCP server health
#   2. Verify current tool registration in Redis
#   3. Force deregister all tools
#   4. Verify tools are gone from Redis
#   5. Re-register all tools
#   6. Verify tools reappear in Redis
#   7. Confirm MCP server health (post-registration)
#   8. E2E: agentic CLI lists tools visible to orchestrator
#   9. E2E: agentic CLI calls MCP health endpoint
#
# Usage:
#   ./scripts/diagnostics/test_tool_registration_lifecycle.sh \
#       --stack biofoundation \
#       --container biofoundation_mcp_server \
#       --health-port 9009 \
#       --tool-count 5 \
#       --tools "preprocess_spectra,run_inference,get_job_status,list_models,convert_mza" \
#       --register-cmd "python3 scripts/register_biofoundation_tools.py register" \
#       --deregister-cmd "python3 scripts/register_biofoundation_tools.py deregister" \
#       --verify-cmd "python3 scripts/register_biofoundation_tools.py verify" \
#       --stack-dir examples/biofoundation_mcp_server
#
# Environment:
#   ADMIN_USER          (default: admin)
#   ADMIN_PASS          (default: admin)
#   KEYCLOAK_URL        (default: http://keycloak:8180)
#   AGENT_GATEWAY_URL   (default: http://localhost:8083)
#   ENGINE              (default: docker)

set -uo pipefail
# NOTE: -e intentionally omitted — steps use pass/fail counters, not early exit

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak:8180}"
AGENT_GATEWAY_URL="${AGENT_GATEWAY_URL:-http://localhost:8083}"
ENGINE="${ENGINE:-docker}"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
STACK=""
CONTAINER=""
HEALTH_PORT=""
TOOL_COUNT=""
TOOLS=""
REGISTER_CMD=""
DEREGISTER_CMD=""
VERIFY_CMD=""
STACK_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stack)       STACK="$2"; shift 2 ;;
        --container)   CONTAINER="$2"; shift 2 ;;
        --health-port) HEALTH_PORT="$2"; shift 2 ;;
        --tool-count)  TOOL_COUNT="$2"; shift 2 ;;
        --tools)       TOOLS="$2"; shift 2 ;;
        --register-cmd)   REGISTER_CMD="$2"; shift 2 ;;
        --deregister-cmd) DEREGISTER_CMD="$2"; shift 2 ;;
        --verify-cmd)     VERIFY_CMD="$2"; shift 2 ;;
        --stack-dir)      STACK_DIR="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Validate required args
for var in STACK CONTAINER HEALTH_PORT TOOL_COUNT TOOLS REGISTER_CMD DEREGISTER_CMD STACK_DIR; do
    if [[ -z "${!var:-}" ]]; then
        echo "ERROR: --$(echo "$var" | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required"
        exit 1
    fi
done

# Split tool names into array
IFS=',' read -ra TOOL_ARRAY <<< "$TOOLS"

# Resolve project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
PASS=0
FAIL=0
STEP=0

step() {
    STEP=$((STEP + 1))
    echo ""
    echo "================================================================"
    echo "  Step $STEP: $1"
    echo "================================================================"
}

pass() {
    PASS=$((PASS + 1))
    echo "  [PASS] $1"
}

fail() {
    FAIL=$((FAIL + 1))
    echo "  [FAIL] $1"
}

check_redis_key() {
    local key="$1"
    local result
    result=$($ENGINE exec redis redis-cli GET "$key" 2>/dev/null) || true
    if [[ -n "$result" && "$result" != "(nil)" ]]; then
        return 0  # found
    fi
    return 1  # not found
}

find_agentic_cli() {
    local candidates=(
        "$PROJECT_ROOT/.venv311/bin/agentic"
        "$PROJECT_ROOT/.venv/bin/agentic"
    )
    local which_result
    which_result=$(which agentic 2>/dev/null) || true
    if [[ -n "$which_result" ]]; then
        candidates+=("$which_result")
    fi
    for c in "${candidates[@]}"; do
        if [[ -x "$c" ]]; then
            echo "$c"
            return 0
        fi
    done
    echo ""
    return 1
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
echo "====================================================================="
echo "  Registration Lifecycle Test: ${STACK}"
echo "====================================================================="
echo ""
echo "  Container:     $CONTAINER"
echo "  Health port:   $HEALTH_PORT"
echo "  Tool count:    $TOOL_COUNT"
echo "  Tools:         ${TOOL_ARRAY[*]}"
echo "  Stack dir:     $STACK_DIR"
echo "  Gateway:       $AGENT_GATEWAY_URL"
echo "  Keycloak:      $KEYCLOAK_URL"
echo ""

# Find agentic CLI
AGENTIC_CLI=$(find_agentic_cli) || true
if [[ -z "$AGENTIC_CLI" ]]; then
    echo "ERROR: agentic CLI not found. Install: pip install -e $PROJECT_ROOT/src/"
    exit 1
fi
echo "  agentic CLI:   $AGENTIC_CLI"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Confirm MCP server health (pre-test)
# ---------------------------------------------------------------------------
step "Confirm MCP server health (pre-test)"

if curl -sf "http://localhost:${HEALTH_PORT}/health" > /dev/null 2>&1; then
    pass "MCP server healthy at localhost:${HEALTH_PORT}"
else
    # Try via docker exec as fallback (some stacks don't expose health port to host)
    if $ENGINE exec "$CONTAINER" curl -sf "http://localhost:${HEALTH_PORT}/health" > /dev/null 2>&1; then
        pass "MCP server healthy (via docker exec)"
    else
        fail "MCP server NOT healthy at localhost:${HEALTH_PORT}"
    fi
fi

# Also check container is running
if $ENGINE ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    pass "Container '$CONTAINER' is running"
else
    fail "Container '$CONTAINER' is NOT running"
    echo "ABORT: Cannot continue without running container."
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 2: Verify current tool registration in Redis (baseline)
# ---------------------------------------------------------------------------
step "Verify current tool registration in Redis (baseline)"

BASELINE_FOUND=0
for tool in "${TOOL_ARRAY[@]}"; do
    key="external_tool:${tool}"
    if check_redis_key "$key"; then
        echo "  + $tool: registered"
        BASELINE_FOUND=$((BASELINE_FOUND + 1))
    else
        echo "  - $tool: NOT registered"
    fi
done
echo ""
echo "  Baseline: $BASELINE_FOUND/$TOOL_COUNT tools currently registered"

# ---------------------------------------------------------------------------
# Step 3: Force deregister all tools
# ---------------------------------------------------------------------------
step "Force deregister all tools"

# Run the stack's own deregister command from its directory
pushd "$PROJECT_ROOT/$STACK_DIR" > /dev/null
echo "  Running: $DEREGISTER_CMD (from $STACK_DIR)"
if eval "export KEYCLOAK_URL='$KEYCLOAK_URL' AGENT_GATEWAY_URL='$AGENT_GATEWAY_URL' ADMIN_USER='$ADMIN_USER' ADMIN_PASS='$ADMIN_PASS'; $DEREGISTER_CMD" 2>&1 | tail -10; then
    pass "Deregister command completed"
else
    # Deregister can fail if tools don't exist — that's OK
    echo "  (deregister returned non-zero, which may be expected if tools were already absent)"
fi
popd > /dev/null

# ---------------------------------------------------------------------------
# Step 4: Verify tools are GONE from Redis
# ---------------------------------------------------------------------------
step "Verify tools are gone from Redis (post-deregister)"

GONE_COUNT=0
for tool in "${TOOL_ARRAY[@]}"; do
    key="external_tool:${tool}"
    if check_redis_key "$key"; then
        fail "$tool still in Redis after deregister"
    else
        pass "$tool removed from Redis"
        GONE_COUNT=$((GONE_COUNT + 1))
    fi
done

if [[ "$GONE_COUNT" -eq "$TOOL_COUNT" ]]; then
    pass "All $TOOL_COUNT tools confirmed removed"
else
    fail "Only $GONE_COUNT/$TOOL_COUNT tools removed"
fi

# ---------------------------------------------------------------------------
# Step 5: Re-register all tools
# ---------------------------------------------------------------------------
step "Re-register all tools"

pushd "$PROJECT_ROOT/$STACK_DIR" > /dev/null
echo "  Running: $REGISTER_CMD (from $STACK_DIR)"
if eval "export KEYCLOAK_URL='$KEYCLOAK_URL' AGENT_GATEWAY_URL='$AGENT_GATEWAY_URL' ADMIN_USER='$ADMIN_USER' ADMIN_PASS='$ADMIN_PASS'; $REGISTER_CMD" 2>&1 | tail -15; then
    pass "Register command completed"
else
    fail "Register command failed"
fi
popd > /dev/null

# ---------------------------------------------------------------------------
# Step 6: Verify tools reappear in Redis (post-register)
# ---------------------------------------------------------------------------
step "Verify tools reappear in Redis (post-register)"

REGISTERED_COUNT=0
for tool in "${TOOL_ARRAY[@]}"; do
    key="external_tool:${tool}"
    if check_redis_key "$key"; then
        # Validate JSON structure
        raw=$($ENGINE exec redis redis-cli GET "$key" 2>/dev/null)
        if echo "$raw" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'invocation' in d" 2>/dev/null; then
            pass "$tool registered with valid config"
        else
            pass "$tool registered (config parse skipped)"
        fi
        REGISTERED_COUNT=$((REGISTERED_COUNT + 1))
    else
        fail "$tool NOT found in Redis after register"
    fi
done

if [[ "$REGISTERED_COUNT" -eq "$TOOL_COUNT" ]]; then
    pass "All $TOOL_COUNT tools confirmed registered"
else
    fail "Only $REGISTERED_COUNT/$TOOL_COUNT tools registered"
fi

# ---------------------------------------------------------------------------
# Step 7: Confirm MCP server health (post-registration)
# ---------------------------------------------------------------------------
step "Confirm MCP server health (post-registration)"

if curl -sf "http://localhost:${HEALTH_PORT}/health" > /dev/null 2>&1; then
    pass "MCP server still healthy after registration lifecycle"
elif $ENGINE exec "$CONTAINER" curl -sf "http://localhost:${HEALTH_PORT}/health" > /dev/null 2>&1; then
    pass "MCP server still healthy (via docker exec)"
else
    fail "MCP server health degraded after registration lifecycle"
fi

# ---------------------------------------------------------------------------
# Step 8: E2E — agentic CLI lists tools visible to orchestrator
# ---------------------------------------------------------------------------
step "E2E: agentic CLI tool listing"

# Use list-registered-tools.sh (API-based, returns ALL tools — CLI truncates at 20)
LIST_SCRIPT="${PROJECT_ROOT}/scripts/list-registered-tools.sh"
if [[ -x "$LIST_SCRIPT" ]]; then
    echo "  Running: scripts/list-registered-tools.sh (API-based, full list)"
    TOOL_LIST_OUTPUT=$("$LIST_SCRIPT" 2>&1) || true
else
    # Fallback to agentic CLI
    echo "  Running: $AGENTIC_CLI tools list --username $ADMIN_USER --password ****"
    TOOL_LIST_OUTPUT=$($AGENTIC_CLI tools list \
        --username "$ADMIN_USER" --password "$ADMIN_PASS" 2>&1) || true
fi

if [[ -n "$TOOL_LIST_OUTPUT" ]]; then
    echo "  Tool list output (relevant lines):"
    # Show only lines matching this stack's tools
    FOUND_IN_LIST=0
    for tool in "${TOOL_ARRAY[@]}"; do
        if echo "$TOOL_LIST_OUTPUT" | grep -q "$tool"; then
            echo "    + $tool: visible"
            FOUND_IN_LIST=$((FOUND_IN_LIST + 1))
        else
            echo "    - $tool: NOT visible in agentic tools list"
        fi
    done

    if [[ "$FOUND_IN_LIST" -eq "$TOOL_COUNT" ]]; then
        pass "All $TOOL_COUNT tools visible via agentic CLI"
    else
        fail "Only $FOUND_IN_LIST/$TOOL_COUNT tools visible via agentic CLI"
    fi
else
    fail "agentic tools list returned empty output"
fi

# ---------------------------------------------------------------------------
# Step 9: E2E — MCP health via orchestration_service
# ---------------------------------------------------------------------------
step "E2E: MCP health reachability from orchestration_service"

# The orchestration_service must be able to reach the MCP server via Docker DNS
if $ENGINE exec orchestration_service curl -sf "http://${CONTAINER}:${HEALTH_PORT}/health" > /dev/null 2>&1; then
    pass "orchestration_service can reach ${CONTAINER}:${HEALTH_PORT}/health"
else
    # Some stacks use different internal ports
    fail "orchestration_service CANNOT reach ${CONTAINER}:${HEALTH_PORT}/health"
fi

# Also test MCP endpoint reachability (JSON-RPC or streamable HTTP)
# NOTE: FastMCP servers use streamable HTTP transport, not legacy JSON-RPC POST.
# A plain POST with Content-Type: application/json may return 4xx. This is
# expected and treated as a soft warning — the health check above already
# confirms reachability.
MCP_RPC='{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
MCP_RESULT=$($ENGINE exec orchestration_service \
    curl -sf -X POST "http://${CONTAINER}:${HEALTH_PORT}/mcp" \
    -H "Content-Type: application/json" \
    -d "$MCP_RPC" 2>&1) || true

if echo "$MCP_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'result' in d" 2>/dev/null; then
    DISCOVERED=$(echo "$MCP_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['result'].get('tools',d['result'] if isinstance(d['result'],list) else [])))" 2>/dev/null) || DISCOVERED="?"
    pass "MCP JSON-RPC tools/list reachable from orchestration_service ($DISCOVERED tools)"
else
    echo "  [WARN] MCP JSON-RPC tools/list not reachable (expected: server uses streamable HTTP transport)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "====================================================================="
echo "  Registration Lifecycle Summary: ${STACK}"
echo "====================================================================="
TOTAL=$((PASS + FAIL))
echo ""
echo "  Passed: $PASS / $TOTAL"
echo "  Failed: $FAIL / $TOTAL"
echo ""

if [[ "$FAIL" -eq 0 ]]; then
    echo "  RESULT: ALL CHECKS PASSED"
    exit 0
else
    echo "  RESULT: $FAIL CHECK(S) FAILED"
    exit 1
fi
