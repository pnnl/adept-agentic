#!/usr/bin/env python3
"""
Docker Compose Definition Linter for ADEPT

Cross-references all docker-compose.yaml files across the project to detect:
  1. Service name collisions on shared networks (DNS shadowing)
  2. Host port conflicts
  3. Container name collisions
  4. Generic service names on shared networks from sub-stacks

This prevents the class of bug where a sub-stack Redis service named "redis"
shadows the ADEPT core Redis on a shared Docker network (Session 98).

Usage:
    python3 scripts/diagnostics/lint_docker_compose.py
    make lint-compose

Exit codes:
    0 — No issues found
    1 — Errors detected
"""

import os
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def find_compose_files(root: str) -> list:
    """Find all docker-compose*.yaml files in the project."""
    compose_files = []
    for dirpath, _, filenames in os.walk(root):
        if any(skip in dirpath for skip in ["/.git/", "/node_modules/", "/__pycache__/"]):
            continue
        for f in filenames:
            if f.startswith("docker-compose") and (f.endswith(".yaml") or f.endswith(".yml")):
                compose_files.append(os.path.join(dirpath, f))
    return sorted(compose_files)


def parse_compose_file(filepath: str) -> dict:
    """Parse a docker-compose file. Uses PyYAML if available, else basic fallback."""
    if yaml is not None:
        with open(filepath) as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                print(f"  WARNING: Could not parse {filepath}: {e}")
                return {}
        return data if isinstance(data, dict) else {}

    # Fallback: extract service and network names without PyYAML
    data = {"services": {}, "networks": {}}
    with open(filepath) as f:
        lines = f.readlines()
    in_services = in_networks = False
    indent_level = 0
    for line in lines:
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        leading = len(line) - len(line.lstrip())
        if stripped == "services:":
            in_services, in_networks, indent_level = True, False, leading
            continue
        elif stripped == "networks:":
            in_networks, in_services, indent_level = True, False, leading
            continue
        elif leading == 0 and stripped.endswith(":"):
            in_services = in_networks = False
            continue
        if in_services and leading == indent_level + 2:
            name = stripped.rstrip(":")
            if not name.startswith(("-", "#")):
                data["services"][name] = {}
        if in_networks and leading == indent_level + 2:
            name = stripped.rstrip(":")
            if not name.startswith(("-", "#")):
                data["networks"][name] = {}
    return data


def extract_service_info(compose_data: dict, filepath: str) -> list:
    """Extract service definitions with their network memberships and ports."""
    services = compose_data.get("services") or {}
    networks_def = compose_data.get("networks") or {}
    results = []

    for svc_name, svc_config in services.items():
        if not isinstance(svc_config, dict):
            svc_config = {}

        container_name = svc_config.get("container_name", svc_name)

        # Resolve network references to actual Docker network names
        svc_networks = []
        raw_networks = svc_config.get("networks", [])
        net_names = raw_networks if isinstance(raw_networks, list) else (
            list(raw_networks.keys()) if isinstance(raw_networks, dict) else []
        )
        for net_ref in net_names:
            net_def = networks_def.get(net_ref, {})
            actual_name = net_def.get("name", net_ref) if isinstance(net_def, dict) else net_ref
            svc_networks.append(actual_name)

        # Extract host ports
        ports = []
        for port_spec in (svc_config.get("ports") or []):
            port_str = str(port_spec)
            parts = port_str.split(":")
            if len(parts) >= 2:
                host_part = parts[-2].split("/")[0]
                if "." in host_part:
                    continue
                # Handle ${VAR:-default} patterns
                if ":-" in host_part:
                    host_part = host_part.split(":-")[1].rstrip("}")
                try:
                    ports.append(int(host_part))
                except ValueError:
                    pass

        results.append({
            "service_name": svc_name,
            "container_name": container_name,
            "networks": svc_networks,
            "ports": ports,
            "file": filepath,
        })
    return results


SHARED_NETWORKS = {
    "adept_application_network",
    "adept_data_network",
    "adept_frontend_network",
    "adept_integration_network",
}

GENERIC_NAMES = {"redis", "postgres", "nginx", "proxy", "worker", "api", "server"}


def lint(root: str) -> int:
    """Run all linting checks. Returns number of errors found."""
    compose_files = find_compose_files(root)
    print(f"Scanning {len(compose_files)} docker-compose files...\n")

    all_services = []
    for filepath in compose_files:
        data = parse_compose_file(filepath)
        if data:
            all_services.extend(extract_service_info(data, filepath))

    errors = warnings = 0
    core_compose_dir = os.path.join(root, "deployment", "local", "docker-compose")

    # CHECK 1: Service name collisions on shared networks
    print("CHECK 1: Service name collisions on shared networks")
    print("-" * 60)
    svc_net_map = defaultdict(list)
    for svc in all_services:
        for net in svc["networks"]:
            svc_net_map[(svc["service_name"], net)].append(svc)

    check1_errors = 0
    for (svc_name, network), entries in sorted(svc_net_map.items()):
        if len(entries) > 1:
            files = [os.path.relpath(e["file"], root) for e in entries]
            print(f"  ERROR: Service '{svc_name}' on network '{network}' defined in:")
            for f in files:
                print(f"    - {f}")
            print(f"  -> Docker DNS will have ambiguous resolution for '{svc_name}'\n")
            errors += 1
            check1_errors += 1
    if check1_errors == 0:
        print("  No collisions found.\n")

    # CHECK 2: Host port conflicts
    print("CHECK 2: Host port conflicts")
    print("-" * 60)
    port_map = defaultdict(list)
    for svc in all_services:
        for port in svc["ports"]:
            port_map[port].append(svc)

    check2_warnings = 0
    for port, entries in sorted(port_map.items()):
        if len(entries) > 1:
            files = set(e["file"] for e in entries)
            if len(files) > 1:
                print(f"  WARNING: Host port {port} used by multiple services:")
                for e in entries:
                    print(f"    - {e['service_name']} ({os.path.relpath(e['file'], root)})")
                print()
                warnings += 1
                check2_warnings += 1
    if check2_warnings == 0:
        print("  No conflicts found.\n")

    # CHECK 3: Container name collisions
    print("CHECK 3: Container name collisions")
    print("-" * 60)
    cname_map = defaultdict(list)
    for svc in all_services:
        cname_map[svc["container_name"]].append(svc)

    check3_errors = 0
    for cname, entries in sorted(cname_map.items()):
        if len(entries) > 1:
            files = set(e["file"] for e in entries)
            if len(files) > 1:
                print(f"  ERROR: Container name '{cname}' in multiple files:")
                for e in entries:
                    print(f"    - service '{e['service_name']}' ({os.path.relpath(e['file'], root)})")
                print()
                errors += 1
                check3_errors += 1
    if check3_errors == 0:
        print("  No collisions found.\n")

    # CHECK 4: Generic service names on shared networks (preventive)
    print("CHECK 4: Generic service names on shared networks (preventive)")
    print("-" * 60)
    check4_warnings = 0
    for svc in all_services:
        if svc["service_name"] in GENERIC_NAMES:
            for net in svc["networks"]:
                if net in SHARED_NETWORKS and not svc["file"].startswith(core_compose_dir):
                    rel_file = os.path.relpath(svc["file"], root)
                    print(f"  WARNING: Generic service name '{svc['service_name']}' on '{net}'")
                    print(f"    File: {rel_file}")
                    print(f"    Container: {svc['container_name']}")
                    print(f"    FIX: Rename service to '{svc['container_name']}'\n")
                    warnings += 1
                    check4_warnings += 1
    if check4_warnings == 0:
        print("  No generic names on shared networks.\n")

    # Summary
    print("=" * 60)
    print(f"SUMMARY: {len(compose_files)} files, {len(all_services)} services, "
          f"{errors} errors, {warnings} warnings")
    if errors > 0:
        print(f"\n  {errors} error(s) must be fixed before deployment.")
    return 1 if errors > 0 else 0


def main():
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent
    if not (project_root / "Makefile").exists():
        project_root = Path.cwd()
    print(f"ADEPT Docker Compose Linter\nProject root: {project_root}\n")
    sys.exit(lint(str(project_root)))


if __name__ == "__main__":
    main()
