#!/bin/bash
# Validate network isolation in Docker Compose environment
# Tests that JupyterLab and Streamlit CANNOT access Redis/PostgreSQL directly

set -e

echo "================================================================="
echo "Docker Compose Network Isolation Validation (Session 50 Phase 1)"
echo "================================================================="
echo ""

FAILED=0

# Test 1: JupyterLab CANNOT access Redis
echo "[Test 1] JupyterLab CANNOT access Redis..."
if docker exec jupyterlab python3 -c "import socket; socket.create_connection(('redis', 6379), timeout=2)" 2>/dev/null; then
    echo "❌ FAIL: JupyterLab can access Redis"
    FAILED=1
else
    echo "✅ PASS: JupyterLab isolated from Redis (network-level)"
fi
echo ""

# Test 2: JupyterLab CANNOT access PostgreSQL
echo "[Test 2] JupyterLab CANNOT access PostgreSQL..."
if docker exec jupyterlab python3 -c "import socket; socket.create_connection(('postgres', 5432), timeout=2)" 2>/dev/null; then
    echo "❌ FAIL: JupyterLab can access PostgreSQL"
    FAILED=1
else
    echo "✅ PASS: JupyterLab isolated from PostgreSQL (network-level)"
fi
echo ""

# Test 3: JupyterLab CANNOT access Keycloak directly
echo "[Test 3] JupyterLab CANNOT access Keycloak..."
if docker exec jupyterlab python3 -c "import socket; socket.create_connection(('keycloak', 8180), timeout=2)" 2>/dev/null; then
    echo "❌ FAIL: JupyterLab can access Keycloak"
    FAILED=1
else
    echo "✅ PASS: JupyterLab isolated from Keycloak (network-level)"
fi
echo ""

# Test 4: JupyterLab CAN access nginx (frontend network)
echo "[Test 4] JupyterLab CAN access nginx proxy..."
if docker exec jupyterlab python3 -c "import socket; socket.create_connection(('nginx_proxy', 80), timeout=2)" >/dev/null 2>&1; then
    echo "✅ PASS: JupyterLab has nginx access (frontend network)"
else
    echo "⚠️  WARNING: JupyterLab cannot access nginx (may be normal if nginx on different network)"
fi
echo ""

# Test 5: Orchestration service CAN access Redis
echo "[Test 5] Orchestration service CAN access Redis..."
if docker exec orchestration_service python3 -c "import redis; redis.Redis(host='redis', port=6379, db=1, socket_connect_timeout=2).ping()" >/dev/null 2>&1; then
    echo "✅ PASS: Orchestration service has Redis access (application tier privilege)"
else
    echo "❌ FAIL: Orchestration service cannot access Redis"
    FAILED=1
fi
echo ""

# Test 6: Orchestration service CAN access PostgreSQL
echo "[Test 6] Orchestration service CAN access PostgreSQL..."
if docker exec orchestration_service python3 -c "import socket; socket.create_connection(('postgres', 5432), timeout=2)" >/dev/null 2>&1; then
    echo "✅ PASS: Orchestration service has PostgreSQL access (application tier privilege)"
else
    echo "❌ FAIL: Orchestration service cannot access PostgreSQL"
    FAILED=1
fi
echo ""

# Test 7: Agent Gateway CAN access Redis
echo "[Test 7] Agent Gateway CAN access Redis..."
if docker exec agent_gateway python3 -c "import redis; redis.Redis(host='redis', port=6379, db=0, socket_connect_timeout=2).ping()" >/dev/null 2>&1; then
    echo "✅ PASS: Agent Gateway has Redis access (bridge service privilege)"
else
    echo "❌ FAIL: Agent Gateway cannot access Redis"
    FAILED=1
fi
echo ""

# Test 8: MCP Server CAN access Redis
echo "[Test 8] MCP Server CAN access Redis..."
if docker exec mcp_server python3 -c "import redis; redis.Redis(host='redis', port=6379, db=0, socket_connect_timeout=2).ping()" >/dev/null 2>&1; then
    echo "✅ PASS: MCP Server has Redis access (tools tier privilege)"
else
    echo "❌ FAIL: MCP Server cannot access Redis"
    FAILED=1
fi
echo ""

# Test 9: Sandbox MCP Server CANNOT access Redis (strict isolation)
echo "[Test 9] Sandbox MCP Server CANNOT access Redis..."
if docker exec sandbox_mcp_server python3 -c "import redis; redis.Redis(host='redis', port=6379, db=0, socket_connect_timeout=2).ping()" 2>/dev/null; then
    echo "❌ FAIL: Sandbox can access Redis (should be isolated)"
    FAILED=1
else
    echo "✅ PASS: Sandbox isolated from Redis (strict isolation)"
fi
echo ""

# Test 10: Verify network count
echo "[Test 10] Verifying network count..."
NETWORK_COUNT=$(docker network ls | grep -E "adept_(frontend|application|data)" | wc -l)
if [ "$NETWORK_COUNT" -eq 3 ]; then
    echo "✅ PASS: All 3 tier networks created (frontend, application, data)"
else
    echo "⚠️  WARNING: Expected 3 networks, found $NETWORK_COUNT"
fi
echo ""

# Test 11: Langfuse connectivity for observability
echo "[Test 11] Agent Gateway CAN access Langfuse..."
if docker exec agent_gateway python3 -c "import socket; socket.create_connection(('langfuse-web', 3000), timeout=2)" >/dev/null 2>&1; then
    echo "✅ PASS: Agent Gateway has Langfuse access (observability)"
else
    echo "⚠️  WARNING: Agent Gateway cannot access Langfuse (telemetry may fail)"
fi
echo ""

echo "[Test 12] MCP Server CAN access Langfuse..."
if docker exec mcp_server python3 -c "import socket; socket.create_connection(('langfuse-web', 3000), timeout=2)" >/dev/null 2>&1; then
    echo "✅ PASS: MCP Server has Langfuse access (observability)"
else
    echo "⚠️  WARNING: MCP Server cannot access Langfuse (telemetry may fail)"
fi
echo ""

echo "================================================================="
if [ $FAILED -eq 0 ]; then
    echo "✅ All network isolation tests PASSED"
    echo "================================================================="
    echo ""
    echo "Network Isolation Summary:"
    echo "  - JupyterLab: ISOLATED from data tier (Redis, PostgreSQL, Keycloak)"
    echo "  - Sandbox: ISOLATED from data tier (strict isolation)"
    echo "  - Application tier: Full data tier access (authorized)"
    echo "  - Tools tier: Full data tier access (authorized)"
    echo "  - Observability: Langfuse accessible from application/tools tiers"
    exit 0
else
    echo "❌ Network isolation tests FAILED"
    echo "================================================================="
    exit 1
fi
