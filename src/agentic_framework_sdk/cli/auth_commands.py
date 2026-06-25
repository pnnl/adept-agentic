"""
CLI authentication commands for Agentic Framework.

Provides login, logout, and token management commands.
"""

import asyncio
import os
import sys
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

try:
    from ..auth import KeycloakAuth, TokenStorage, DeviceFlowAuth, AuthenticationError, KeycloakConnectionError
    from ..auth.credential_manager import CredentialManager
    AUTH_AVAILABLE = True
except ImportError:
    try:
        # Fallback for direct script execution
        from agentic_framework_sdk.auth import KeycloakAuth, TokenStorage, DeviceFlowAuth, AuthenticationError, KeycloakConnectionError
        from agentic_framework_sdk.auth.credential_manager import CredentialManager
        AUTH_AVAILABLE = True
    except ImportError:
        AUTH_AVAILABLE = False
        KeycloakAuth = None
        TokenStorage = None
        DeviceFlowAuth = None
        CredentialManager = None

console = Console()


@click.group(name="auth")
def auth_group():
    """Authentication management commands."""
    if not AUTH_AVAILABLE:
        console.print("[red]❌ Authentication module not available. Please install required dependencies.[/red]")
        sys.exit(1)


@auth_group.command()
@click.option(
    "--external", 
    is_flag=True, 
    help="Use external NGINX proxy endpoint (https://api.agentic.local/auth)"
)
@click.option(
    "--device-flow",
    is_flag=True,
    help="Use OAuth2 device flow (PIN-based authentication)"
)
@click.option(
    "--username", 
    help="Username for authentication (will prompt if not provided)"
)
@click.option(
    "--keycloak-url",
    default="http://keycloak:8180",
    help="Keycloak server URL (for internal access)"
)
@click.option(
    "--realm",
    default="master", 
    help="Keycloak realm name"
)
@click.option(
    "--client-id",
    default="login-client",
    help="OAuth2 client ID"
)
def login(external: bool, device_flow: bool, username: Optional[str], keycloak_url: str, realm: str, client_id: str):
    """
    Login to Agentic Framework.
    
    Authentication Methods:
    - Password-based: Direct username/password authentication (default)
    - Device Flow: OAuth2 device flow with PIN-based authentication (--device-flow)
    
    Access Methods:  
    - Internal: Direct connection to Keycloak server (for Docker environments)
    - External: Via NGINX proxy with TLS (for external clients, --external)
    """
    asyncio.run(_do_login(external, device_flow, username, keycloak_url, realm, client_id))


@auth_group.command()
def logout():
    """Clear stored authentication tokens."""
    token_storage = TokenStorage()
    
    if token_storage.is_token_valid():
        if Confirm.ask("Clear stored authentication tokens?", default=True):
            token_storage.delete_token()
            console.print("✅ [green]Successfully logged out[/green]")
        else:
            console.print("Login tokens preserved")
    else:
        console.print("ℹ️  No stored tokens found")


@auth_group.command()
def status():
    """Show authentication status."""
    token_storage = TokenStorage()
    
    console.print(Panel.fit("🔐 Authentication Status", style="bold blue"))
    
    if token_storage.is_token_valid():
        try:
            token_info = token_storage.get_token()
            console.print("✅ [green]Authenticated[/green]")
            
            # Show token info (without sensitive data)
            if "stored_at" in token_info and "expires_in" in token_info:
                import time
                from datetime import datetime, timedelta
                
                stored_at = datetime.fromtimestamp(token_info["stored_at"])
                expires_in = token_info["expires_in"]
                expires_at = stored_at + timedelta(seconds=expires_in)
                
                console.print(f"📅 Token stored: {stored_at.strftime('%Y-%m-%d %H:%M:%S')}")
                console.print(f"⏰ Token expires: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
                
                if expires_at < datetime.now():
                    console.print("[yellow]⚠️  Token has expired[/yellow]")
            else:
                console.print("📋 Token information available")
                
        except Exception as e:
            console.print(f"⚠️  [yellow]Token found but may be invalid: {e}[/yellow]")
    else:
        console.print("❌ [red]Not authenticated[/red]")
        console.print("\nTo login, run:")
        console.print("  [cyan]agentic auth login[/cyan]                  # Internal access")
        console.print("  [cyan]agentic auth login --external[/cyan]       # External access via NGINX proxy")


@auth_group.command()
@click.option(
    "--external", 
    is_flag=True, 
    help="Test external NGINX proxy endpoint"
)
@click.option(
    "--keycloak-url",
    default="http://keycloak:8180",
    help="Keycloak server URL"
)
def test(external: bool, keycloak_url: str):
    """Test connection to authentication server."""
    asyncio.run(_do_test_connection(external, keycloak_url))


async def _do_login(
    external: bool,
    device_flow: bool,
    username: Optional[str], 
    keycloak_url: str, 
    realm: str, 
    client_id: str
):
    """Perform the actual login flow."""
    # Determine external proxy URL if using external access
    external_proxy_url = "https://api.agentic.local/auth" if external else None
    
    # Create auth client
    auth = KeycloakAuth(
        keycloak_url=keycloak_url,
        realm=realm,
        client_id=client_id,
        external_proxy_url=external_proxy_url
    )
    
    console.print(Panel.fit(
        "🔐 Agentic Framework Authentication", 
        style="bold blue"
    ))
    
    # Show connection method
    if external:
        console.print("🌐 Using external NGINX proxy endpoint")
        console.print(f"📡 Endpoint: https://api.agentic.local/auth")
    else:
        console.print("🔒 Using internal Keycloak endpoint") 
        console.print(f"📡 Endpoint: {keycloak_url}")
    
    console.print()
    
    # Test connection first
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Testing connection to authentication server...", total=None)
        
        try:
            can_connect = await auth.test_connection(use_external_proxy=external)
            if not can_connect:
                console.print(f"❌ [red]Cannot connect to authentication server[/red]")
                if external:
                    console.print("💡 Try without --external flag for internal access")
                else:
                    console.print("💡 Try with --external flag for external access via NGINX proxy")
                return
                
            progress.update(task, description="✅ Connection successful")
            progress.stop()
            
        except Exception as e:
            console.print(f"❌ [red]Connection failed: {e}[/red]")
            return
    
    console.print("✅ [green]Connected to authentication server[/green]")
    console.print()
    
    # Check if device flow is requested
    if device_flow:
        await _do_device_flow_login(external, keycloak_url, realm, client_id)
        return
    
    # Get credentials from user
    if not username:
        username = Prompt.ask("👤 Username")
    
    from getpass import getpass
    password = getpass("🔑 Password: ")
    
    if not username or not password:
        console.print("❌ [red]Username and password required[/red]")
        return
    
    # Perform authentication
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Authenticating...", total=None)
        
        try:
            token_info = await auth.authenticate_password(
                username=username,
                password=password,
                use_external_proxy=external
            )
            
            # Store the token
            auth.token_storage.store_token(token_info, "default")
            
            progress.update(task, description="✅ Authentication successful")
            progress.stop()
            
        except AuthenticationError as e:
            console.print(f"❌ [red]Authentication failed: {e}[/red]")
            return
        except Exception as e:
            console.print(f"❌ [red]Unexpected error: {e}[/red]")
            return
    
    console.print("🎉 [green]Successfully logged in![/green]")
    console.print()
    console.print("You can now use:")
    console.print("  [cyan]agentic chat[/cyan]                    # Start research chat")
    console.print("  [cyan]agentic auth status[/cyan]             # Check auth status") 
    console.print("  [cyan]agentic auth logout[/cyan]             # Logout")


async def _do_device_flow_login(external: bool, keycloak_url: str, realm: str, client_id: str):
    """Perform OAuth2 device flow authentication."""
    external_proxy_url = "https://api.agentic.local/auth" if external else None
    
    # Create device flow auth client
    device_auth = DeviceFlowAuth(
        keycloak_url=keycloak_url,
        realm=realm,
        client_id=client_id,
        external_proxy_url=external_proxy_url
    )
    
    console.print(Panel.fit(
        "📱 OAuth2 Device Flow Authentication", 
        style="bold green"
    ))
    
    # Show authentication method
    if external:
        console.print("🌐 Using external NGINX proxy endpoint")
        console.print(f"📡 Endpoint: https://api.agentic.local/auth")
    else:
        console.print("🔒 Using internal Keycloak endpoint")
        console.print(f"📡 Endpoint: {keycloak_url}")
    
    console.print()
    
    # Test device flow support first
    console.print("🔍 Testing device flow support...")
    device_flow_supported = await device_auth.test_device_flow_support(use_external_proxy=external)
    
    if not device_flow_supported:
        console.print("❌ [red]Device flow is not supported by the authentication server[/red]")
        console.print("💡 Try using password authentication without --device-flow flag")
        console.print("💡 Or ensure Keycloak client supports device authorization grant")
        return
    
    console.print("✅ [green]Device flow is supported[/green]")
    console.print()
    
    def progress_callback(message: str):
        """Handle progress updates from device flow."""
        console.print(message)
    
    try:
        # Perform device flow authentication
        token_info = await device_auth.authenticate_device_flow(
            use_external_proxy=external,
            progress_callback=progress_callback
        )
        
        console.print()
        console.print("🎉 [green]Device flow authentication successful![/green]")
        console.print()
        console.print("You can now use:")
        console.print("  [cyan]agentic chat[/cyan]                    # Start research chat")
        console.print("  [cyan]agentic auth status[/cyan]             # Check auth status") 
        console.print("  [cyan]agentic auth logout[/cyan]             # Logout")
        
    except AuthenticationError as e:
        console.print(f"❌ [red]Device flow authentication failed: {e}[/red]")
        console.print()
        console.print("💡 Try using password authentication without --device-flow flag")
        console.print("💡 Or check if the authorization was completed correctly")
    except Exception as e:
        console.print(f"❌ [red]Unexpected error during device flow: {e}[/red]")


async def _do_test_connection(external: bool, keycloak_url: str):
    """Test connection to authentication server."""
    external_proxy_url = "https://api.agentic.local/auth" if external else None

    auth = KeycloakAuth(
        keycloak_url=keycloak_url,
        external_proxy_url=external_proxy_url
    )

    endpoint_type = "External NGINX proxy" if external else "Internal Keycloak"
    endpoint_url = "https://api.agentic.local/auth" if external else keycloak_url

    console.print(f"🔍 Testing {endpoint_type} connection...")
    console.print(f"📡 Endpoint: {endpoint_url}")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Connecting...", total=None)

        try:
            can_connect = await auth.test_connection(use_external_proxy=external)

            if can_connect:
                progress.update(task, description="✅ Connection successful")
                progress.stop()
                console.print(f"✅ [green]{endpoint_type} is accessible[/green]")

                if external:
                    console.print("🌐 External clients can authenticate via NGINX proxy")
                else:
                    console.print("🔒 Internal clients can authenticate via direct Keycloak access")
            else:
                progress.update(task, description="❌ Connection failed")
                progress.stop()
                console.print(f"❌ [red]{endpoint_type} is not accessible[/red]")

                if external:
                    console.print("💡 NGINX proxy may not be running or configured properly")
                    console.print("💡 Try: [cyan]agentic auth test[/cyan] (without --external)")
                else:
                    console.print("💡 Keycloak server may not be running")
                    console.print("💡 Try: [cyan]agentic auth test --external[/cyan]")

        except Exception as e:
            console.print(f"❌ [red]Connection test failed: {e}[/red]")


# ==============================================================================
# CREDENTIAL MANAGEMENT COMMANDS (A2A Service Authentication)
# ==============================================================================

@auth_group.command("cred-setup")
@click.option("--profile", default="default", help="Profile name (default: 'default')")
@click.option("--auto-discover", is_flag=True, help="Auto-discover credentials from ADEPT installation")
@click.option("--client-id", help="Validation runner client ID")
@click.option("--client-secret", help="Validation runner client secret")
@click.option("--keycloak-url", help="Keycloak server URL")
@click.option("--keycloak-realm", default="master", help="Keycloak realm (default: 'master')")
@click.option("--registry-url", help="Gateway registry URL")
@click.option("--force", is_flag=True, help="Overwrite existing profile without confirmation")
def cred_setup(
    profile: str,
    auto_discover: bool,
    client_id: Optional[str],
    client_secret: Optional[str],
    keycloak_url: Optional[str],
    keycloak_realm: str,
    registry_url: Optional[str],
    force: bool,
):
    """
    Setup service credentials for A2A operations.

    Configures service-to-service authentication credentials for A2A
    (Agent-to-Agent) operations. Credentials are stored securely in
    ~/.adept-agentic/credentials with chmod 600.

    \b
    Examples:
        # Auto-discover from ADEPT installation (recommended)
        agentic auth cred-setup --auto-discover

        # Manual setup
        agentic auth cred-setup --client-id validation-runner-client --client-secret SECRET

        # Setup production profile
        agentic auth cred-setup --profile production \\
            --keycloak-url https://keycloak.prod.example.com

        # Interactive mode (prompts for all values)
        agentic auth cred-setup
    """
    cred_manager = CredentialManager()

    console.print(Panel.fit(
        f"🔐 Setting up A2A credentials for profile: [cyan]{profile}[/cyan]",
        border_style="blue"
    ))
    console.print()

    # Check if profile already exists
    if cred_manager.profile_exists(profile):
        if not force:
            console.print(f"[yellow]⚠️  Profile '{profile}' already exists[/yellow]")
            if not Confirm.ask("Overwrite existing profile?"):
                console.print("Cancelled")
                return
        else:
            console.print(f"[yellow]⚠️  Profile '{profile}' already exists - overwriting (--force)[/yellow]")
            console.print()

    # Auto-discovery mode
    if auto_discover:
        console.print("🔍 Auto-discovering credentials from ADEPT installation...")
        discovered = cred_manager._discover_adept_credentials()

        if discovered:
            console.print("[green]✅ Found credentials in ADEPT installation[/green]")
            console.print()

            # Show discovered values
            table = Table(show_header=False, box=None)
            table.add_column(style="cyan", justify="right")
            table.add_column()

            table.add_row("Client ID:", discovered.get("validation_runner_client_id", "N/A"))
            secret = discovered.get("validation_runner_client_secret", "N/A")
            table.add_row("Client Secret:", f"{secret[:10]}..." if len(secret) > 10 else secret)
            table.add_row("Keycloak URL:", discovered.get("keycloak_url", "N/A"))
            table.add_row("Realm:", discovered.get("keycloak_realm", "N/A"))
            table.add_row("Registry URL:", discovered.get("gateway_registry_url", "N/A"))

            console.print(table)
            console.print()

            # Auto-confirm if force flag is set, otherwise ask
            use_credentials = force or Confirm.ask("Use these credentials?")
            if use_credentials:
                cred_manager.save_credentials(
                    profile=profile,
                    client_id=discovered["validation_runner_client_id"],
                    client_secret=discovered["validation_runner_client_secret"],
                    keycloak_url=discovered["keycloak_url"],
                    keycloak_realm=discovered.get("keycloak_realm", "master"),
                    gateway_registry_url=discovered.get("gateway_registry_url"),
                )
                console.print()
                console.print(f"[green]✅ Credentials saved to [cyan]~/.adept-agentic/credentials[/cyan] (profile: {profile})[/green]")
                console.print()
                console.print("Test your credentials:")
                console.print(f"  [cyan]agentic auth cred-test --profile {profile}[/cyan]")
                return
        else:
            console.print("[yellow]⚠️  No ADEPT installation found. Using manual setup.[/yellow]")
            console.print()

    # Manual/interactive mode
    if not client_id:
        client_id = Prompt.ask("Client ID", default="validation-runner-client")

    if not client_secret:
        client_secret = Prompt.ask("Client Secret", password=True)

    if not keycloak_url:
        keycloak_url = Prompt.ask(
            "Keycloak URL",
            default="http://keycloak:8180",
        )

    if not registry_url:
        registry_url = Prompt.ask(
            "Gateway Registry URL",
            default="http://gateway_registry:8086",
        )

    # Validate required fields
    if not client_id or not client_secret or not keycloak_url:
        console.print("[red]❌ Error: client_id, client_secret, and keycloak_url are required[/red]")
        sys.exit(1)

    # Save credentials
    try:
        cred_manager.save_credentials(
            profile=profile,
            client_id=client_id,
            client_secret=client_secret,
            keycloak_url=keycloak_url,
            keycloak_realm=keycloak_realm,
            gateway_registry_url=registry_url,
        )

        console.print()
        console.print(f"[green]✅ Credentials saved to [cyan]~/.adept-agentic/credentials[/cyan] (profile: {profile})[/green]")
        console.print()
        console.print("Test your credentials:")
        console.print(f"  [cyan]agentic auth cred-test --profile {profile}[/cyan]")
        console.print()
        console.print("Use in A2A commands:")
        console.print(f"  [cyan]agentic a2a list-peers --profile {profile}[/cyan]")

    except Exception as e:
        console.print(f"[red]❌ Failed to save credentials: {e}[/red]")
        sys.exit(1)


@auth_group.command("cred-list")
def cred_list():
    """
    List all configured credential profiles for A2A operations.

    Shows all service credential profiles stored in ~/.adept-agentic/credentials
    with their basic configuration (Keycloak URL and client ID).

    \b
    Examples:
        agentic auth cred-list
    """
    cred_manager = CredentialManager()
    profiles = cred_manager.list_profiles()

    if not profiles:
        console.print("[yellow]No profiles configured.[/yellow]")
        console.print()
        console.print("Run [cyan]agentic auth cred-setup --auto-discover[/cyan] to configure credentials")
        return

    console.print(Panel.fit("📋 A2A Credential Profiles", border_style="blue"))
    console.print()

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Profile", style="cyan")
    table.add_column("Keycloak URL")
    table.add_column("Client ID")
    table.add_column("Realm")

    # Load each profile and display
    for profile_name in profiles:
        try:
            creds = cred_manager.load_credentials(profile_name)
            table.add_row(
                profile_name,
                creds.get("keycloak_url", "N/A"),
                creds.get("validation_runner_client_id", "N/A"),
                creds.get("keycloak_realm", "master"),
            )
        except Exception as e:
            table.add_row(
                profile_name,
                "[red]Error loading[/red]",
                str(e)[:30],
                ""
            )

    console.print(table)
    console.print()
    console.print(f"Credentials file: [dim]~/.adept-agentic/credentials[/dim]")


@auth_group.command("cred-test")
@click.option("--profile", default="default", help="Profile to test (default: 'default')")
@click.option("--verbose", is_flag=True, help="Show detailed output")
def cred_test(profile: str, verbose: bool):
    """
    Test service credentials by attempting authentication.

    Validates that A2A service credentials work by performing actual
    authentication against Keycloak and checking token retrieval.

    \b
    Examples:
        agentic auth cred-test
        agentic auth cred-test --profile production
        agentic auth cred-test --profile dev --verbose
    """
    cred_manager = CredentialManager()

    console.print(Panel.fit(
        f"🔐 Testing A2A credentials for profile: [cyan]{profile}[/cyan]",
        border_style="blue"
    ))
    console.print()

    # Load credentials
    try:
        creds = cred_manager.load_credentials(profile)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/red]")
        console.print()
        console.print("Run [cyan]agentic auth cred-setup --auto-discover[/cyan] to configure credentials")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")
        console.print()
        available = cred_manager.list_profiles()
        if available:
            console.print(f"Available profiles: {', '.join(available)}")
        sys.exit(1)
    except PermissionError as e:
        console.print(f"[red]❌ {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]❌ Error loading credentials: {e}[/red]")
        sys.exit(1)

    # Show loaded credentials (if verbose)
    if verbose:
        console.print("📋 Loaded credentials:")
        console.print(f"  Client ID: [cyan]{creds['validation_runner_client_id']}[/cyan]")
        secret = creds['validation_runner_client_secret']
        console.print(f"  Client Secret: [cyan]{secret[:10]}...[/cyan]")
        console.print(f"  Keycloak URL: [cyan]{creds['keycloak_url']}[/cyan]")
        console.print(f"  Realm: [cyan]{creds.get('keycloak_realm', 'master')}[/cyan]")
        if 'gateway_registry_url' in creds:
            console.print(f"  Registry URL: [cyan]{creds['gateway_registry_url']}[/cyan]")
        console.print()

    # Test authentication
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Testing service authentication...", total=None)

        try:
            import httpx

            async def test_service_auth():
                token_endpoint = f"{creds['keycloak_url']}/realms/{creds.get('keycloak_realm', 'master')}/protocol/openid-connect/token"

                async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                    response = await client.post(
                        token_endpoint,
                        data={
                            "grant_type": "client_credentials",
                            "client_id": creds["validation_runner_client_id"],
                            "client_secret": creds["validation_runner_client_secret"],
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"}
                    )
                    response.raise_for_status()
                    return response.json()

            # Run async authentication
            token_data = asyncio.run(test_service_auth())
            progress.update(task, description="✅ Authentication successful")
            progress.stop()

            console.print("[green]✅ Service authentication successful![/green]")

            if verbose:
                console.print()
                access_token = token_data.get("access_token", "")
                console.print(f"  Token: [cyan]{access_token[:30]}...[/cyan]")
                console.print(f"  Token type: [cyan]{token_data.get('token_type', 'Bearer')}[/cyan]")
                console.print(f"  Expires in: [cyan]{token_data.get('expires_in', 0)} seconds[/cyan]")

            console.print()
            console.print("Ready to use A2A commands:")
            console.print(f"  [cyan]agentic a2a list-peers --profile {profile}[/cyan]")

        except httpx.HTTPStatusError as e:
            progress.stop()
            console.print(f"[red]❌ Authentication failed: {e.response.status_code}[/red]")
            if verbose:
                console.print(f"  Response: {e.response.text}")
            console.print()
            console.print("Common issues:")
            console.print("  • Invalid client secret (check credentials)")
            console.print("  • Keycloak server not accessible (check URL)")
            console.print("  • Client not configured with 'Service Accounts Enabled'")
            sys.exit(1)
        except httpx.ConnectError as e:
            progress.stop()
            console.print(f"[red]❌ Cannot connect to Keycloak: {creds['keycloak_url']}[/red]")
            if verbose:
                console.print(f"  Error: {e}")
            console.print()
            console.print("Check that Keycloak is running:")
            console.print("  [cyan]docker ps | grep keycloak[/cyan]")
            console.print(f"  [cyan]curl -I {creds['keycloak_url']}[/cyan]")
            sys.exit(1)
        except Exception as e:
            progress.stop()
            console.print(f"[red]❌ Unexpected error: {e}[/red]")
            if verbose:
                import traceback
                console.print()
                console.print("[dim]" + traceback.format_exc() + "[/dim]")
            sys.exit(1)


@auth_group.command("cred-show")
@click.option("--profile", default="default", help="Profile to show (default: 'default')")
@click.option("--show-secret", is_flag=True, help="Show client secret (use carefully)")
def cred_show(profile: str, show_secret: bool):
    """
    Show service credentials for a profile.

    Displays A2A service credential configuration for the specified profile.
    By default, the client secret is masked. Use --show-secret to reveal it.

    \b
    Examples:
        agentic auth cred-show
        agentic auth cred-show --profile production
        agentic auth cred-show --profile production --show-secret
    """
    cred_manager = CredentialManager()

    try:
        creds = cred_manager.load_credentials(profile)

        console.print(Panel.fit(
            f"A2A Credentials - Profile: [cyan]{profile}[/cyan]",
            border_style="blue"
        ))
        console.print()

        table = Table(show_header=False, box=None)
        table.add_column(style="cyan", justify="right")
        table.add_column()

        table.add_row("Client ID:", creds["validation_runner_client_id"])

        secret = creds["validation_runner_client_secret"]
        if show_secret:
            table.add_row("Client Secret:", secret)
        else:
            table.add_row("Client Secret:", f"{secret[:10]}... (use --show-secret to reveal)")

        table.add_row("Keycloak URL:", creds["keycloak_url"])
        table.add_row("Realm:", creds.get("keycloak_realm", "master"))

        if "gateway_registry_url" in creds:
            table.add_row("Registry URL:", creds["gateway_registry_url"])

        console.print(table)
        console.print()
        console.print(f"Credentials file: [dim]~/.adept-agentic/credentials[/dim]")

    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/red]")
        console.print()
        console.print("Run [cyan]agentic auth cred-setup --auto-discover[/cyan] to configure credentials")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")
        console.print()
        available = cred_manager.list_profiles()
        if available:
            console.print(f"Available profiles: {', '.join(available)}")
        sys.exit(1)
    except PermissionError as e:
        console.print(f"[red]❌ {e}[/red]")
        sys.exit(1)


@auth_group.command("cred-remove")
@click.argument("profile")
@click.option("--yes", is_flag=True, help="Skip confirmation")
def cred_remove(profile: str, yes: bool):
    """
    Remove an A2A credential profile.

    Deletes the specified service credential profile from
    ~/.adept-agentic/credentials. Requires confirmation unless --yes is used.

    \b
    Examples:
        agentic auth cred-remove staging
        agentic auth cred-remove production --yes
    """
    cred_manager = CredentialManager()

    # Check if profile exists
    if not cred_manager.profile_exists(profile):
        console.print(f"[yellow]⚠️  Profile '{profile}' not found[/yellow]")
        console.print()
        available = cred_manager.list_profiles()
        if available:
            console.print(f"Available profiles: {', '.join(available)}")
        else:
            console.print("No profiles configured")
        return

    # Confirm deletion
    if not yes:
        console.print(f"⚠️  This will permanently delete profile: [cyan]{profile}[/cyan]")
        console.print()
        if not Confirm.ask("Are you sure?"):
            console.print("Cancelled")
            return

    # Delete profile
    try:
        success = cred_manager.delete_profile(profile)
        if success:
            console.print(f"[green]✅ Profile '{profile}' removed[/green]")
        else:
            console.print(f"[yellow]⚠️  Profile '{profile}' not found[/yellow]")
    except Exception as e:
        console.print(f"[red]❌ Failed to remove profile: {e}[/red]")
        sys.exit(1)


@auth_group.command("cred-export")
@click.option("--profile", default="default", help="Profile to export (default: 'default')")
@click.option("--format", type=click.Choice(["env", "json"]), default="env", help="Export format")
def cred_export(profile: str, format: str):
    """
    Export A2A credentials as environment variables or JSON.

    Useful for setting environment variables in shell scripts or passing
    credentials to other tools.

    \b
    Examples:
        # Export as environment variables (for use in shell)
        agentic auth cred-export
        agentic auth cred-export --profile production

        # Export as JSON
        agentic auth cred-export --format json

        # Use in shell script
        eval $(agentic auth cred-export --profile dev)
    """
    cred_manager = CredentialManager()

    try:
        creds = cred_manager.load_credentials(profile)

        if format == "env":
            # Export as shell environment variables
            console.print(f"export VALIDATION_RUNNER_CLIENT_ID='{creds['validation_runner_client_id']}'")
            console.print(f"export VALIDATION_RUNNER_CLIENT_SECRET='{creds['validation_runner_client_secret']}'")
            console.print(f"export KEYCLOAK_URL='{creds['keycloak_url']}'")
            console.print(f"export KEYCLOAK_REALM='{creds.get('keycloak_realm', 'master')}'")
            if 'gateway_registry_url' in creds:
                console.print(f"export GATEWAY_REGISTRY_URL='{creds['gateway_registry_url']}'")

        elif format == "json":
            # Export as JSON
            import json
            console.print(json.dumps(creds, indent=2))

    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/red]", file=sys.stderr)
        console.print()
        console.print("Run [cyan]agentic auth cred-setup --auto-discover[/cyan] to configure", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]", file=sys.stderr)
        sys.exit(1)


# Export for CLI integration
__all__ = ['auth_group']