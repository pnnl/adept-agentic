#!/usr/bin/env python3
"""
Manage A2A Gateway Registrations in the Gateway Registry.

Fixes public_url to use the correct /a2a endpoint path for A2A protocol
compatibility (AgentCard discovery, JSONRPC messaging).

Usage (run inside orchestration_service or agent_gateway container):
    python3 manage_gateway_registrations.py list
    python3 manage_gateway_registrations.py fix-urls
    python3 manage_gateway_registrations.py register --alias aws-gateway --ip 10.0.0.1 --tags aws,us-west-2
    python3 manage_gateway_registrations.py delete --alias aws-gateway
    python3 manage_gateway_registrations.py verify --alias aws-gateway

Run from host via docker exec:
    docker exec orchestration_service python3 /app/scripts/a2a/manage_gateway_registrations.py list
    docker exec orchestration_service python3 /app/scripts/a2a/manage_gateway_registrations.py fix-urls
    docker exec orchestration_service python3 /app/scripts/a2a/manage_gateway_registrations.py register \\
        --alias aws-gateway --ip 10.0.0.1 --tags aws,us-west-2 --description "AWS EC2 Gateway"
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8180")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")
GATEWAY_REGISTRY_URL = os.getenv("GATEWAY_REGISTRY_URL", "http://gateway_registry:8086")

# Service client with admin role (required for DELETE operations)
SERVICE_CLIENT_ID = os.getenv("VALIDATION_RUNNER_CLIENT_ID", "validation-runner-client")

# Credential discovery paths (in order of preference)
SECRET_PATHS = [
    "/app/credentials/VALIDATION_RUNNER_CLIENT_SECRET",
    "/run/secrets/VALIDATION_RUNNER_CLIENT_SECRET",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def discover_client_secret() -> str:
    """Discover VALIDATION_RUNNER_CLIENT_SECRET from env or credential files."""
    # 1. Environment variable
    secret = os.getenv("VALIDATION_RUNNER_CLIENT_SECRET", "").strip()
    if secret:
        return secret

    # 2. Credential files
    for path in SECRET_PATHS:
        p = Path(path)
        if p.exists():
            val = p.read_text().strip()
            if val:
                return val

    # 3. Consolidated credentials file
    for cred_file in [
        "/app/credentials/.env-keycloak-credentials",
        "/app/.env-keycloak-credentials-dir/.env-keycloak-credentials",
    ]:
        p = Path(cred_file)
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith("VALIDATION_RUNNER_CLIENT_SECRET="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        return val

    print("ERROR: Could not discover VALIDATION_RUNNER_CLIENT_SECRET", file=sys.stderr)
    print("  Set it via environment variable or ensure credential files exist.", file=sys.stderr)
    sys.exit(1)


def get_admin_token() -> str:
    """Get an admin-capable token via client_credentials grant."""
    secret = discover_client_secret()
    token_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"

    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": SERVICE_CLIENT_ID,
                "client_secret": secret,
            },
        )
        if resp.status_code != 200:
            print(f"ERROR: Token request failed: {resp.status_code} — {resp.text}", file=sys.stderr)
            sys.exit(1)
        return resp.json()["access_token"]


def registry_request(method: str, path: str, token: str, json_body=None):
    """Make an authenticated request to the Gateway Registry."""
    url = f"{GATEWAY_REGISTRY_URL}{path}"
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(timeout=15.0) as client:
        resp = client.request(method, url, headers=headers, json=json_body)
    return resp


def make_a2a_url(ip: str) -> str:
    """Construct the correct A2A public_url for a given IP."""
    return f"https://{ip}/a2a"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(args):
    """List all registered gateways."""
    token = get_admin_token()
    resp = registry_request("GET", "/v1/gateways/", token)
    if resp.status_code != 200:
        print(f"ERROR: {resp.status_code} — {resp.text}", file=sys.stderr)
        sys.exit(1)

    gateways = resp.json()

    # Separate real vs test gateways
    real = [g for g in gateways if not g["alias"].startswith("test-gateway-")]
    test = [g for g in gateways if g["alias"].startswith("test-gateway-")]

    print(f"\n{'='*70}")
    print(f"  Gateway Registry: {GATEWAY_REGISTRY_URL}")
    print(f"  Total: {len(gateways)} ({len(real)} real, {len(test)} test fixtures)")
    print(f"{'='*70}\n")

    if real:
        print("  Real Gateways:")
        print(f"  {'Alias':<25} {'Public URL':<40} {'Health'}")
        print(f"  {'-'*25} {'-'*40} {'-'*10}")
        for g in real:
            alias = g["alias"]
            url = g.get("public_url", "N/A")
            health = g.get("health_status", "Unknown")

            # Flag URLs that don't end with /a2a
            url_ok = url.endswith("/a2a")
            marker = "" if url_ok else "  <-- WRONG (needs /a2a)"

            print(f"  {alias:<25} {url:<40} {health}{marker}")
        print()

    if test and args.show_test:
        print(f"  Test Fixtures ({len(test)}):")
        for g in test:
            print(f"    {g['alias']}: {g.get('public_url', 'N/A')}")
        print()


def cmd_register(args):
    """Register a new gateway or re-register with correct URL."""
    token = get_admin_token()
    alias = args.alias
    public_url = make_a2a_url(args.ip)
    description = args.description or f"Gateway at {args.ip}"
    tags = args.tags.split(",") if args.tags else []

    # Check if already registered
    resp = registry_request("GET", f"/v1/gateways/{alias}", token)
    if resp.status_code == 200:
        existing = resp.json()
        existing_url = existing.get("public_url", "")
        if existing_url == public_url:
            print(f"  Already registered: {alias} -> {public_url}")
            return
        else:
            print(f"  Existing registration: {alias} -> {existing_url}")
            print(f"  Needs update to:       {alias} -> {public_url}")
            print(f"  Deleting old registration...")
            del_resp = registry_request("DELETE", f"/v1/gateways/{alias}", token)
            if del_resp.status_code not in (200, 204, 404):
                print(f"  ERROR: Delete failed: {del_resp.status_code} — {del_resp.text}", file=sys.stderr)
                sys.exit(1)
            print(f"  Deleted.")

    # Register
    capabilities = []
    if description:
        capabilities.append(f"description:{description}")
    for tag in tags:
        tag = tag.strip()
        if tag:
            capabilities.append(f"tag:{tag}")

    body = {
        "alias": alias,
        "public_url": public_url,
        "capabilities": capabilities,
    }

    resp = registry_request("POST", "/v1/gateways", token, json_body=body)
    if resp.status_code == 200:
        print(f"  Registered: {alias} -> {public_url}")
    else:
        print(f"  ERROR: Registration failed: {resp.status_code} — {resp.text}", file=sys.stderr)
        sys.exit(1)

    # Verify agent-card is reachable
    cmd_verify_alias(alias, token)


def cmd_delete(args):
    """Delete a gateway registration."""
    token = get_admin_token()
    alias = args.alias

    resp = registry_request("DELETE", f"/v1/gateways/{alias}", token)
    if resp.status_code in (200, 204):
        print(f"  Deleted: {alias}")
    elif resp.status_code == 404:
        print(f"  Not found: {alias} (already deleted)")
    else:
        print(f"  ERROR: {resp.status_code} — {resp.text}", file=sys.stderr)
        sys.exit(1)


def cmd_fix_urls(args):
    """Fix all gateway registrations that have wrong public_url (missing /a2a)."""
    token = get_admin_token()
    resp = registry_request("GET", "/v1/gateways/", token)
    if resp.status_code != 200:
        print(f"ERROR: {resp.status_code} — {resp.text}", file=sys.stderr)
        sys.exit(1)

    gateways = resp.json()

    # Filter to real gateways with HTTPS URLs that don't end with /a2a
    fixable = []
    for g in gateways:
        alias = g["alias"]
        url = g.get("public_url", "")
        if alias.startswith("test-gateway-") or alias.startswith("test-"):
            continue
        if url.startswith("https://") and not url.endswith("/a2a"):
            fixable.append(g)

    if not fixable:
        print("  All gateway URLs already use /a2a. Nothing to fix.")
        return

    print(f"\n  Found {len(fixable)} gateway(s) with incorrect public_url:\n")
    for g in fixable:
        alias = g["alias"]
        old_url = g["public_url"]
        # Extract IP from URL
        ip = old_url.replace("https://", "").split("/")[0].split(":")[0]
        new_url = make_a2a_url(ip)
        print(f"    {alias}: {old_url} -> {new_url}")

    if not args.yes:
        confirm = input("\n  Proceed with fix? [y/N]: ").strip().lower()
        if confirm != "y":
            print("  Aborted.")
            return

    print()
    for g in fixable:
        alias = g["alias"]
        old_url = g["public_url"]
        ip = old_url.replace("https://", "").split("/")[0].split(":")[0]
        new_url = make_a2a_url(ip)
        capabilities = g.get("capabilities", [])

        # Delete old
        del_resp = registry_request("DELETE", f"/v1/gateways/{alias}", token)
        if del_resp.status_code not in (200, 204, 404):
            print(f"  ERROR deleting {alias}: {del_resp.status_code}", file=sys.stderr)
            continue

        # Re-register with correct URL
        body = {
            "alias": alias,
            "public_url": new_url,
            "capabilities": capabilities,
        }
        reg_resp = registry_request("POST", "/v1/gateways", token, json_body=body)
        if reg_resp.status_code == 200:
            print(f"  Fixed: {alias} -> {new_url}")
        else:
            print(f"  ERROR re-registering {alias}: {reg_resp.status_code} — {reg_resp.text}", file=sys.stderr)

    print()
    cmd_verify_all(token)


def cmd_verify(args):
    """Verify a gateway's agent-card is reachable."""
    token = get_admin_token()
    cmd_verify_alias(args.alias, token)


def cmd_verify_alias(alias: str, token: str):
    """Verify a specific gateway alias has a reachable agent-card."""
    resp = registry_request("GET", f"/v1/gateways/{alias}", token)
    if resp.status_code == 404:
        print(f"  VERIFY {alias}: NOT REGISTERED")
        return
    if resp.status_code != 200:
        print(f"  VERIFY {alias}: ERROR {resp.status_code}")
        return

    gateway = resp.json()
    public_url = gateway.get("public_url", "")
    agent_card_url = f"{public_url.rstrip('/')}/.well-known/agent-card.json"

    print(f"  VERIFY {alias}:")
    print(f"    public_url:  {public_url}")
    print(f"    agent-card:  {agent_card_url}")

    try:
        with httpx.Client(timeout=10.0, verify=False) as client:
            card_resp = client.get(agent_card_url)
        if card_resp.status_code == 200:
            card = card_resp.json()
            print(f"    status:      200 OK")
            print(f"    name:        {card.get('name', 'N/A')}")
            print(f"    url:         {card.get('url', 'N/A')}")
            print(f"    protocol:    {card.get('protocolVersion', 'N/A')}")
            skills = card.get("skills", [])
            print(f"    skills:      {len(skills)} ({', '.join(s.get('name','') for s in skills)})")
        else:
            print(f"    status:      {card_resp.status_code} FAILED")
            print(f"    response:    {card_resp.text[:200]}")
    except Exception as e:
        print(f"    status:      ERROR — {e}")


def cmd_verify_all(token: str):
    """Verify all real gateways."""
    resp = registry_request("GET", "/v1/gateways/", token)
    if resp.status_code != 200:
        return
    for g in resp.json():
        alias = g["alias"]
        if alias.startswith("test-gateway-") or alias.startswith("test-"):
            continue
        url = g.get("public_url", "")
        if url.startswith("https://"):
            cmd_verify_alias(alias, token)
            print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Manage A2A Gateway Registrations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all registered gateways
  python3 manage_gateway_registrations.py list

  # Fix URLs that are missing /a2a (interactive)
  python3 manage_gateway_registrations.py fix-urls

  # Fix URLs non-interactively
  python3 manage_gateway_registrations.py fix-urls --yes

  # Register a new gateway
  python3 manage_gateway_registrations.py register --alias aws-gateway --ip 10.0.0.1

  # Register with full options
  python3 manage_gateway_registrations.py register \\
      --alias aws-gateway --ip 10.0.0.1 \\
      --description "AWS EC2 Gateway" --tags aws,us-west-2

  # Delete a gateway
  python3 manage_gateway_registrations.py delete --alias aws-gateway

  # Verify agent-card reachability
  python3 manage_gateway_registrations.py verify --alias aws-gateway
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="List all registered gateways")
    p_list.add_argument("--show-test", action="store_true", help="Include test fixture entries")

    # register
    p_reg = subparsers.add_parser("register", help="Register or re-register a gateway with correct /a2a URL")
    p_reg.add_argument("--alias", required=True, help="Gateway alias (e.g., aws-gateway)")
    p_reg.add_argument("--ip", required=True, help="Gateway IP address (e.g., 10.0.0.1)")
    p_reg.add_argument("--description", help="Human-readable description")
    p_reg.add_argument("--tags", help="Comma-separated tags (e.g., aws,us-west-2)")

    # delete
    p_del = subparsers.add_parser("delete", help="Delete a gateway registration")
    p_del.add_argument("--alias", required=True, help="Gateway alias to delete")

    # fix-urls
    p_fix = subparsers.add_parser("fix-urls", help="Fix all gateway URLs to use /a2a endpoint")
    p_fix.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")

    # verify
    p_ver = subparsers.add_parser("verify", help="Verify a gateway's agent-card is reachable")
    p_ver.add_argument("--alias", required=True, help="Gateway alias to verify")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "register":
        cmd_register(args)
    elif args.command == "delete":
        cmd_delete(args)
    elif args.command == "fix-urls":
        cmd_fix_urls(args)
    elif args.command == "verify":
        cmd_verify(args)


if __name__ == "__main__":
    main()
