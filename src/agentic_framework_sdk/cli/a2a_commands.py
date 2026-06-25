"""
CLI A2A (Agent-to-Agent) commands for Agentic Framework.

Provides token generation for federated A2A communication between ADEPT instances.
"""

import asyncio
import os
import sys
from typing import Optional, Coroutine, Any
from datetime import datetime, timedelta
import concurrent.futures

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

try:
    from ..auth.credential_manager import CredentialManager
    CREDENTIALS_AVAILABLE = True
except ImportError:
    try:
        from agentic_framework_sdk.auth.credential_manager import CredentialManager
        CREDENTIALS_AVAILABLE = True
    except ImportError:
        CREDENTIALS_AVAILABLE = False
        CredentialManager = None

console = Console()


async def _get_registry_auth_token(profile: str = "default") -> Optional[str]:
    """
    Get authentication token for Gateway Registry operations.

    Credential discovery priority:
    1. CredentialManager profile (from ~/.adept-agentic/credentials)
    2. Environment variables (backward compatibility)

    Args:
        profile: Credential profile name (default: "default")

    Returns:
        JWT access token or None if authentication fails
    """
    client_id = None
    client_secret = None
    keycloak_url = None
    realm = None

    # Try CredentialManager first (highest priority)
    if CREDENTIALS_AVAILABLE:
        try:
            cred_manager = CredentialManager()
            credentials = cred_manager.load_credentials(profile)
            client_id = credentials.get("validation_runner_client_id")
            client_secret = credentials.get("validation_runner_client_secret")
            keycloak_url = credentials.get("keycloak_url")
            realm = credentials.get("keycloak_realm", "master")
        except (FileNotFoundError, ValueError):
            # Profile not found or no credentials file - fall back to environment variables
            pass
        except Exception as e:
            # Other errors (permissions, etc.) - log warning and fall back
            console.print(f"[dim]Note: Could not load credentials from profile '{profile}': {e}[/dim]")

    # Fallback to environment variables (backward compatibility)
    if not client_id or not client_secret:
        client_id = os.getenv("VALIDATION_RUNNER_CLIENT_ID") or os.getenv("GATEWAY_REGISTRY_CLIENT_ID")
        client_secret = os.getenv("VALIDATION_RUNNER_CLIENT_SECRET") or os.getenv("GATEWAY_REGISTRY_CLIENT_SECRET")
        keycloak_url = os.getenv("KEYCLOAK_URL", "http://keycloak:8180")
        realm = os.getenv("KEYCLOAK_REALM", "master")

    if not client_id or not client_secret:
        # No service credentials available - return None (anonymous access)
        return None

    # Get service token from Keycloak
    token_endpoint = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()
            token_data = response.json()
            return token_data.get("access_token")
    except Exception as e:
        # Authentication failed - return None
        console.print(f"[yellow]⚠️  Warning: Failed to get auth token: {e}[/yellow]")
        return None


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """
    Run async coroutine, handling both sync and async contexts.

    When called from a synchronous context (normal CLI usage), uses asyncio.run().
    When called from an async context (pytest-asyncio tests), runs in a thread pool
    to avoid "asyncio.run() cannot be called from a running event loop" errors.

    Args:
        coro: Async coroutine to execute

    Returns:
        Result of the coroutine execution
    """
    try:
        # Check if we're already in an async context
        asyncio.get_running_loop()
        # We're in an async context - run in a thread pool to avoid event loop conflicts
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)


@click.group(name="a2a")
def a2a_group():
    """Agent-to-Agent federation commands."""
    pass


@a2a_group.command("generate-token")
@click.option(
    "--gateway-alias",
    help="Alias for the gateway (e.g., 'university-a', 'lab-b')"
)
@click.option(
    "--keycloak-url",
    default=None,
    help="Keycloak server URL (defaults to KEYCLOAK_URL env var or http://keycloak:8180)"
)
@click.option(
    "--realm",
    default="master",
    help="Keycloak realm name"
)
@click.option(
    "--client-id",
    default=None,
    help="Gateway client ID (defaults to GATEWAY_CLIENT_ID env var or 'gateway-client')"
)
@click.option(
    "--client-secret",
    default=None,
    help="Gateway client secret (defaults to GATEWAY_CLIENT_SECRET env var)"
)
@click.option(
    "--output",
    type=click.Choice(["token", "json", "curl"]),
    default="token",
    help="Output format (token: raw JWT, json: full response, curl: example curl command)"
)
def generate_token(
    gateway_alias: Optional[str],
    keycloak_url: Optional[str],
    realm: str,
    client_id: Optional[str],
    client_secret: Optional[str],
    output: str
):
    """
    Generate A2A authentication token for federated task delegation.

    This command generates a JWT token that can be shared with peer institutions
    running ADEPT Agent Gateway. The token enables secure Agent-to-Agent (A2A)
    communication for federated task delegation across different ADEPT instances.

    Usage Examples:

      # Generate token for University A's gateway
      agentic a2a generate-token --gateway-alias university-a

      # Generate token with custom Keycloak URL
      agentic a2a generate-token --keycloak-url http://keycloak.example.com:8180

      # Output as curl command example
      agentic a2a generate-token --gateway-alias lab-b --output curl

      # Output full JSON response
      agentic a2a generate-token --output json

    Manual Trust Establishment Workflow:

      1. Admin at Institution A generates token:
         $ agentic a2a generate-token --gateway-alias institution-a > token_a.txt

      2. Admin at Institution A shares token_a.txt with Institution B admin
         (via secure channel: encrypted email, shared vault, etc.)

      3. Admin at Institution B uses token to register Institution A's gateway:
         $ curl -H "Authorization: Bearer $(cat token_a.txt)" \\
                https://institution-b.edu/v1/gateway-registry/register \\
                -d '{"name": "institution-a", "url": "https://institution-a.edu"}'

      4. Repeat process in reverse for bidirectional trust

    Security Notes:

      - Tokens use OAuth2 Client Credentials flow (service-to-service authentication)
      - Tokens have "gateway-service" group for inter-gateway communication
      - Token expiration follows Keycloak configuration (typically 5 minutes)
      - Refresh tokens are NOT generated (use client credentials for new tokens)
      - Share tokens via secure channels only (encrypted communication)
    """
    run_async(_do_generate_token(
        gateway_alias, keycloak_url, realm, client_id, client_secret, output
    ))


async def _do_generate_token(
    gateway_alias: Optional[str],
    keycloak_url: Optional[str],
    realm: str,
    client_id: Optional[str],
    client_secret: Optional[str],
    output: str
):
    """Generate A2A token using OAuth2 Client Credentials flow."""

    # Resolve configuration from environment variables or defaults
    keycloak_url = keycloak_url or os.getenv("KEYCLOAK_URL", "http://keycloak:8180")
    client_id = client_id or os.getenv("GATEWAY_CLIENT_ID", "gateway-client")
    client_secret = client_secret or os.getenv("GATEWAY_CLIENT_SECRET")

    # Validate client secret
    if not client_secret:
        console.print("[red]❌ Gateway client secret not found[/red]")
        console.print()
        console.print("Please provide the secret via:")
        console.print("  1. Environment variable: [cyan]GATEWAY_CLIENT_SECRET[/cyan]")
        console.print("  2. Command line option: [cyan]--client-secret SECRET[/cyan]")
        console.print()
        console.print("To find the secret:")
        console.print("  [dim]# From credentials directory[/dim]")
        console.print("  [cyan]cat deployment/local/docker-compose/.env-keycloak-credentials-dir/GATEWAY_CLIENT_SECRET[/cyan]")
        console.print()
        console.print("  [dim]# From PostgreSQL (if running)[/dim]")
        console.print("  [cyan]docker exec postgres psql -U admin -d keycloak \\")
        console.print("    -c \"SELECT secret FROM client WHERE client_id = 'gateway-client';\"[/cyan]")
        sys.exit(1)

    # Show configuration panel
    config_table = Table.grid(padding=(0, 2))
    config_table.add_column(style="cyan", justify="right")
    config_table.add_column()

    config_table.add_row("Keycloak URL:", keycloak_url)
    config_table.add_row("Realm:", realm)
    config_table.add_row("Client ID:", client_id)
    config_table.add_row("Gateway Alias:", gateway_alias or "(not specified)")

    console.print(Panel.fit(
        config_table,
        title="🔐 A2A Token Generation",
        border_style="blue"
    ))
    console.print()

    # Request token using Client Credentials flow
    token_endpoint = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Generating A2A token...", total=None)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    token_endpoint,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )

                response.raise_for_status()
                token_data = response.json()

            progress.update(task, description="✅ Token generated successfully")
            progress.stop()

        except httpx.HTTPStatusError as e:
            console.print(f"[red]❌ Token generation failed: {e.response.status_code} {e.response.text}[/red]")
            console.print()
            console.print("Common issues:")
            console.print("  • Invalid client credentials (check GATEWAY_CLIENT_SECRET)")
            console.print("  • Keycloak server not accessible")
            console.print("  • Client not configured with 'Service Accounts Enabled'")
            sys.exit(1)
        except httpx.ConnectError as e:
            console.print(f"[red]❌ Cannot connect to Keycloak: {e}[/red]")
            console.print()
            console.print("Check that Keycloak is running:")
            console.print("  [cyan]docker ps | grep keycloak[/cyan]")
            console.print("  [cyan]curl -I {keycloak_url}[/cyan]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]❌ Unexpected error: {e}[/red]")
            sys.exit(1)

    # Extract token fields
    access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in", 0)
    token_type = token_data.get("token_type", "Bearer")

    # Calculate expiration time
    expires_at = datetime.now() + timedelta(seconds=expires_in)

    # Display based on output format
    if output == "token":
        # Raw token only (for piping to file)
        console.print(access_token)

    elif output == "json":
        # Full JSON response
        import json
        console.print(Syntax(
            json.dumps(token_data, indent=2),
            "json",
            theme="monokai",
            line_numbers=False
        ))

    elif output == "curl":
        # Example curl command
        console.print()
        console.print(Panel.fit(
            f"[bold green]Token Generated Successfully[/bold green]\n\n"
            f"[cyan]Token Type:[/cyan] {token_type}\n"
            f"[cyan]Expires In:[/cyan] {expires_in} seconds ({expires_in // 60} minutes)\n"
            f"[cyan]Expires At:[/cyan] {expires_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"[cyan]Gateway Alias:[/cyan] {gateway_alias or '(not specified)'}",
            title="🎉 Success",
            border_style="green"
        ))
        console.print()
        console.print("[bold]Example curl command:[/bold]")
        console.print()

        # Example A2A endpoint call
        example_gateway_url = "https://peer-institution.edu"
        curl_command = f"""curl -X POST {example_gateway_url}/v1/a2a \\
  -H "Authorization: Bearer {access_token[:20]}...{access_token[-20:]}" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "jsonrpc": "2.0",
    "method": "task.delegate",
    "params": {{
      "task": "Analyze protein sequence MKLLV...",
      "context": {{"experiment_id": "exp-123"}}
    }},
    "id": 1
  }}'"""

        console.print(Syntax(curl_command, "bash", theme="monokai", line_numbers=False))
        console.print()
        console.print("[dim]Note: Token is truncated in example. Use full token in actual requests.[/dim]")
        console.print()

    # Show usage instructions if not raw token output
    if output != "token":
        console.print()
        console.print("[bold blue]Next Steps:[/bold blue]")
        console.print()
        console.print("1. [bold]Save token to file:[/bold]")
        console.print(f"   [cyan]agentic a2a generate-token --gateway-alias {gateway_alias or 'my-gateway'} > a2a_token.txt[/cyan]")
        console.print()
        console.print("2. [bold]Share token with peer institution admin[/bold] (via secure channel)")
        console.print()
        console.print("3. [bold]Peer admin registers your gateway:[/bold]")
        curl_register_cmd = f"""curl -X POST https://peer.edu/v1/gateway-registry/register \\
     -H "Authorization: Bearer $(cat a2a_token.txt)" \\
     -H "Content-Type: application/json" \\
     -d '{{"name": "{gateway_alias or 'partner-gateway'}", "url": "https://your-gateway.edu"}}'"""
        console.print(f"   [cyan]{curl_register_cmd}[/cyan]")
        console.print()
        console.print("[yellow]⚠️  Security Note:[/yellow] Token expires in [bold]{} minutes[/bold]. ".format(expires_in // 60))
        console.print("   Generate new token if expired. Never share tokens via unsecured channels.")


@a2a_group.command("test-token")
@click.option(
    "--token",
    required=True,
    help="JWT token to test (or use '-' to read from stdin)"
)
@click.option(
    "--gateway-url",
    default="http://localhost:8083",
    help="Agent Gateway URL to test against"
)
def test_token(token: str, gateway_url: str):
    """
    Test an A2A token against Agent Gateway.

    Usage Examples:

      # Test token from file
      agentic a2a test-token --token "$(cat a2a_token.txt)"

      # Test token from stdin
      cat a2a_token.txt | agentic a2a test-token --token -

      # Test against external gateway
      agentic a2a test-token --token TOKEN --gateway-url https://partner.edu
    """
    run_async(_do_test_token(token, gateway_url))


async def _do_test_token(token: str, gateway_url: str):
    """Test A2A token by calling AgentCard endpoint."""

    # Handle stdin input
    if token == "-":
        import sys
        token = sys.stdin.read().strip()

    if not token:
        console.print("[red]❌ No token provided[/red]")
        sys.exit(1)

    console.print(Panel.fit(
        f"🔍 Testing A2A Token\n\n"
        f"[cyan]Gateway URL:[/cyan] {gateway_url}\n"
        f"[cyan]Token Length:[/cyan] {len(token)} characters",
        border_style="blue"
    ))
    console.print()

    # Test 1: AgentCard endpoint (public, no auth)
    agentcard_url = f"{gateway_url}/a2a/.well-known/agent-card.json"

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task1 = progress.add_task("Testing AgentCard discovery...", total=None)

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                response = await client.get(agentcard_url)

                if response.status_code == 200:
                    progress.update(task1, description="✅ AgentCard accessible")
                    agentcard = response.json()
                    console.print(f"[green]✓ AgentCard Discovery:[/green] {agentcard.get('name', 'Unknown Gateway')}")
                else:
                    progress.update(task1, description=f"❌ AgentCard error: {response.status_code}")
                    console.print(f"[red]✗ AgentCard Discovery Failed:[/red] {response.status_code}")

        except Exception as e:
            progress.update(task1, description=f"❌ AgentCard error: {e}")
            console.print(f"[red]✗ AgentCard Discovery Failed:[/red] {e}")

        # Test 2: A2A endpoint with token (requires auth)
        task2 = progress.add_task("Testing A2A endpoint with token...", total=None)
        a2a_url = f"{gateway_url}/a2a/"

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                response = await client.post(
                    a2a_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "jsonrpc": "2.0",
                        "method": "capabilities.list",
                        "params": {},
                        "id": 1
                    }
                )

                if response.status_code == 200:
                    progress.update(task2, description="✅ Token valid, A2A endpoint accessible")
                    console.print(f"[green]✓ Token Authentication:[/green] Valid")
                    console.print(f"[green]✓ A2A Endpoint:[/green] Accessible")
                elif response.status_code in [401, 403]:
                    progress.update(task2, description=f"❌ Token invalid: {response.status_code}")
                    console.print(f"[red]✗ Token Authentication:[/red] Failed ({response.status_code})")
                    console.print("[yellow]Token may be expired or lack required permissions[/yellow]")
                else:
                    progress.update(task2, description=f"⚠️  Unexpected response: {response.status_code}")
                    console.print(f"[yellow]⚠  Unexpected Response:[/yellow] {response.status_code}")

        except Exception as e:
            progress.update(task2, description=f"❌ A2A test error: {e}")
            console.print(f"[red]✗ A2A Endpoint Test Failed:[/red] {e}")

    console.print()
    console.print("[dim]Token testing complete[/dim]")


@a2a_group.command("list-peers")
@click.option(
    "--registry-url",
    default=lambda: os.getenv("GATEWAY_REGISTRY_URL", "http://localhost:8086"),
    help="Gateway Registry URL"
)
@click.option(
    "--format",
    type=click.Choice(["table", "json", "simple"]),
    default="table",
    help="Output format"
)
@click.option(
    "--profile",
    default="default",
    help="Credential profile to use (default: 'default')"
)
def list_peers(registry_url: str, format: str, profile: str):
    """
    List all registered gateway peers in the mesh.

    Example:
        agentic a2a list-peers
        agentic a2a list-peers --format json
        agentic a2a list-peers --profile production
        agentic a2a list-peers --registry-url http://registry.example.com:8086
    """
    run_async(_do_list_peers(registry_url, format, profile))


async def _do_list_peers(registry_url: str, format: str, profile: str):
    """List all registered gateway peers."""

    # Get authentication token
    auth_token = await _get_registry_auth_token(profile)
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            response = await client.get(
                f"{registry_url}/v1/gateways/",
                headers=headers,
            )
            response.raise_for_status()
            gateways = response.json()

            if not gateways:
                console.print("[yellow]No gateway peers registered.[/yellow]")
                return

            if format == "json":
                import json
                console.print(json.dumps(gateways, indent=2))
            elif format == "simple":
                for gw in gateways:
                    # Use public_url from Gateway Registry schema
                    console.print(f"{gw['alias']}: {gw.get('public_url', gw.get('base_url', 'N/A'))}")
            else:  # table
                table = Table(title="Registered Gateway Peers")
                table.add_column("Alias", style="cyan")
                table.add_column("Public URL", style="green")
                table.add_column("Capabilities", style="dim")
                table.add_column("Health Status", style="yellow")

                for gw in gateways:
                    # Extract description/tags from capabilities if stored there
                    capabilities = gw.get("capabilities", [])
                    caps_str = ", ".join(capabilities) if capabilities else "N/A"

                    table.add_row(
                        gw.get("alias", ""),
                        gw.get("public_url", gw.get("base_url", "")),  # Support both field names
                        caps_str,
                        gw.get("health_status", "Unknown")
                    )

                console.print(table)

    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP Error: {e.response.status_code}[/red]")
        if e.response.status_code == 404:
            console.print("[yellow]Gateway Registry not found. Is the service running?[/yellow]")
        sys.exit(1)
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to Gateway Registry at {registry_url}[/red]")
        console.print("[yellow]Check that the registry service is running:[/yellow]")
        console.print("  docker ps | grep gateway_registry")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@a2a_group.command("register-peer")
@click.argument("alias")
@click.argument("base_url")
@click.option(
    "--description",
    default="",
    help="Optional description of the gateway"
)
@click.option(
    "--tags",
    default="",
    help="Comma-separated tags (e.g., 'production,us-west-2')"
)
@click.option(
    "--registry-url",
    default=lambda: os.getenv("GATEWAY_REGISTRY_URL", "http://localhost:8086"),
    help="Gateway Registry URL"
)
@click.option(
    "--profile",
    default="default",
    help="Credential profile to use (default: 'default')"
)
def register_peer(alias: str, base_url: str, description: str, tags: str, registry_url: str, profile: str):
    """
    Register a remote gateway peer in the mesh.

    Example:
        agentic a2a register-peer lab-west https://lab-west.example.com/a2a
        agentic a2a register-peer lab-west https://lab-west.example.com/a2a \\
          --description "West Coast Lab" --tags "production,us-west-2"
        agentic a2a register-peer lab-west https://lab-west.example.com/a2a --profile production
    """
    run_async(_do_register_peer(alias, base_url, description, tags, registry_url, profile))


async def _do_register_peer(alias: str, base_url: str, description: str, tags: str, registry_url: str, profile: str):
    """Register a remote gateway peer."""

    # Build capabilities list from description and tags
    capabilities = []
    tag_list = []  # Initialize tag_list to avoid UnboundLocalError

    if description:
        capabilities.append(f"description:{description}")
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        capabilities.extend([f"tag:{t}" for t in tag_list])

    # Use correct Gateway Registry schema (public_url, not base_url)
    payload = {
        "alias": alias,
        "public_url": base_url,  # Gateway Registry expects 'public_url'
        "capabilities": capabilities if capabilities else [],
    }

    # Get authentication token
    auth_token = await _get_registry_auth_token(profile)
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            response = await client.post(
                f"{registry_url}/v1/gateways",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

        # Display success message
        console.print(f"[green]✓[/green] Peer gateway '{alias}' registered successfully")
        console.print(f"[cyan]Base URL:[/cyan] {base_url}")
        if description:
            console.print(f"[cyan]Description:[/cyan] {description}")
        if tag_list:  # Now safe to check tag_list
            console.print(f"[cyan]Tags:[/cyan] {', '.join(tag_list)}")

        # Suggest next steps
        console.print("\n[yellow]Next steps:[/yellow]")
        console.print("  1. Generate A2A token: [cyan]agentic a2a generate-token[/cyan]")
        console.print(f"  2. Test connection: [cyan]agentic a2a test-connection {alias}[/cyan]")

    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP Error: {e.response.status_code}[/red]")
        if e.response.status_code == 400:
            try:
                error_detail = e.response.json()
                console.print(f"[yellow]Details: {error_detail.get('detail', 'Invalid request')}[/yellow]")
            except:
                console.print(f"[yellow]Details: {e.response.text[:200]}[/yellow]")
        sys.exit(1)
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to Gateway Registry at {registry_url}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def _parse_capabilities(caps_list):
    """
    Parse a capabilities list into structured description + tags.

    Input: ["description:Azure VM", "tag:azure", "tag:westus"]
    Output: {"description": "Azure VM", "tags": {"azure", "westus"}}
    """
    result = {"description": "", "tags": set()}
    for cap in (caps_list or []):
        if cap.startswith("description:"):
            result["description"] = cap[len("description:"):]
        elif cap.startswith("tag:"):
            result["tags"].add(cap[len("tag:"):])
    return result


def _build_capabilities(parsed):
    """
    Build a capabilities list from structured description + tags.

    Input: {"description": "Azure VM", "tags": {"azure", "westus"}}
    Output: ["description:Azure VM", "tag:azure", "tag:westus"]
    """
    caps = []
    if parsed.get("description"):
        caps.append(f"description:{parsed['description']}")
    for tag in sorted(parsed.get("tags", set())):
        caps.append(f"tag:{tag}")
    return caps


@a2a_group.command("update-peer")
@click.argument("alias")
@click.option(
    "--add-tags",
    default="",
    help="Comma-separated tags to add (e.g., 'Opentrons,lab-automation')"
)
@click.option(
    "--remove-tags",
    default="",
    help="Comma-separated tags to remove"
)
@click.option(
    "--description",
    default=None,
    help="Replace description (if provided)"
)
@click.option(
    "--public-url",
    default=None,
    help="Replace public URL (if provided)"
)
@click.option(
    "--registry-url",
    default=lambda: os.getenv("GATEWAY_REGISTRY_URL", "http://localhost:8086"),
    help="Gateway Registry URL"
)
@click.option(
    "--profile",
    default="default",
    help="Credential profile to use (default: 'default')"
)
def update_peer(alias: str, add_tags: str, remove_tags: str, description: Optional[str], public_url: Optional[str], registry_url: str, profile: str):
    """
    Update a registered gateway peer's capabilities or metadata.

    Fetches the current registration, merges changes, and upserts back.
    Tags are merged (not replaced) so existing tags are preserved.

    Example:
        agentic a2a update-peer azure-gateway --add-tags "Opentrons"
        agentic a2a update-peer azure-gateway --remove-tags "old-tag"
        agentic a2a update-peer azure-gateway --description "New description"
        agentic a2a update-peer azure-gateway --add-tags "Opentrons" --description "Updated"
    """
    run_async(_do_update_peer(alias, add_tags, remove_tags, description, public_url, registry_url, profile))


async def _do_update_peer(alias: str, add_tags: str, remove_tags: str, description: Optional[str], public_url: Optional[str], registry_url: str, profile: str):
    """Update a registered gateway peer (fetch-merge-upsert)."""

    # Get authentication token
    auth_token = await _get_registry_auth_token(profile)
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}

    # Step 1: Fetch current registration
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            response = await client.get(
                f"{registry_url}/v1/gateways/{alias}",
                headers=headers,
            )
            if response.status_code == 404:
                console.print(f"[red]Peer '{alias}' not found in registry[/red]")
                sys.exit(1)
            response.raise_for_status()
            current = response.json()
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to Gateway Registry at {registry_url}[/red]")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print(f"[red]Peer '{alias}' not found in registry[/red]")
        else:
            console.print(f"[red]HTTP Error: {e.response.status_code}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error fetching peer: {e}[/red]")
        sys.exit(1)

    # Step 2: Parse existing capabilities
    parsed_before = _parse_capabilities(current.get("capabilities", []))
    parsed = _parse_capabilities(current.get("capabilities", []))

    # Step 3: Apply changes
    if add_tags:
        for tag in [t.strip() for t in add_tags.split(",") if t.strip()]:
            parsed["tags"].add(tag)
    if remove_tags:
        for tag in [t.strip() for t in remove_tags.split(",") if t.strip()]:
            parsed["tags"].discard(tag)
    if description is not None:
        parsed["description"] = description

    new_public_url = public_url if public_url is not None else current.get("public_url", "")

    # Step 4: Build merged payload and upsert
    payload = {
        "alias": alias,
        "public_url": new_public_url,
        "capabilities": _build_capabilities(parsed),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            response = await client.post(
                f"{registry_url}/v1/gateways",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP Error updating peer: {e.response.status_code}[/red]")
        try:
            error_detail = e.response.json()
            console.print(f"[yellow]Details: {error_detail.get('detail', 'Unknown')}[/yellow]")
        except Exception:
            console.print(f"[yellow]Details: {e.response.text[:200]}[/yellow]")
        sys.exit(1)
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to Gateway Registry at {registry_url}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error updating peer: {e}[/red]")
        sys.exit(1)

    # Step 5: Display before/after diff
    caps_after = _build_capabilities(parsed)
    caps_before = _build_capabilities(parsed_before)

    console.print(f"[green]✓[/green] Peer '{alias}' updated successfully")
    console.print()
    console.print(f"[cyan]Public URL:[/cyan] {new_public_url}")
    console.print(f"[cyan]Before:[/cyan] {', '.join(caps_before) if caps_before else '(none)'}")
    console.print(f"[cyan]After:[/cyan]  {', '.join(caps_after) if caps_after else '(none)'}")


@a2a_group.command("test-connection")
@click.argument("alias")
@click.option(
    "--registry-url",
    default=lambda: os.getenv("GATEWAY_REGISTRY_URL", "http://localhost:8086"),
    help="Gateway Registry URL"
)
@click.option(
    "--timeout",
    default=10.0,
    help="Connection timeout in seconds"
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed connection information"
)
@click.option(
    "--profile",
    default="default",
    help="Credential profile to use (default: 'default')"
)
def test_connection(alias: str, registry_url: str, timeout: float, verbose: bool, profile: str):
    """
    Test connectivity to a registered peer gateway.

    Example:
        agentic a2a test-connection lab-west
        agentic a2a test-connection lab-west --verbose
        agentic a2a test-connection lab-west --profile production
    """
    run_async(_do_test_connection(alias, registry_url, timeout, verbose, profile))


async def _do_test_connection(alias: str, registry_url: str, timeout: float, verbose: bool, profile: str):
    """Test connectivity to a peer gateway."""
    import time

    # Get authentication token
    auth_token = await _get_registry_auth_token(profile)
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}

    try:
        # Get gateway details from registry
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.get(
                f"{registry_url}/v1/gateways/{alias}",
                headers=headers,
            )
            response.raise_for_status()
            gateway = response.json()

        peer_url = gateway.get("public_url", gateway.get("base_url", ""))

        if verbose:
            console.print(f"[cyan]Gateway Alias:[/cyan] {alias}")
            console.print(f"[cyan]Public URL:[/cyan] {peer_url}")
            console.print(f"[cyan]Description:[/cyan] {gateway.get('description', '(none)')}")
            console.print()

        # Test HTTP connectivity to health endpoint
        console.print(f"Testing connection to {peer_url}...")
        start_time = time.time()

        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            try:
                # Try /health endpoint first
                response = await client.get(f"{peer_url.rstrip('/v1')}/health")
                response.raise_for_status()
                health_data = response.json()
                status = health_data.get("status", "unknown")
            except:
                # Fallback to base URL
                response = await client.get(peer_url)
                status = "accessible" if response.status_code == 200 else "unknown"

        latency = (time.time() - start_time) * 1000  # ms

        # Display results
        color = "green" if status in ["healthy", "accessible"] else "yellow"
        console.print(f"[{color}]●[/{color}] Connection Status: {status}")
        console.print(f"[cyan]Latency:[/cyan] {latency:.0f}ms")

        if latency > 1000:
            console.print("[yellow]⚠ High latency detected (>1s)[/yellow]")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print(f"[red]✗[/red] Gateway '{alias}' not found in registry")
        else:
            console.print(f"[red]✗[/red] Connection failed: HTTP {e.response.status_code}")
        sys.exit(1)
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Cannot connect to {peer_url}")
        console.print("[yellow]The peer gateway may be offline or unreachable[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Connection error: {e}")
        sys.exit(1)


@a2a_group.command("remove-peer")
@click.argument("alias")
@click.option(
    "--registry-url",
    default=lambda: os.getenv("GATEWAY_REGISTRY_URL", "http://localhost:8086"),
    help="Gateway Registry URL"
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt"
)
@click.option(
    "--profile",
    default="default",
    help="Credential profile to use (default: 'default')"
)
def remove_peer(alias: str, registry_url: str, yes: bool, profile: str):
    """
    Remove a gateway peer from the mesh.

    Example:
        agentic a2a remove-peer lab-west
        agentic a2a remove-peer lab-west --yes
        agentic a2a remove-peer lab-west --profile production
    """
    run_async(_do_remove_peer(alias, registry_url, yes, profile))


async def _do_remove_peer(alias: str, registry_url: str, yes: bool, profile: str):
    """Remove a gateway peer from the registry."""
    from rich.prompt import Confirm

    # Confirmation prompt
    if not yes:
        confirm = Confirm.ask(
            f"[yellow]Remove peer '{alias}' from the registry?[/yellow]",
            default=False
        )
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            return

    # Get authentication token
    auth_token = await _get_registry_auth_token(profile)
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            response = await client.delete(
                f"{registry_url}/v1/gateways/{alias}",
                headers=headers,
            )
            response.raise_for_status()

        console.print(f"[green]✓[/green] Peer '{alias}' removed successfully")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print(f"[yellow]Peer '{alias}' not found in registry[/yellow]")
        else:
            console.print(f"[red]HTTP Error: {e.response.status_code}[/red]")
        sys.exit(1)
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to Gateway Registry at {registry_url}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


# Export for CLI integration
__all__ = ['a2a_group']
