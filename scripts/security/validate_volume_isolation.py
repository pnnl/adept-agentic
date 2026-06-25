#!/usr/bin/env python3
"""
Validate volume isolation by attempting unauthorized filesystem access.
Should FAIL when volume restrictions are properly configured.

This script validates that user-facing services (JupyterLab, sandbox_mcp_server)
CANNOT access sensitive infrastructure directories.

Exit codes:
  0 - All isolation checks passed (secure)
  1 - Isolation failure detected (security vulnerability)
"""
import os
import sys

def test_jupyterlab_isolation():
    """Test that JupyterLab CANNOT access infrastructure data."""
    print("="*70)
    print("JUPYTERLAB VOLUME ISOLATION VALIDATION")
    print("="*70)
    print()

    # Directories that should NOT be accessible
    restricted_paths = [
        "/home/jovyan/work/data/postgres_data",
        "/home/jovyan/work/data/nginx_certs",
        "/home/jovyan/work/data/n8n_data",
        "/home/jovyan/work/data/redis_data",
        "/home/jovyan/work/data/openwebui_data",
        "/home/jovyan/work/data/mgmt_ui_data",
    ]

    failed = False

    for path in restricted_paths:
        if os.path.exists(path):
            print(f"❌ SECURITY FAILURE: Can access {path}")
            failed = True
        else:
            print(f"✅ BLOCKED: Cannot access {path}")

    print()

    # Verify legitimate access still works
    allowed_paths = [
        "/home/jovyan/work/data/uploaded_files",
        "/home/jovyan/work/notebooks",
    ]

    for path in allowed_paths:
        if os.path.exists(path):
            print(f"✅ ALLOWED: Can access {path}")
        else:
            print(f"❌ FAILURE: Cannot access {path} (should be accessible)")
            failed = True

    print()

    if failed:
        print("❌ SECURITY VALIDATION FAILED: JupyterLab has unauthorized access")
        return False
    else:
        print("✅ SECURITY OK: JupyterLab properly isolated")
        return True

def test_sandbox_isolation():
    """Test that sandbox_mcp_server CANNOT access infrastructure data."""
    print("="*70)
    print("SANDBOX MCP SERVER VOLUME ISOLATION VALIDATION")
    print("="*70)
    print()

    # Directories that should NOT be accessible
    restricted_paths = [
        "/app/data/postgres_data",
        "/app/data/nginx_certs",
        "/app/data/n8n_data",
        "/app/data/redis_data",
        "/app/data/openwebui_data",
        "/app/data/mgmt_ui_data",
    ]

    failed = False

    for path in restricted_paths:
        if os.path.exists(path):
            print(f"❌ SECURITY FAILURE: Can access {path}")
            failed = True
        else:
            print(f"✅ BLOCKED: Cannot access {path}")

    print()

    # Verify legitimate access still works
    allowed_paths = [
        "/app/data/uploaded_files",
        "/workspace",
    ]

    for path in allowed_paths:
        if os.path.exists(path):
            print(f"✅ ALLOWED: Can access {path}")
        else:
            print(f"❌ FAILURE: Cannot access {path} (should be accessible)")
            failed = True

    print()

    if failed:
        print("❌ SECURITY VALIDATION FAILED: Sandbox has unauthorized access")
        return False
    else:
        print("✅ SECURITY OK: Sandbox properly isolated")
        return True

if __name__ == "__main__":
    # Detect which environment we're running in
    if os.path.exists("/home/jovyan"):
        success = test_jupyterlab_isolation()
    elif os.path.exists("/workspace"):
        success = test_sandbox_isolation()
    else:
        print("❌ ERROR: Unknown environment (not JupyterLab or sandbox_mcp_server)")
        sys.exit(1)

    sys.exit(0 if success else 1)
