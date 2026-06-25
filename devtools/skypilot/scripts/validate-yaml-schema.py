#!/usr/bin/env python3
"""validate-yaml-schema.py — SkyPilot YAML schema and environment variable validation.

Validates:
  1. Required SkyPilot keys (name, setup, run)
  2. Cloud YAML: resources block (cloud, cpus, memory, disk_size, ports)
  3. Environment variable coverage: all ${VAR} in setup/run have matching envs
  4. No hardcoded secrets in YAML
  5. Critical Ansible parity patterns present

Usage:
  python3 scripts/validate-yaml-schema.py [yaml_dir]
  Default: /app/skypilot/tasks/
"""

import os
import re
import sys
import yaml
from pathlib import Path

YAML_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/app/skypilot/tasks")

ERRORS = 0
WARNINGS = 0


def error(msg):
    global ERRORS
    ERRORS += 1
    print(f"  ERROR: {msg}")


def warn(msg):
    global WARNINGS
    WARNINGS += 1
    print(f"  WARN:  {msg}")


def check(label, condition):
    if condition:
        print(f"  {label}: PASS")
    else:
        error(f"{label}: FAIL")


def validate_yaml(yaml_path):
    print(f"\n--- Validating: {yaml_path.name} ---")

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        error("YAML root is not a mapping")
        return

    # 1. Required top-level keys
    check("name exists", "name" in data)
    check("setup exists", "setup" in data)
    check("run exists", "run" in data)

    # 2. Resources block (cloud tasks only)
    if "resources" in data:
        res = data["resources"]
        check("resources.cloud", "cloud" in res)
        check("resources.disk_size >= 100", res.get("disk_size", 0) >= 100)
        check("resources.ports defined", "ports" in res and len(res["ports"]) > 0)
        check("resources.use_spot is false", res.get("use_spot") is False)

        # Verify critical ports
        ports = res.get("ports", [])
        for port in [443, 80]:
            check(f"port {port} exposed", port in ports)

    # 3. Environment variable coverage
    envs = data.get("envs", {})
    setup = data.get("setup", "")
    run = data.get("run", "")
    full_script = setup + "\n" + run

    # Find all ${VAR} and $VAR references (excluding positional $1, $?, etc.)
    var_refs = set(re.findall(r'\$\{([A-Z_][A-Z0-9_]*)\}', full_script))
    var_refs.update(re.findall(r'\$([A-Z_][A-Z0-9_]+)', full_script))

    # Exclude standard shell/system variables
    system_vars = {
        "USER", "HOME", "PATH", "PWD", "SHELL", "LANG", "TERM",
        "HOSTNAME", "AVAILABLE_GB", "PUBLIC_IP", "PUBLIC_HOST",
        "WORKSPACE", "ADEPT_DIR", "DEPLOY_DATE", "OS_FAMILY",
        "CERT_DIR", "DAEMON_EOF",
    }
    undeclared = var_refs - set(envs.keys()) - system_vars
    if undeclared:
        # Only warn — some vars are set within the script itself
        for var in sorted(undeclared):
            # Check if it's set within the script (VAR=value)
            if re.search(rf'^[ \t]*{var}=', full_script, re.MULTILINE):
                continue  # Script-local variable, OK
            warn(f"${{{var}}} used but not in envs and not set in script")

    # Check for unused envs
    for env_key in envs:
        if env_key not in var_refs and f"${env_key}" not in full_script:
            warn(f"envs.{env_key} declared but not referenced in setup/run")

    # 4. No hardcoded secrets
    secret_patterns = [
        (r'AKIA[0-9A-Z]{16}', "AWS access key"),
        (r'(?i)password\s*=\s*["\'][^"\']+["\']', "hardcoded password"),
        (r'-----BEGIN (RSA |EC )?PRIVATE KEY-----', "private key"),
    ]
    raw_text = open(yaml_path).read()
    for pattern, desc in secret_patterns:
        if re.search(pattern, raw_text):
            error(f"Potential {desc} found in YAML")


def validate_ansible_parity(yaml_path):
    """Check that critical Ansible playbook phases are present."""
    print(f"\n--- Ansible Parity: {yaml_path.name} ---")

    raw = open(yaml_path).read()
    is_cloud = "resources:" in raw  # Cloud task has resources block

    # Universal checks (both cloud and existing-VM)
    check("unprivileged port binding (sysctl)",
          "unprivileged_port_start" in raw)
    check("/etc/hosts entries",
          "api.agentic.local" in raw)
    check("TLS certificate generation",
          "openssl req" in raw)
    check("Docker smoke test",
          "hello-world" in raw)
    check("Docker permissions (DinD)",
          "chmod 2777" in raw)
    check("make create-env-symlink",
          "create-env-symlink" in raw)
    check("make init-shared-volume-permissions",
          "init-shared-volume-permissions" in raw)

    # Cloud-specific checks
    if is_cloud:
        check("disk space validation (df)",
              "df " in raw and "AVAILABLE_GB" in raw)
        check("Docker data root migration (conditional)",
              "DockerRootDir" in raw or "data-root" in raw)

    # Existing-VM-specific checks
    if not is_cloud:
        check("OS family detection",
              "OS_FAMILY" in raw)
        check("Rocky Docker install (dnf)",
              "dnf" in raw and "docker-ce" in raw)
        check("firewall rules (firewall-cmd or ufw)",
              "firewall-cmd" in raw or "ufw" in raw)
        check("Podman cleanup",
              "podman" in raw and "reset" in raw)


if __name__ == "__main__":
    print("============================================")
    print("SkyPilot YAML Schema Validation")
    print("============================================")

    yaml_files = sorted(YAML_DIR.glob("*.yaml"))
    if not yaml_files:
        print(f"ERROR: No YAML files found in {YAML_DIR}")
        sys.exit(1)

    for yf in yaml_files:
        validate_yaml(yf)
        validate_ansible_parity(yf)

    print("\n============================================")
    if ERRORS == 0:
        print(f"ALL CHECKS PASSED ({WARNINGS} warnings)")
        sys.exit(0)
    else:
        print(f"FAILED: {ERRORS} error(s), {WARNINGS} warning(s)")
        sys.exit(1)
