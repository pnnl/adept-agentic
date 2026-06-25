#!/usr/bin/env python3
"""
Register Academy MCP server tools with the ADEPT Gateway.

Derives tool names, descriptions, and parameter schemas directly from the
FastMCP tool definitions in tools/agent_lifecycle.py — no hardcoded
duplicates.  Validates every schema with Pydantic before sending.

Replaces the former hardcoded Makefile TOOL_*_SCHEMA variables.

Usage:
    python scripts/register_academy_tools.py                # register all
    python scripts/register_academy_tools.py deregister     # remove all
    python scripts/register_academy_tools.py verify         # check Redis
    python scripts/register_academy_tools.py show-schemas   # print JSON schemas
"""

from __future__ import annotations

import argparse
import base64
import importlib
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, get_args, get_origin, get_type_hints

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Ensure academy_mcp_server package is importable
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PKG_ROOT = _SCRIPT_DIR.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

# ---------------------------------------------------------------------------
# Framework-injected fields — stripped before registration
# ---------------------------------------------------------------------------
_FRAMEWORK_INJECTED_FIELDS = frozenset(
    {
        "mcp_session_id",
        "session_id",
        "multi_agent_session_id",
        "gateway_session_id",
        "execution_timeout",
        "user_context",
        "session_hierarchy",
        "execution_context",
        "user_id",
        "username",
        "ctx",
    }
)

# Python type -> JSON Schema type mapping
_TYPE_MAP: Dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
}


# ---------------------------------------------------------------------------
# Pydantic model for a validated tool definition
# ---------------------------------------------------------------------------
class ToolDefinition(BaseModel):
    """A single external-tool registration payload, validated before use."""

    name: str = Field(description="Unique tool name")
    display_name: str = Field(description="Display name on MCP server")
    description: str = Field(description="Human-readable tool description")
    args_schema: Dict[str, Any] = Field(
        default_factory=dict,
        description="Flat property map: {param: {type, description, default?}}",
    )


# ---------------------------------------------------------------------------
# Schema extraction from FastMCP tool functions
# ---------------------------------------------------------------------------
TOOL_MODULE = "tools.agent_lifecycle"


def _resolve_type(annotation: Any) -> type:
    """Unwrap Optional / Annotated to the base Python type."""
    origin = get_origin(annotation)

    if hasattr(annotation, "__class__") and annotation.__class__.__name__ == "_AnnotatedAlias":
        return _resolve_type(get_args(annotation)[0])

    import typing
    if origin is typing.Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if args:
            return _resolve_type(args[0])

    if isinstance(annotation, type):
        return annotation
    return str


def _extract_tool(func) -> ToolDefinition:
    """Extract a ToolDefinition from a captured tool function."""
    tool_name = func.__name__

    raw_doc = inspect.getdoc(func) or ""
    paragraphs = raw_doc.split("\n\n")
    description = paragraphs[0].replace("\n", " ").strip()
    if len(paragraphs) > 1:
        description += " " + paragraphs[1].replace("\n", " ").strip()

    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        hints = {}

    args_schema: Dict[str, Any] = {}
    for pname, param in sig.parameters.items():
        if pname in _FRAMEWORK_INJECTED_FIELDS:
            continue
        if pname in ("self", "cls"):
            continue

        annotation = hints.get(pname, param.annotation)
        if annotation is inspect.Parameter.empty:
            annotation = str

        base_type = _resolve_type(annotation)
        json_type = _TYPE_MAP.get(base_type, "string")

        prop: Dict[str, Any] = {"type": json_type}

        if param.default is not inspect.Parameter.empty and param.default is not None:
            prop["default"] = param.default

        args_schema[pname] = prop

    return ToolDefinition(
        name=tool_name,
        display_name=tool_name,
        description=description,
        args_schema=args_schema,
    )


def discover_tools() -> List[ToolDefinition]:
    """Discover and validate all Academy tool definitions."""
    mod = importlib.import_module(TOOL_MODULE)

    captured: list = []

    class _MockMCP:
        """Fake MCP server that captures @mcp.tool() decorated functions."""

        def tool(self):
            def decorator(func):
                captured.append(func)
                return func
            return decorator

    mock = _MockMCP()
    mod.register(mock)

    tools = []
    for func in captured:
        tool = _extract_tool(func)
        tools.append(tool)
    return tools


# ---------------------------------------------------------------------------
# Configuration
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
    project_root = _PKG_ROOT.parent.parent
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
            print(f"  Clearing stale cached token (issuer={cached_issuer})")
            cache_file.unlink()
    except Exception:
        pass


def _find_engine() -> str:
    """Find a working Docker engine command."""
    try:
        subprocess.run(
            ["docker", "info"], capture_output=True, check=True, timeout=10
        )
        return "docker"
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        print("WARNING: Cannot connect to Docker.")
        return "docker"


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def register_tools_action(tools: List[ToolDefinition]) -> bool:
    """Register all tools with the ADEPT gateway via the agentic CLI."""
    cfg = _get_config()
    cli = _find_agentic_cli()
    mcp = _mcp_url(cfg)

    _clear_stale_token(cfg)

    print(f"--> Registering {len(tools)} Academy tools at {mcp}...")

    engine = _find_engine()
    try:
        subprocess.run(
            [engine, "exec", "academy_mcp_server", "curl", "-sf", "http://localhost:9004/health"],
            capture_output=True, check=True, timeout=10,
        )
        print("  Academy MCP server is healthy")
    except Exception:
        print("  WARNING: Academy MCP server health check failed")

    passed = 0
    failed = 0
    for tool in tools:
        schema_json = json.dumps(tool.args_schema)
        cmd = [
            cli, "tools", "register", tool.name,
            "-d", tool.description,
            "-p", "mcp",
            "-u", mcp,
            "--tool-name", tool.display_name,
            "--args-schema", schema_json,
            "--username", cfg["admin_user"],
            "--password", cfg["admin_pass"],
        ]
        print(f"  Registering {tool.name}... ", end="", flush=True)
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=30)
            print("OK")
            passed += 1
        except subprocess.CalledProcessError:
            print("FAILED")
            failed += 1

    print(f"\nResult: {passed}/{len(tools)} tools registered successfully")
    return failed == 0


def deregister_tools_action(tools: List[ToolDefinition]) -> bool:
    """Remove all tools from the ADEPT gateway."""
    cfg = _get_config()
    cli = _find_agentic_cli()

    _clear_stale_token(cfg)

    print(f"--> Deregistering {len(tools)} Academy tools...")

    passed = 0
    for tool in tools:
        cmd = [
            cli, "tools", "delete", tool.name, "--yes",
            "--username", cfg["admin_user"],
            "--password", cfg["admin_pass"],
        ]
        print(f"  Deregistering {tool.name}... ", end="", flush=True)
        try:
            subprocess.run(
                cmd, capture_output=True, check=True, timeout=30,
            )
            print("OK")
            passed += 1
        except subprocess.CalledProcessError:
            print("FAILED (may not exist)")

    print(f"\nResult: {passed}/{len(tools)} tools deregistered")
    return True


def verify_tools_action(tools: List[ToolDefinition]) -> bool:
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
        key = f"external_tool:{tool.name}"
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
                        print(f"  + {tool.name} found in Redis (with args_schema)")
                    else:
                        print(f"  ~ {tool.name} found in Redis (WARNING: missing args_schema)")
                except json.JSONDecodeError:
                    print(f"  ~ {tool.name} found in Redis (invalid JSON)")
                found += 1
            else:
                print(f"  - {tool.name} NOT found in Redis")
        except Exception:
            print(f"  - {tool.name} Redis lookup failed")

    print(f"\nResult: {found}/{len(tools)} tools verified in Redis")
    return found == len(tools)


def show_schemas(tools: List[ToolDefinition]) -> None:
    """Print discovered tool definitions as JSON to stdout (machine-readable)."""
    output = []
    for tool in tools:
        output.append({
            "name": tool.name,
            "display_name": tool.display_name,
            "description": tool.description,
            "args_schema": tool.args_schema,
        })
    print(json.dumps(output, indent=2))


def show_usage() -> None:
    cfg = _get_config()
    print(f"""Usage: python {sys.argv[0]} [register|deregister|verify|show-schemas|help]

Commands:
  register      Register all Academy tools with ADEPT (default)
  deregister    Remove all Academy tools from ADEPT
  verify        Check that tools exist in Redis
  show-schemas  Print discovered tool schemas (for debugging)
  help          Show this message

Environment:
  KEYCLOAK_URL           (default: http://keycloak:8180)
  AGENT_GATEWAY_URL      (default: http://localhost:8083)
  ACADEMY_MCP_HOST       (default: academy_mcp_server)
  ACADEMY_MCP_PORT       (default: 9004)
  ADMIN_USER             (default: admin)
  ADMIN_PASS             (default: admin)

Tool schemas are derived from @mcp.tool() decorated functions in tools/agent_lifecycle.py.
No manual schema maintenance is needed.""")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register Academy MCP tools with ADEPT Gateway",
        add_help=False,
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="register",
        choices=["register", "deregister", "verify", "show-schemas", "help"],
    )
    args = parser.parse_args()

    if args.action == "help":
        show_usage()
        return

    tools = discover_tools()

    # show-schemas outputs clean JSON to stdout — no config preamble
    if args.action == "show-schemas":
        show_schemas(tools)
        return

    cfg = _get_config()
    print(f"Configuration:")
    print(f"  KEYCLOAK_URL:       {cfg['keycloak_url']}")
    print(f"  AGENT_GATEWAY_URL:  {cfg['gateway_url']}")
    print(f"  MCP_URL:            {_mcp_url(cfg)}")
    print(f"  Tools discovered:   {len(tools)}")
    for t in tools:
        params = list(t.args_schema.keys())
        print(f"    - {t.name} ({len(params)} params: {', '.join(params) or 'none'})")
    print()

    if args.action == "register":
        ok = register_tools_action(tools)
        print()
        verify_tools_action(tools)
        sys.exit(0 if ok else 1)
    elif args.action == "deregister":
        deregister_tools_action(tools)
    elif args.action == "verify":
        ok = verify_tools_action(tools)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
