#!/usr/bin/env python3
"""
Host-side tool registration from a JSON schema file.

Reads tool definitions (name, description, args_schema) from a JSON file
produced by `register_academy_tools.py show-schemas` inside the container,
then registers each tool with the ADEPT Gateway via the agentic CLI.

This script does NOT import academy-py or any container-only dependencies.

Usage:
    python scripts/register_from_schemas.py /tmp/academy_schemas.json
    python scripts/register_from_schemas.py /tmp/academy_schemas.json deregister
    python scripts/register_from_schemas.py /tmp/academy_schemas.json verify
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration (from environment, matching canonical pattern)
# ---------------------------------------------------------------------------
def _get_config() -> dict:
    return {
        "keycloak_url": os.environ.get("KEYCLOAK_URL", "http://keycloak:8180"),
        "keycloak_realm": os.environ.get("KEYCLOAK_REALM", "master"),
        "gateway_url": os.environ.get("AGENT_GATEWAY_URL", "http://localhost:8083"),
        "admin_user": os.environ.get("ADMIN_USER", "admin"),
        "admin_pass": os.environ.get("ADMIN_PASS", "admin"),
        "mcp_host": os.environ.get("ACADEMY_MCP_HOST", "academy_mcp_server"),
        "mcp_port": os.environ.get("ACADEMY_MCP_PORT", "9004"),
    }


def _mcp_url(cfg: dict) -> str:
    return f"http://{cfg['mcp_host']}:{cfg['mcp_port']}/mcp"


def _find_agentic_cli() -> str:
    """Locate the agentic CLI binary."""
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent.parent  # examples/academy_mcp_server/scripts -> project root
    candidates = [
        project_root / ".venv311" / "bin" / "agentic",
        project_root / ".venv" / "bin" / "agentic",
    ]
    which = shutil.which("agentic")
    if which:
        candidates.append(Path(which))

    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return str(c)

    print("ERROR: agentic CLI not found.", file=sys.stderr)
    print(f"  Install: pip install -e {project_root / 'src'}/", file=sys.stderr)
    sys.exit(1)


def _clear_stale_token(cfg: dict) -> None:
    """Clear cached admin token if it has the wrong issuer."""
    cache_file = Path.home() / ".adept-agentic" / "cache" / "admin_token.json"
    if not cache_file.exists():
        return
    try:
        data = json.loads(cache_file.read_text())
        parts = data["access_token"].split(".")
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        cached_issuer = payload.get("iss", "")
        expected = f"{cfg['keycloak_url']}/realms/{cfg['keycloak_realm']}"
        if cached_issuer and cached_issuer != expected:
            print(f"  Clearing stale cached token (issuer={cached_issuer}, expected={expected})")
            cache_file.unlink()
    except Exception:
        pass


def _find_engine() -> str:
    """Find a working Docker engine command."""
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return "docker"
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return "docker"


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def register_tools(tools: list, cfg: dict) -> bool:
    """Register all tools with the ADEPT gateway via the agentic CLI."""
    cli = _find_agentic_cli()
    mcp = _mcp_url(cfg)
    _clear_stale_token(cfg)

    print(f"--> Registering {len(tools)} Academy tools at {mcp}...")

    # Health check
    engine = _find_engine()
    try:
        subprocess.run(
            [engine, "exec", cfg["mcp_host"], "curl", "-sf",
             f"http://localhost:{cfg['mcp_port']}/health"],
            capture_output=True, check=True, timeout=10,
        )
        print("  Academy MCP server is healthy")
    except Exception:
        print("  WARNING: Academy MCP server health check failed")

    passed = 0
    failed = 0
    for tool in tools:
        schema_json = json.dumps(tool["args_schema"])
        display_name = tool.get("display_name", tool["name"])
        cmd = [
            cli, "tools", "register", tool["name"],
            "-d", tool["description"],
            "-p", "mcp",
            "-u", mcp,
            "--tool-name", display_name,
            "--args-schema", schema_json,
            "--username", cfg["admin_user"],
            "--password", cfg["admin_pass"],
        ]
        print(f"  Registering {tool['name']}... ", end="", flush=True)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            print("OK")
            passed += 1
        except subprocess.CalledProcessError as e:
            print("FAILED")
            if e.stderr:
                print(f"    stderr: {e.stderr.strip()[:200]}")
            failed += 1

    print(f"\nResult: {passed}/{len(tools)} tools registered successfully")
    return failed == 0


def deregister_tools(tools: list, cfg: dict) -> bool:
    """Remove all tools from the ADEPT gateway."""
    cli = _find_agentic_cli()
    _clear_stale_token(cfg)

    print(f"--> Deregistering {len(tools)} Academy tools...")
    passed = 0
    for tool in tools:
        cmd = [
            cli, "tools", "delete", tool["name"], "--yes",
            "--username", cfg["admin_user"],
            "--password", cfg["admin_pass"],
        ]
        print(f"  Deregistering {tool['name']}... ", end="", flush=True)
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=30)
            print("OK")
            passed += 1
        except subprocess.CalledProcessError:
            print("FAILED (may not exist)")

    print(f"\nResult: {passed}/{len(tools)} tools deregistered")
    return True


def verify_tools(tools: list) -> bool:
    """Verify tools exist in Redis."""
    engine = _find_engine()

    print("--> Verifying Academy tool registration in Redis...")
    try:
        subprocess.run(
            [engine, "exec", "redis", "redis-cli", "PING"],
            capture_output=True, check=True, timeout=10,
        )
    except Exception:
        print("  WARNING: Cannot reach Redis via docker exec.")
        return False

    found = 0
    for tool in tools:
        key = f"external_tool:{tool['name']}"
        try:
            result = subprocess.run(
                [engine, "exec", "redis", "redis-cli", "GET", key],
                capture_output=True, text=True, check=True, timeout=10,
            )
            val = result.stdout.strip()
            if val and val != "(nil)":
                try:
                    data = json.loads(val)
                    if data.get("args_schema") is not None:
                        print(f"  + {tool['name']} found in Redis (with args_schema)")
                    else:
                        print(f"  ~ {tool['name']} found in Redis (WARNING: missing args_schema)")
                except json.JSONDecodeError:
                    print(f"  ~ {tool['name']} found in Redis (invalid JSON)")
                found += 1
            else:
                print(f"  - {tool['name']} NOT found in Redis")
        except Exception:
            print(f"  - {tool['name']} Redis lookup failed")

    print(f"\nResult: {found}/{len(tools)} tools verified in Redis")
    return found == len(tools)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <schemas.json> [register|deregister|verify]")
        sys.exit(1)

    schema_file = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else "register"

    with open(schema_file) as f:
        tools = json.load(f)

    cfg = _get_config()
    print("Configuration:")
    print(f"  KEYCLOAK_URL:       {cfg['keycloak_url']}")
    print(f"  AGENT_GATEWAY_URL:  {cfg['gateway_url']}")
    print(f"  MCP_URL:            {_mcp_url(cfg)}")
    print(f"  agentic CLI:        {_find_agentic_cli()}")
    print(f"  Tools:              {len(tools)}")
    for t in tools:
        params = list(t.get("args_schema", {}).keys())
        print(f"    - {t['name']} ({len(params)} params: {', '.join(params) or 'none'})")
    print()

    if action == "register":
        ok = register_tools(tools, cfg)
        print()
        verify_tools(tools)
        sys.exit(0 if ok else 1)
    elif action == "deregister":
        deregister_tools(tools, cfg)
    elif action == "verify":
        ok = verify_tools(tools)
        sys.exit(0 if ok else 1)
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
