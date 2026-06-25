#!/usr/bin/env python3
"""Generate catalog.json from temp/mcp/src/ directory.

Scans all AWS MCP server subdirectories, reads pyproject.toml for package
metadata, and produces a static catalog file used by the meta-server.

Usage:
    python scripts/generate-catalog.py [--src-dir PATH] [--output PATH]
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Servers explicitly marked deprecated or excluded
DEPRECATED_SERVERS = {
    "cdk-mcp-server",
    "terraform-mcp-server",
    "code-doc-gen-mcp-server",
    "aws-diagram-mcp-server",
}


def derive_tool_prefix(server_name: str) -> str:
    """Derive a tool namespace prefix from a server directory name."""
    name = server_name
    name = re.sub(r"-mcp-server$", "", name)
    name = re.sub(r"^aws-", "", name)
    name = re.sub(r"^amazon-", "", name)
    name = name.replace("-", "_")
    return name


def parse_pyproject(path: Path) -> dict | None:
    """Parse a pyproject.toml file to extract package metadata.

    Uses a simple regex parser to avoid requiring tomllib/toml dependency.
    """
    text = path.read_text()

    # Extract name
    name_match = re.search(r'^name\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not name_match:
        return None
    package_name = name_match.group(1)

    # Extract description
    desc_match = re.search(r'^description\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    description = desc_match.group(1) if desc_match else ""

    # Extract entry point command (scripts section)
    cmd_match = re.search(
        r'^\[project\.scripts\]\s*\n([^[]+)',
        text,
        re.MULTILINE,
    )
    command = ""
    if cmd_match:
        scripts_block = cmd_match.group(1)
        first_script = re.search(r'^["\']?([^"\'=\s]+)["\']?\s*=', scripts_block, re.MULTILINE)
        if first_script:
            command = first_script.group(1)

    return {
        "package": package_name,
        "description": description,
        "command": command,
    }


def generate_catalog(src_dir: Path) -> list[dict]:
    """Scan src_dir for AWS MCP server directories and build catalog entries."""
    entries = []

    for subdir in sorted(src_dir.iterdir()):
        if not subdir.is_dir():
            continue
        if not subdir.name.endswith("-mcp-server") and subdir.name != "mcp-lambda-handler":
            continue
        if subdir.name in DEPRECATED_SERVERS:
            print(f"  SKIP (deprecated): {subdir.name}", file=sys.stderr)
            continue

        pyproject = subdir / "pyproject.toml"
        if not pyproject.exists():
            print(f"  SKIP (no pyproject.toml): {subdir.name}", file=sys.stderr)
            continue

        meta = parse_pyproject(pyproject)
        if not meta:
            print(f"  SKIP (parse error): {subdir.name}", file=sys.stderr)
            continue

        tool_prefix = derive_tool_prefix(subdir.name)
        command = meta["command"] or f"awslabs.{subdir.name}"
        package = meta["package"] or f"awslabs.{subdir.name}"

        entry = {
            "name": subdir.name,
            "command": command,
            "package": package,
            "description": meta["description"],
            "tool_prefix": tool_prefix,
            "install_cmd": f"pip install {package}",
        }
        entries.append(entry)
        print(f"  OK: {subdir.name} → {tool_prefix}", file=sys.stderr)

    return entries


def main():
    parser = argparse.ArgumentParser(description="Generate AWS MCP server catalog")
    parser.add_argument(
        "--src-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent.parent / "temp" / "mcp" / "src",
        help="Path to temp/mcp/src/ directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "aws_mcp_manager" / "catalog.json",
        help="Output path for catalog.json",
    )
    args = parser.parse_args()

    if not args.src_dir.exists():
        print(f"ERROR: Source directory not found: {args.src_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning: {args.src_dir}", file=sys.stderr)
    entries = generate_catalog(args.src_dir)

    catalog = {
        "version": "1.0",
        "description": "AWS Labs MCP server catalog (auto-generated)",
        "server_count": len(entries),
        "servers": entries,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(catalog, f, indent=2)

    print(f"\nGenerated catalog with {len(entries)} servers → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
