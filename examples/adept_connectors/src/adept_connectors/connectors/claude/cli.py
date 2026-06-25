"""CLI entry points for ADEPT Claude Connector.

Subcommands:
    (default)          Run as MCP STDIO server
    --http             Run as HTTP transport server
    setup              Configure Claude Desktop for ADEPT
    provision-users    Bulk-create Keycloak users (admin only)
    doctor             Diagnose connectivity and auth issues
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Optional


def main() -> None:
    """Main entry point — dispatches to subcommand or runs MCP server."""
    parser = argparse.ArgumentParser(
        prog="adept-claude-connector",
        description="MCP server connecting Claude Desktop to an ADEPT instance",
    )
    sub = parser.add_subparsers(dest="command")

    # --- setup ---
    setup_p = sub.add_parser("setup", help="Configure Claude Desktop for ADEPT")
    setup_p.add_argument("--adept-url", required=True, help="ADEPT base URL (e.g. https://your-adept-host.example.com/v1)")
    setup_p.add_argument("--auth-method", default=None, help="Auth method: api_key, password, jwt")
    setup_p.add_argument("--api-key", default=None, help="API key (for api_key auth)")
    setup_p.add_argument("--username", default=None, help="Username (for password auth)")
    setup_p.add_argument("--password", default=None, help="Password (for password auth)")
    setup_p.add_argument("--jwt-token", default=None, help="JWT token (for jwt auth)")
    setup_p.add_argument("--verify-ssl", default=True, type=_str_to_bool, help="Verify TLS (default: true)")

    # --- provision-users ---
    prov_p = sub.add_parser("provision-users", help="Bulk-create Keycloak users (admin)")
    prov_p.add_argument("--email-list", default=None, help="Path to file with one email per line")
    prov_p.add_argument("--email", action="append", default=[], help="Single email (repeatable)")
    prov_p.add_argument("--group", default="notebook-users", help="Keycloak group (default: notebook-users)")
    prov_p.add_argument("--keycloak-url", default="http://localhost:8180", help="Keycloak URL")
    prov_p.add_argument("--admin-username", default="admin", help="Keycloak admin username")
    prov_p.add_argument("--admin-password", default=None, help="Keycloak admin password (or ADEPT_ADMIN_PASSWORD env)")
    prov_p.add_argument("--temporary-password", action="store_true", help="Force password change on first login")
    prov_p.add_argument("--output-format", choices=["table", "csv", "json"], default="table")

    # --- doctor ---
    sub.add_parser("doctor", help="Diagnose connectivity and auth issues")

    args = parser.parse_args()

    if args.command == "setup":
        _cmd_setup(args)
    elif args.command == "provision-users":
        _cmd_provision_users(args)
    elif args.command == "doctor":
        _cmd_doctor()
    elif args.command is None:
        # Default: run MCP server
        if "--http" in sys.argv:
            run_http()
        else:
            run_stdio()
    else:
        parser.print_help()


# -- MCP Server Entry Points --------------------------------------------------


def run_stdio() -> None:
    """Run as MCP STDIO server (default for Claude Desktop)."""
    from .server import create_server

    server = create_server()
    server.run(transport="stdio")


def run_http(host: str = "0.0.0.0", port: int = 9090) -> None:
    """Run as HTTP transport server (for Claude Pro)."""
    from .server import create_server

    server = create_server()
    server.run(transport="streamable-http", host=host, port=port)


# -- setup ---------------------------------------------------------------------


def _cmd_setup(args: argparse.Namespace) -> None:
    """Write Claude Desktop config JSON for ADEPT connection."""
    # Determine auth method from provided flags
    auth_method = args.auth_method
    if auth_method is None:
        if args.api_key:
            auth_method = "api_key"
        elif args.username and args.password:
            auth_method = "password"
        elif args.jwt_token:
            auth_method = "jwt"
        else:
            print("Error: Provide --api-key, --username/--password, or --jwt-token", file=sys.stderr)
            sys.exit(1)

    env = {
        "ADEPT_BASE_URL": args.adept_url,
        "ADEPT_AUTH_METHOD": auth_method,
    }
    if auth_method == "api_key" and args.api_key:
        env["ADEPT_API_KEY"] = args.api_key
    elif auth_method == "password":
        if not args.username or not args.password:
            print("Error: --username and --password required for password auth", file=sys.stderr)
            sys.exit(1)
        env["ADEPT_USERNAME"] = args.username
        env["ADEPT_PASSWORD"] = args.password
        # Keycloak is behind the same nginx proxy — same scheme+host, no path
        from urllib.parse import urlparse
        parsed = urlparse(args.adept_url)
        env["ADEPT_KEYCLOAK_URL"] = f"{parsed.scheme}://{parsed.hostname}"
    elif auth_method == "jwt" and args.jwt_token:
        env["ADEPT_JWT_TOKEN"] = args.jwt_token

    if not args.verify_ssl:
        env["ADEPT_VERIFY_SSL"] = "false"

    # Build Claude Desktop MCP config snippet
    connector_path = _find_connector_path()
    uv_path = _find_uv_path()
    config_snippet = {
        "mcpServers": {
            "adept": {
                "command": uv_path,
                "args": [
                    "run", "--extra", "claude",
                    "--directory", connector_path,
                    "python", "-m", "adept_connectors.connectors.claude",
                ],
                "env": env,
            }
        }
    }

    config_path = _get_claude_desktop_config_path()
    if config_path and config_path.exists():
        _merge_into_config(config_path, config_snippet)
        print(f"Updated Claude Desktop config: {config_path}")
    elif config_path:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config_snippet, indent=2) + "\n")
        print(f"Created Claude Desktop config: {config_path}")
    else:
        print("Could not detect Claude Desktop config path.")
        print("Add this to your claude_desktop_config.json:\n")
        print(json.dumps(config_snippet, indent=2))

    if not args.verify_ssl:
        print("\nWarning: TLS verification disabled. Only use with self-signed certificates.")
    print("\nRestart Claude Desktop to apply changes.")


def _merge_into_config(config_path: Path, snippet: dict) -> None:
    """Merge MCP server config into existing Claude Desktop config."""
    existing = json.loads(config_path.read_text())
    if "mcpServers" not in existing:
        existing["mcpServers"] = {}
    existing["mcpServers"]["adept"] = snippet["mcpServers"]["adept"]
    config_path.write_text(json.dumps(existing, indent=2) + "\n")


def _get_claude_desktop_config_path() -> Optional[Path]:
    """Return platform-specific Claude Desktop config path."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
    elif system == "Linux":
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    return None


def _find_uv_path() -> str:
    """Find the absolute path to the uv binary.

    Prefers well-known install locations over arbitrary $PATH entries to avoid
    picking up bundled copies (e.g. Langflow's ``~/.langflow/uv/uv``) that may
    be outdated or incompatible.
    """
    import shutil

    # 1. Check well-known install locations first (order: most common → least)
    for candidate in [
        Path.home() / ".local" / "bin" / "uv",       # Official installer default
        Path("/opt/homebrew/bin/uv"),                  # Homebrew on macOS ARM
        Path("/usr/local/bin/uv"),                     # Homebrew on macOS Intel / Linux
        Path.home() / ".cargo" / "bin" / "uv",        # Cargo install
    ]:
        if candidate.exists():
            return str(candidate)
    # 2. Fall back to $PATH (may find bundled copies like .langflow/uv/uv)
    uv = shutil.which("uv")
    if uv:
        return uv
    # 3. Last resort — hope it's on PATH at runtime
    return "uv"


def _find_connector_path() -> str:
    """Find the adept_connectors package directory for the uv command."""
    # Walk up from this file to the package root containing pyproject.toml
    # __file__ is connectors/claude/cli.py
    # Package root is 4 levels up: claude -> connectors -> adept_connectors -> src -> (package root with pyproject.toml)
    here = Path(__file__).resolve().parent
    for _ in range(6):
        here = here.parent
        if (here / "pyproject.toml").exists():
            return str(here)
    return str(Path.cwd())


# -- provision-users -----------------------------------------------------------


def _cmd_provision_users(args: argparse.Namespace) -> None:
    """Bulk-create Keycloak users from email list."""
    from ...core.admin.user_provisioning import (
        format_results_csv,
        format_results_json,
        format_results_table,
        provision_users,
    )

    emails = list(args.email)  # --email flags
    if args.email_list:
        path = Path(args.email_list)
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            sys.exit(1)
        emails.extend(line.strip() for line in path.read_text().splitlines() if line.strip())

    if not emails:
        print("Error: Provide --email or --email-list", file=sys.stderr)
        sys.exit(1)

    admin_password = args.admin_password or os.environ.get("ADEPT_ADMIN_PASSWORD", "")
    if not admin_password:
        print("Error: --admin-password or ADEPT_ADMIN_PASSWORD required", file=sys.stderr)
        sys.exit(1)

    results = provision_users(
        emails=emails,
        group=args.group,
        keycloak_url=args.keycloak_url,
        admin_username=args.admin_username,
        admin_password=admin_password,
        temporary_password=args.temporary_password,
    )

    created = sum(1 for r in results if r["status"] == "created")
    skipped = len(results) - created

    if args.output_format == "csv":
        print(format_results_csv(results))
    elif args.output_format == "json":
        print(format_results_json(results))
    else:
        print(f"\nProvisioned {created} users ({skipped} skipped):\n")
        print(format_results_table(results))
        print(f"\nDistribute each user's row securely. They configure Claude Desktop with:")
        print(f"  uv run python -m adept_connectors.connectors.claude setup --adept-url <URL> --username <email> --password <password>")


# -- doctor --------------------------------------------------------------------


def _cmd_doctor() -> None:
    """Diagnose connectivity and auth issues."""
    import asyncio

    asyncio.run(_run_doctor())


async def _run_doctor() -> None:
    """Run diagnostic checks."""
    checks_passed = 0
    checks_total = 0

    # 1. Config loading
    checks_total += 1
    print("Checking configuration...")
    try:
        from ...core.config import AdeptConnectorConfig
        config = AdeptConnectorConfig()
        print(f"  Base URL:    {config.base_url}")
        print(f"  Auth method: {config.auth_method.value}")
        print(f"  Verify SSL:  {config.verify_ssl}")
        checks_passed += 1
        print("  [PASS] Configuration loaded\n")
    except Exception as e:
        print(f"  [FAIL] {e}\n")
        config = None

    if config is None:
        print(f"\nResult: {checks_passed}/{checks_total} checks passed")
        sys.exit(1)

    # 2. Authentication
    checks_total += 1
    print("Checking authentication...")
    try:
        from ...core.auth import AuthManager
        auth = AuthManager(config)
        headers = await auth.get_auth_headers()
        auth_header = headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token_preview = auth_header[7:17] + "..."
            print(f"  Token: {token_preview}")
            checks_passed += 1
            print("  [PASS] Authentication successful\n")
        else:
            print("  [FAIL] No bearer token obtained\n")
    except Exception as e:
        print(f"  [FAIL] {e}\n")

    # 3. Connectivity
    checks_total += 1
    print("Checking ADEPT connectivity...")
    try:
        from ...core.clients.base import BaseAdeptClient
        client = BaseAdeptClient(config, auth, client_source="claude-connector")
        await client._ensure_client()
        resp = await client.get("/responses/models")
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", data) if isinstance(data, dict) else data
            print(f"  Models available: {len(models)}")
            checks_passed += 1
            print("  [PASS] ADEPT reachable\n")
        else:
            print(f"  [FAIL] HTTP {resp.status_code}: {resp.text[:200]}\n")
        await client.close()
    except Exception as e:
        print(f"  [FAIL] {e}\n")

    # 4. MCP proxy endpoint
    checks_total += 1
    print("Checking MCP proxy endpoint...")
    try:
        from ...core.clients.mcp_proxy import MCPProxyClient

        proxy = MCPProxyClient(config, auth)
        print(f"  MCP URL:     {proxy._base_url}")
        tools = await proxy.list_tools()
        print(f"  Tools available: {len(tools)}")
        if tools:
            tool_names = [t.get("name", "?") for t in tools[:5]]
            print(f"  Sample tools: {', '.join(tool_names)}")
        checks_passed += 1
        print("  [PASS] MCP proxy reachable\n")
    except Exception as e:
        print(f"  [FAIL] {e}\n")

    # 5. AG-UI endpoint
    checks_total += 1
    print("Checking AG-UI endpoint...")
    try:
        import httpx as _httpx

        agui_url = f"{config.base_url}/ag-ui/run"
        agui_headers = await auth.get_auth_headers()
        agui_headers["Content-Type"] = "application/json"
        agui_payload = {
            "thread_id": "doctor-probe",
            "run_id": "doctor-probe",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
        }
        async with _httpx.AsyncClient(
            verify=config.verify_ssl,
            timeout=_httpx.Timeout(30),
        ) as agui_client:
            agui_resp = await agui_client.post(
                agui_url, json=agui_payload, headers=agui_headers
            )
        # Accept 200 (success) or 4xx/5xx that proves the endpoint exists
        if agui_resp.status_code in (200, 201):
            checks_passed += 1
            print("  [PASS] AG-UI endpoint reachable\n")
        elif agui_resp.status_code < 500:
            # 400/422 means endpoint exists but payload was rejected — still reachable
            checks_passed += 1
            print(f"  [PASS] AG-UI endpoint reachable (HTTP {agui_resp.status_code})\n")
        else:
            print(f"  [FAIL] HTTP {agui_resp.status_code}: {agui_resp.text[:200]}\n")
    except Exception as e:
        print(f"  [FAIL] {e}\n")

    # 6. Files API endpoint
    checks_total += 1
    print("Checking Files API endpoint...")
    try:
        from ...core.clients.base import BaseAdeptClient as _BaseClient

        files_client = _BaseClient(config, auth, client_source="claude-connector")
        await files_client._ensure_client()
        files_resp = await files_client.get("/files")
        if files_resp.status_code == 200:
            files_data = files_resp.json()
            file_list = files_data.get("data", files_data) if isinstance(files_data, dict) else files_data
            print(f"  Files: {len(file_list)}")
            checks_passed += 1
            print("  [PASS] Files API reachable\n")
        else:
            print(f"  [FAIL] HTTP {files_resp.status_code}: {files_resp.text[:200]}\n")
        await files_client.close()
    except Exception as e:
        print(f"  [FAIL] {e}\n")

    # 7. Claude Desktop config
    checks_total += 1
    print("Checking Claude Desktop config...")
    config_path = _get_claude_desktop_config_path()
    if config_path and config_path.exists():
        try:
            cd_config = json.loads(config_path.read_text())
            if "adept" in cd_config.get("mcpServers", {}):
                checks_passed += 1
                print(f"  Config path: {config_path}")
                print("  [PASS] ADEPT server configured\n")
            else:
                print(f"  [WARN] Config exists but no 'adept' server entry\n")
        except Exception as e:
            print(f"  [FAIL] Cannot parse config: {e}\n")
    else:
        print(f"  [SKIP] Config not found at {config_path}\n")
        checks_passed += 1  # Not a failure on servers

    print(f"Result: {checks_passed}/{checks_total} checks passed")
    if checks_passed < checks_total:
        sys.exit(1)


# -- Helpers -------------------------------------------------------------------


def _str_to_bool(v: str) -> bool:
    return v.lower() in ("true", "1", "yes")


if __name__ == "__main__":
    main()
