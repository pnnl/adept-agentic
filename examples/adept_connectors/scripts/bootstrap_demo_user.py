#!/usr/bin/env python3
"""Bootstrap, verify, or delete demo users in Keycloak for ADEPT Claude Desktop Connector.

Usage:
    # Create a single user
    python3 scripts/bootstrap_demo_user.py create \
        --keycloak-url http://localhost:8180 \
        --admin-password admin \
        --email alice.test@pnnl.gov \
        --password AdeptTest2026! \
        --group notebook-users streamlit-users

    # Create multiple users (comma, semicolon, or space separated)
    python3 scripts/bootstrap_demo_user.py create \
        --keycloak-url http://localhost:8180 \
        --admin-password admin \
        --email "alice@pnnl.gov, bob@pnnl.gov; carol@pnnl.gov" \
        --password AdeptTest2026! \
        --group notebook-users

    # Delete a single user
    python3 scripts/bootstrap_demo_user.py delete \
        --keycloak-url http://localhost:8180 \
        --admin-password admin \
        --email alice.test@pnnl.gov

    # Delete multiple users
    python3 scripts/bootstrap_demo_user.py delete \
        --keycloak-url http://localhost:8180 \
        --admin-password admin \
        --email "alice@pnnl.gov, bob@pnnl.gov, carol@pnnl.gov"

    # Verify user can authenticate (ROPC flow)
    python3 scripts/bootstrap_demo_user.py verify \
        --keycloak-url http://localhost:8180 \
        --email alice.test@pnnl.gov \
        --password AdeptTest2026!

Prerequisites:
    pip install requests   (or: uv add requests)
"""
from __future__ import annotations

import argparse
import re
import sys

import requests


def _parse_emails(raw: str) -> list[str]:
    """Split a string of emails by comma, semicolon, or whitespace."""
    return [e.strip() for e in re.split(r"[,;\s]+", raw) if e.strip()]


def get_admin_token(
    keycloak_url: str,
    admin_username: str,
    admin_password: str,
    admin_client_secret: str | None,
    verify_ssl: bool,
) -> str:
    """Get admin token via password grant on admin-cli."""
    token_url = f"{keycloak_url}/realms/master/protocol/openid-connect/token"
    data = {
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": admin_username,
        "password": admin_password,
    }
    if admin_client_secret:
        data["client_secret"] = admin_client_secret
    resp = requests.post(token_url, data=data, verify=verify_ssl)
    resp.raise_for_status()
    return resp.json()["access_token"]


def create_user(
    keycloak_url: str,
    token: str,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    temporary_password: bool,
    verify_ssl: bool,
) -> dict:
    """Create a user in Keycloak master realm."""
    users_url = f"{keycloak_url}/admin/realms/master/users"
    payload = {
        "username": email,
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "enabled": True,
        "emailVerified": True,
        "credentials": [
            {
                "type": "password",
                "value": password,
                "temporary": temporary_password,
            }
        ],
    }
    resp = requests.post(
        users_url,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        verify=verify_ssl,
    )
    if resp.status_code == 409:
        print(f"  User {email} already exists (409 Conflict)")
        return get_user(keycloak_url, token, email, verify_ssl)
    resp.raise_for_status()
    print(f"  Created user: {email}")
    return get_user(keycloak_url, token, email, verify_ssl)


def get_user(keycloak_url: str, token: str, email: str, verify_ssl: bool) -> dict | None:
    """Look up user by username. Returns None if not found."""
    url = f"{keycloak_url}/admin/realms/master/users?username={email}&exact=true"
    resp = requests.get(
        url, headers={"Authorization": f"Bearer {token}"}, verify=verify_ssl
    )
    resp.raise_for_status()
    users = resp.json()
    return users[0] if users else None


def delete_user(
    keycloak_url: str, token: str, user_id: str, email: str, verify_ssl: bool
) -> bool:
    """Delete a user from Keycloak by user ID."""
    url = f"{keycloak_url}/admin/realms/master/users/{user_id}"
    resp = requests.delete(
        url, headers={"Authorization": f"Bearer {token}"}, verify=verify_ssl
    )
    if resp.status_code == 204:
        print(f"  Deleted: {email}")
        return True
    elif resp.status_code == 404:
        print(f"  Not found: {email}")
        return False
    resp.raise_for_status()
    return False


def get_group_id(
    keycloak_url: str, token: str, group_name: str, verify_ssl: bool
) -> str:
    """Look up group ID by name."""
    url = f"{keycloak_url}/admin/realms/master/groups?search={group_name}"
    resp = requests.get(
        url, headers={"Authorization": f"Bearer {token}"}, verify=verify_ssl
    )
    resp.raise_for_status()
    groups = resp.json()
    for g in groups:
        if g["name"] == group_name:
            return g["id"]
    raise RuntimeError(
        f"Group '{group_name}' not found. Available: {[g['name'] for g in groups]}"
    )


def add_user_to_group(
    keycloak_url: str,
    token: str,
    user_id: str,
    group_id: str,
    group_name: str,
    verify_ssl: bool,
) -> None:
    """Add user to a Keycloak group."""
    url = f"{keycloak_url}/admin/realms/master/users/{user_id}/groups/{group_id}"
    resp = requests.put(
        url, headers={"Authorization": f"Bearer {token}"}, verify=verify_ssl
    )
    resp.raise_for_status()
    print(f"  Added to group: {group_name}")


def verify_ropc(
    keycloak_url: str,
    email: str,
    password: str,
    client_id: str,
    verify_ssl: bool,
) -> bool:
    """Verify ROPC login works for the user."""
    token_url = f"{keycloak_url}/realms/master/protocol/openid-connect/token"
    data = {
        "grant_type": "password",
        "client_id": client_id,
        "username": email,
        "password": password,
    }
    resp = requests.post(token_url, data=data, verify=verify_ssl)
    if resp.status_code == 200:
        token_data = resp.json()
        print(f"  ROPC login: SUCCESS (expires_in={token_data['expires_in']}s)")
        return True
    else:
        print(f"  ROPC login: FAILED ({resp.status_code}: {resp.text[:200]})")
        return False


def verify_adept_api(
    adept_url: str, jwt: str, verify_ssl: bool
) -> bool:
    """Verify JWT works against ADEPT API."""
    resp = requests.get(
        f"{adept_url}/responses/models",
        headers={"Authorization": f"Bearer {jwt}"},
        verify=verify_ssl,
    )
    if resp.status_code == 200:
        data = resp.json()
        models = data.get("data", data) if isinstance(data, dict) else data
        print(f"  ADEPT API: SUCCESS ({len(models)} models)")
        return True
    else:
        print(f"  ADEPT API: FAILED ({resp.status_code}: {resp.text[:200]})")
        return False


# ── Subcommand: create ─────────────────────────────────────────────


def cmd_create(args) -> None:
    verify_ssl = not args.no_verify_ssl
    keycloak_url = args.keycloak_url.rstrip("/")
    api_keycloak_url = (args.external_keycloak_url or keycloak_url).rstrip("/")
    emails = _parse_emails(args.email)

    if not args.password:
        print("Error: --password is required", file=sys.stderr)
        sys.exit(1)
    if not args.admin_password:
        print("Error: --admin-password is required for user creation", file=sys.stderr)
        sys.exit(1)

    print(f"\n1. Authenticating as admin...")
    token = get_admin_token(
        keycloak_url, args.admin_username, args.admin_password,
        args.admin_client_secret, verify_ssl,
    )
    print(f"  Admin token obtained")

    for i, email in enumerate(emails, 1):
        first_name = email.split("@")[0].split(".")[0].capitalize()
        last_name = args.last_name

        print(f"\n--- User {i}/{len(emails)}: {email} ---")

        print(f"\n2. Creating user {email}...")
        user = create_user(
            keycloak_url, token, email, args.password,
            first_name, last_name, args.temporary_password, verify_ssl,
        )
        user_id = user["id"]
        print(f"  User ID: {user_id}")

        print(f"\n3. Adding to group(s): {', '.join(args.group)}...")
        for group_name in args.group:
            group_id = get_group_id(keycloak_url, token, group_name, verify_ssl)
            add_user_to_group(keycloak_url, token, user_id, group_id, group_name, verify_ssl)

        print(f"\n4. Verifying ROPC login...")
        verify_ropc(keycloak_url, email, args.password, args.ropc_client_id, verify_ssl)

        if args.adept_url:
            print(f"\n5. Verifying ADEPT API access...")
            token_url = f"{api_keycloak_url}/realms/master/protocol/openid-connect/token"
            resp = requests.post(
                token_url,
                data={
                    "grant_type": "password",
                    "client_id": args.ropc_client_id,
                    "username": email,
                    "password": args.password,
                },
                verify=verify_ssl,
            )
            jwt = resp.json()["access_token"]
            verify_adept_api(args.adept_url.rstrip("/"), jwt, verify_ssl)

    print(f"\n{'='*50}")
    print(f"  Created {len(emails)} user(s)")
    for email in emails:
        print(f"  - {email}")
    print(f"  Password: {args.password}")
    print(f"  Group(s): {', '.join(args.group)}")


# ── Subcommand: delete ─────────────────────────────────────────────


def cmd_delete(args) -> None:
    verify_ssl = not args.no_verify_ssl
    keycloak_url = args.keycloak_url.rstrip("/")
    emails = _parse_emails(args.email)

    if not args.admin_password:
        print("Error: --admin-password is required for user deletion", file=sys.stderr)
        sys.exit(1)

    print(f"\n1. Authenticating as admin...")
    token = get_admin_token(
        keycloak_url, args.admin_username, args.admin_password,
        args.admin_client_secret, verify_ssl,
    )
    print(f"  Admin token obtained")

    deleted = 0
    not_found = 0
    for i, email in enumerate(emails, 1):
        print(f"\n[{i}/{len(emails)}] Deleting {email}...")
        user = get_user(keycloak_url, token, email, verify_ssl)
        if user is None:
            print(f"  Not found: {email}")
            not_found += 1
            continue
        if delete_user(keycloak_url, token, user["id"], email, verify_ssl):
            deleted += 1

    print(f"\n{'='*50}")
    print(f"  Deleted: {deleted}, Not found: {not_found}, Total: {len(emails)}")


# ── Subcommand: verify ─────────────────────────────────────────────


def cmd_verify(args) -> None:
    verify_ssl = not args.no_verify_ssl
    keycloak_url = args.keycloak_url.rstrip("/")
    api_keycloak_url = (args.external_keycloak_url or keycloak_url).rstrip("/")
    emails = _parse_emails(args.email)

    if not args.password:
        print("Error: --password is required for verification", file=sys.stderr)
        sys.exit(1)

    all_ok = True
    for email in emails:
        print(f"\nVerifying login for {email}...")
        ok = verify_ropc(keycloak_url, email, args.password, args.ropc_client_id, verify_ssl)
        if ok and args.adept_url:
            token_url = f"{api_keycloak_url}/realms/master/protocol/openid-connect/token"
            resp = requests.post(
                token_url,
                data={
                    "grant_type": "password",
                    "client_id": args.ropc_client_id,
                    "username": email,
                    "password": args.password,
                },
                verify=verify_ssl,
            )
            jwt = resp.json()["access_token"]
            verify_adept_api(args.adept_url.rstrip("/"), jwt, verify_ssl)
        if not ok:
            all_ok = False

    sys.exit(0 if all_ok else 1)


# ── CLI Entry Point ────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create, delete, or verify demo users in Keycloak for ADEPT connector testing"
    )
    # Shared arguments
    parser.add_argument("--keycloak-url", required=True, help="Keycloak base URL")
    parser.add_argument("--admin-username", default="admin", help="Admin username")
    parser.add_argument("--admin-password", default=None, help="Admin password")
    parser.add_argument(
        "--admin-client-secret", default=None, help="admin-cli client secret (if confidential)"
    )
    parser.add_argument("--email", required=True, help="Email(s) — comma, semicolon, or space separated")
    parser.add_argument("--no-verify-ssl", action="store_true", help="Skip TLS verification")

    sub = parser.add_subparsers(dest="command", help="Action to perform")

    # create
    create_p = sub.add_parser("create", help="Create user(s) in Keycloak")
    create_p.add_argument("--password", default=None, help="User password")
    create_p.add_argument("--last-name", default="Test", help="Last name")
    create_p.add_argument("--group", nargs="+", default=["notebook-users"], help="Keycloak group(s), space-separated")
    create_p.add_argument("--temporary-password", action="store_true", help="Force password change on first login")
    create_p.add_argument("--ropc-client-id", default="login-client", help="Client ID for ROPC verification")
    create_p.add_argument("--adept-url", default=None, help="ADEPT base URL for API verification")
    create_p.add_argument("--external-keycloak-url", default=None, help="External Keycloak URL for API token")

    # delete
    sub.add_parser("delete", help="Delete user(s) from Keycloak")

    # verify
    verify_p = sub.add_parser("verify", help="Verify user login (ROPC flow)")
    verify_p.add_argument("--password", default=None, help="User password")
    verify_p.add_argument("--ropc-client-id", default="login-client", help="Client ID for ROPC verification")
    verify_p.add_argument("--adept-url", default=None, help="ADEPT base URL for API verification")
    verify_p.add_argument("--external-keycloak-url", default=None, help="External Keycloak URL for API token")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        print("\nError: a command is required: create, delete, or verify", file=sys.stderr)
        sys.exit(1)

    if args.command == "create":
        cmd_create(args)
    elif args.command == "delete":
        cmd_delete(args)
    elif args.command == "verify":
        cmd_verify(args)


if __name__ == "__main__":
    main()
