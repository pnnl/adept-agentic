#!/bin/bash
# Validate volume isolation in Docker Compose environment
# Tests that JupyterLab and sandbox_mcp_server CANNOT access infrastructure directories

set -e

echo "================================================================="
echo "Docker Compose Volume Isolation Validation (Session 50 Phase 0)"
echo "================================================================="
echo ""

FAILED=0

# Test 1: JupyterLab isolation from postgres_data
echo "[Test 1] JupyterLab CANNOT access postgres_data..."
if docker exec jupyterlab ls /home/jovyan/work/data/postgres_data 2>/dev/null; then
    echo "❌ FAIL: JupyterLab can access postgres_data"
    FAILED=1
else
    echo "✅ PASS: JupyterLab isolated from postgres_data"
fi
echo ""

# Test 2: JupyterLab isolation from nginx_certs
echo "[Test 2] JupyterLab CANNOT access nginx_certs..."
if docker exec jupyterlab ls /home/jovyan/work/data/nginx_certs 2>/dev/null; then
    echo "❌ FAIL: JupyterLab can access nginx_certs"
    FAILED=1
else
    echo "✅ PASS: JupyterLab isolated from nginx_certs"
fi
echo ""

# Test 3: JupyterLab isolation from n8n_data
echo "[Test 3] JupyterLab CANNOT access n8n_data..."
if docker exec jupyterlab ls /home/jovyan/work/data/n8n_data 2>/dev/null; then
    echo "❌ FAIL: JupyterLab can access n8n_data"
    FAILED=1
else
    echo "✅ PASS: JupyterLab isolated from n8n_data"
fi
echo ""

# Test 4: JupyterLab isolation from redis_data
echo "[Test 4] JupyterLab CANNOT access redis_data..."
if docker exec jupyterlab ls /home/jovyan/work/data/redis_data 2>/dev/null; then
    echo "❌ FAIL: JupyterLab can access redis_data"
    FAILED=1
else
    echo "✅ PASS: JupyterLab isolated from redis_data"
fi
echo ""

# Test 5: JupyterLab CAN access uploaded_files
echo "[Test 5] JupyterLab CAN access uploaded_files..."
if docker exec jupyterlab ls /home/jovyan/work/data/uploaded_files >/dev/null 2>&1; then
    echo "✅ PASS: JupyterLab has access to uploaded_files"
else
    echo "❌ FAIL: JupyterLab cannot access uploaded_files (should be accessible)"
    FAILED=1
fi
echo ""

# Test 6: JupyterLab CAN access notebooks
echo "[Test 6] JupyterLab CAN access notebooks..."
if docker exec jupyterlab ls /home/jovyan/work/notebooks >/dev/null 2>&1; then
    echo "✅ PASS: JupyterLab has access to notebooks"
else
    echo "❌ FAIL: JupyterLab cannot access notebooks (should be accessible)"
    FAILED=1
fi
echo ""

# Test 7: Sandbox isolation from postgres_data
echo "[Test 7] Sandbox CANNOT access postgres_data..."
if docker exec sandbox_mcp_server ls /app/data/postgres_data 2>/dev/null; then
    echo "❌ FAIL: Sandbox can access postgres_data"
    FAILED=1
else
    echo "✅ PASS: Sandbox isolated from postgres_data"
fi
echo ""

# Test 8: Sandbox isolation from nginx_certs
echo "[Test 8] Sandbox CANNOT access nginx_certs..."
if docker exec sandbox_mcp_server ls /app/data/nginx_certs 2>/dev/null; then
    echo "❌ FAIL: Sandbox can access nginx_certs"
    FAILED=1
else
    echo "✅ PASS: Sandbox isolated from nginx_certs"
fi
echo ""

# Test 9: Sandbox CAN access uploaded_files
echo "[Test 9] Sandbox CAN access uploaded_files..."
if docker exec sandbox_mcp_server ls /app/data/uploaded_files >/dev/null 2>&1; then
    echo "✅ PASS: Sandbox has access to uploaded_files"
else
    echo "❌ FAIL: Sandbox cannot access uploaded_files (should be accessible)"
    FAILED=1
fi
echo ""

# Test 10: Sandbox CAN access workspace
echo "[Test 10] Sandbox CAN access workspace..."
if docker exec sandbox_mcp_server ls /workspace >/dev/null 2>&1; then
    echo "✅ PASS: Sandbox has access to workspace"
else
    echo "❌ FAIL: Sandbox cannot access workspace (should be accessible)"
    FAILED=1
fi
echo ""

echo "================================================================="
if [ $FAILED -eq 0 ]; then
    echo "✅ All volume isolation tests PASSED"
    echo "================================================================="
    exit 0
else
    echo "❌ Volume isolation tests FAILED"
    echo "================================================================="
    exit 1
fi
