#!/usr/bin/env python3
"""
generate-registration-schemas.py
================================

Introspects the FastMCP app's tool registry and generates tool_registry.json —
the contract file that register-slurm-tools.sh consumes for registration.

Pydantic models define and validate the JSON structure. If introspection
produces invalid data, this script fails at generation time — not at
registration time inside bash.

Usage:
    # Generate scripts/tool_registry.json (default)
    python3 scripts/generate-registration-schemas.py

    # Generate with explicit output path
    python3 scripts/generate-registration-schemas.py --output /tmp/registry.json

    # Check if existing tool_registry.json matches live introspection
    python3 scripts/generate-registration-schemas.py --check

    # Inspect a single tool's schema
    python3 scripts/generate-registration-schemas.py --tool deception_submit_job

Exit codes:
    0 — Success (or --check found no drift)
    1 — --check found drift between tool_registry.json and live schemas
    2 — Import or introspection error
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

SCRIPT_DIR = Path(__file__).parent
SLURM_MCP_DIR = SCRIPT_DIR.parent / "slurm_mcp_server"
DEFAULT_OUTPUT = SCRIPT_DIR / "tool_registry.json"

TOOL_PREFIX = "slurm_hpc"

# 4 local tools have shortened registered names; all others use {prefix}_{remote_name}
REGISTERED_NAME_OVERRIDES = {
    "submit_slurm_job": "submit_job",
    "cancel_slurm_job": "cancel_job",
    "list_cluster_jobs": "list_jobs",
    "get_cluster_summary": "cluster_summary",
}


# ---------------------------------------------------------------------------
# Pydantic contract models
# ---------------------------------------------------------------------------

class ToolEntry(BaseModel):
    """A single tool's registration metadata."""

    registered_name: str
    remote_name: str
    description: str
    args_schema: Dict[str, Any]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "registered_name": "slurm_hpc_deception_submit_job",
                    "remote_name": "deception_submit_job",
                    "description": "Submit a batch job to Deception HPC cluster.",
                    "args_schema": {
                        "request": {"type": "object", "description": "Job submission request."},
                        "mcp_session_id": {"type": "string", "description": "Framework-injected session ID."},
                    },
                }
            ]
        }
    )


class ToolRegistry(BaseModel):
    """Complete tool registry written to tool_registry.json."""

    tool_prefix: str
    tools: List[ToolEntry]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tool_prefix": "slurm_hpc",
                    "tools": [ToolEntry.model_config["json_schema_extra"]["examples"][0]],
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# FastMCP introspection
# ---------------------------------------------------------------------------

def load_mcp_app():
    """Import and return the FastMCP app with all tool modules loaded."""
    sys.path.insert(0, str(SLURM_MCP_DIR))
    os.environ.setdefault("SLURM_MCP_MODE", "local")

    from slurm_mcp.app import app
    from slurm_mcp import tools  # noqa: F401
    from slurm_mcp.deception import tools as _d  # noqa: F401
    from slurm_mcp.tahoma import tools as _t  # noqa: F401
    from slurm_mcp import ssh_key_tools as _s  # noqa: F401
    from slurm_mcp import workspace_tools as _w  # noqa: F401

    return app


def _simplify_schema(properties: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simplify FastMCP's JSON Schema into the flat format that
    _create_args_schema() in external_tool_manager.py expects.

    Resolves anyOf (Optional[T]) patterns, preserves nested objects,
    and strips metadata that _create_args_schema() doesn't consume.
    """
    simplified = {}

    for field_name, field_schema in properties.items():
        entry: Dict[str, Any] = {}

        if "anyOf" in field_schema:
            non_null = [t for t in field_schema["anyOf"] if t.get("type") != "null"]
            entry["type"] = non_null[0].get("type", "string") if non_null else "string"
        elif "type" in field_schema:
            entry["type"] = field_schema["type"]
        else:
            entry["type"] = "object"

        if "description" in field_schema:
            entry["description"] = field_schema["description"]

        if "default" in field_schema:
            entry["default"] = field_schema["default"]

        if entry["type"] == "object" and "properties" in field_schema:
            entry["properties"] = _simplify_nested(field_schema["properties"])
            if "required" in field_schema:
                entry["required"] = field_schema["required"]

        if entry["type"] == "array" and "items" in field_schema:
            entry["items"] = field_schema["items"]

        simplified[field_name] = entry

    return simplified


def _simplify_nested(properties: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively simplify nested object properties."""
    result = {}
    for name, schema in properties.items():
        entry: Dict[str, Any] = {}
        if "anyOf" in schema:
            non_null = [t for t in schema["anyOf"] if t.get("type") != "null"]
            entry["type"] = non_null[0].get("type", "string") if non_null else "string"
        elif "type" in schema:
            entry["type"] = schema["type"]
        else:
            entry["type"] = "string"

        if "description" in schema:
            entry["description"] = schema["description"]
        if "default" in schema:
            entry["default"] = schema["default"]
        if entry["type"] == "object" and "properties" in schema:
            entry["properties"] = _simplify_nested(schema["properties"])
            if "required" in schema:
                entry["required"] = schema["required"]
        if entry["type"] == "array" and "items" in schema:
            entry["items"] = schema["items"]
        result[name] = entry
    return result


def _registered_name(remote_name: str) -> str:
    """Compute the gateway-registered name from the MCP remote tool name."""
    suffix = REGISTERED_NAME_OVERRIDES.get(remote_name, remote_name)
    return f"{TOOL_PREFIX}_{suffix}"


def generate_registry(app) -> ToolRegistry:
    """
    Introspect the FastMCP app and return a validated ToolRegistry.

    Pydantic validates on construction — if any field has wrong type,
    this raises ValidationError at generation time.
    """
    tool_map = app._tool_manager._tools
    entries = []

    for tool_name, tool in sorted(tool_map.items()):
        params = tool.parameters
        properties = params.get("properties", {})
        args_schema = _simplify_schema(properties) if properties else {}

        entries.append(ToolEntry(
            registered_name=_registered_name(tool_name),
            remote_name=tool_name,
            description=tool.description,
            args_schema=args_schema,
        ))

    return ToolRegistry(tool_prefix=TOOL_PREFIX, tools=entries)


# ---------------------------------------------------------------------------
# CLI modes
# ---------------------------------------------------------------------------

def do_generate(app, output_path: Path) -> None:
    """Generate tool_registry.json from live introspection."""
    registry = generate_registry(app)
    output_path.write_text(registry.model_dump_json(indent=2))
    print(f"Generated {output_path.name}: {len(registry.tools)} tools")


def do_check(app, registry_path: Path) -> None:
    """Compare live introspection against existing tool_registry.json."""
    if not registry_path.exists():
        print(f"ERROR: {registry_path} not found. Run without --check first.", file=sys.stderr)
        sys.exit(1)

    live = generate_registry(app)
    existing = ToolRegistry.model_validate_json(registry_path.read_text())

    live_map = {t.registered_name: t for t in live.tools}
    existing_map = {t.registered_name: t for t in existing.tools}

    drift = []
    for name, live_entry in live_map.items():
        if name not in existing_map:
            drift.append((name, "not in tool_registry.json"))
            continue
        existing_entry = existing_map[name]
        if live_entry.args_schema != existing_entry.args_schema:
            live_keys = set(live_entry.args_schema.keys())
            existing_keys = set(existing_entry.args_schema.keys())
            missing = live_keys - existing_keys
            extra = existing_keys - live_keys
            if missing:
                drift.append((name, f"missing fields: {missing}"))
            elif extra:
                drift.append((name, f"extra fields: {extra}"))
            else:
                drift.append((name, "schema content differs"))
        if live_entry.description != existing_entry.description:
            drift.append((name, "description changed"))

    for name in existing_map:
        if name not in live_map:
            drift.append((name, "in tool_registry.json but not in MCP app"))

    if drift:
        print(f"DRIFT DETECTED: {len(drift)} issue(s):\n")
        for tool_name, reason in drift:
            print(f"  {tool_name}: {reason}")
        print(f"\nFix: cd examples/slurm_hpc && make generate-schemas")
        sys.exit(1)
    else:
        print(f"OK: All {len(live.tools)} tool schemas match tool_registry.json")
        sys.exit(0)


def do_tool(app, tool_name: str) -> None:
    """Print a single tool's registration entry."""
    registry = generate_registry(app)
    for entry in registry.tools:
        if entry.remote_name == tool_name:
            print(entry.model_dump_json(indent=2))
            return
    names = sorted(e.remote_name for e in registry.tools)
    print(f"ERROR: Tool '{tool_name}' not found. Available: {names}", file=sys.stderr)
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser(
        description="Generate tool_registry.json from FastMCP introspection"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check if tool_registry.json matches live introspection (exit 1 if drift)"
    )
    parser.add_argument(
        "--tool", type=str, default=None,
        help="Output a single tool's registration entry"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output path for tool_registry.json (default: {DEFAULT_OUTPUT})"
    )
    args = parser.parse_args()

    try:
        app = load_mcp_app()
    except Exception as e:
        print(f"ERROR: Failed to load MCP app: {e}", file=sys.stderr)
        sys.exit(2)

    if args.tool:
        do_tool(app, args.tool)
    elif args.check:
        do_check(app, args.output)
    else:
        do_generate(app, args.output)


if __name__ == "__main__":
    main()
