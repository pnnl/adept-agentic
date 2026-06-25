#!/usr/bin/env python3
"""
Service API Token Creation Utility

OVERVIEW:
This script generates service API tokens for bearer token authentication with ADEPT Agent Gateway.
Unlike user-based JWT tokens (Keycloak OAuth2 flow), service API tokens are:
- Long-lived (configurable TTL, default 90 days)
- Non-expiring during operation (no token refresh needed)
- Ideal for external services, scripts, and automation
- Simpler than user authentication (just API token + base URL)

MIGRATION STATUS (Session 49):
- **Phase 1 (Dual-Mode)**: Writes to BOTH file and Redis for zero-risk deployment
- **Phase 2 (Future)**: Will write to Redis-only after full migration

KEY FEATURES:
1. Service Token Generation - Create bearer tokens with custom prefixes
2. TTL Support - Configurable expiration (1 hour to 1 year)
3. Group Assignment - Assign service identity to Keycloak groups
4. Token Revocation - Deactivate expired or compromised tokens
5. List Tokens - View all active service tokens

SERVICE API TOKEN vs USER JWT TOKEN:
┌─────────────────────┬──────────────────────┬────────────────────────┐
│ Feature             │ Service API Token    │ User JWT Token         │
├─────────────────────┼──────────────────────┼────────────────────────┤
│ Authentication      │ Bearer sk-service-*  │ Keycloak OAuth2 flow   │
│ Lifespan            │ 90 days (default)    │ 8 hours (access token) │
│ Refresh Required    │ No                   │ Yes (refresh token)    │
│ Use Case            │ Services, automation │ End-user interactive   │
│ Identity            │ Service username     │ Actual user (sub)      │
│ Complexity          │ Low (just API key)   │ High (OIDC flow)       │
└─────────────────────┴──────────────────────┴────────────────────────┘

COMMON USE CASES:
- External services calling ADEPT API (n8n, OpenWebUI)
- CI/CD pipelines and automation scripts
- Long-running background processes
- Non-interactive API access
- Testing and validation runners

COMPARISON TO STREAMLIT CHAT.PY:
Streamlit Chat.py uses user JWT tokens from Keycloak login:
  1. User enters username/password in Streamlit UI
  2. get_user_token() calls Keycloak OIDC token endpoint
  3. Returns JWT access token (expires in 8 hours)
  4. OpenAI client uses: openai.OpenAI(base_url=..., api_key=jwt_token)

This utility creates service API tokens for non-interactive use:
  1. Admin generates token: make create-service-token NAME=my-service GROUPS=notebook-users
  2. Service stores token as environment variable
  3. OpenAI client uses: openai.OpenAI(base_url=..., api_key=service_token)
  4. No login UI, no token refresh logic needed

RELATED DOCUMENTATION:
- examples/openai_client_service_token_example.py - Complete usage example
- src/agentic_framework_pkg/streamlit_app_v2/Chat.py - User JWT pattern
- docs/security/SERVICE_API_TOKEN_ARCHITECTURE.md - Security analysis

ENVIRONMENT VARIABLES:
- KC_ADMIN_CLI_SECRET: Admin-CLI client secret (required)
- KC_BOOTSTRAP_ADMIN_USERNAME: Keycloak admin username (default: admin)
- KC_BOOTSTRAP_ADMIN_PASSWORD: Keycloak admin password (default: admin)

USAGE:
    # Create service token (90-day default)
    python scripts/deps/create_service_api_token.py \\
        --name my-automation-service \\
        --groups notebook-users \\
        --description "CI/CD pipeline automation"

    # Create token with custom TTL (30 days)
    python scripts/deps/create_service_api_token.py \\
        --name short-lived-service \\
        --groups gateway-agents \\
        --ttl-days 30

    # List all active tokens
    python scripts/deps/create_service_api_token.py --list

    # Revoke token
    python scripts/deps/create_service_api_token.py --revoke sk-service-my-automation-service-abc123

MAKEFILE INTEGRATION:
    # Create service token
    make create-service-token NAME=my-service GROUPS=notebook-users TTL_DAYS=90

    # List tokens
    make list-service-tokens

    # Revoke token
    make revoke-service-token TOKEN=sk-service-...

VALIDATION:
After creating a token, test it:
    export ADEPT_SERVICE_API_TOKEN="sk-service-..."
    python examples/openai_client_service_token_example.py
"""
import argparse
import json
import os
import secrets
import string
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from keycloak import KeycloakAdmin, KeycloakOpenIDConnection

# --- Add src to path to import core utilities ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))
from agentic_framework_pkg.core.secrets_manager import get_secret, save_secrets
from agentic_framework_pkg.core.service_token_manager import ServiceTokenManager, generate_service_token
from agentic_framework_pkg.logger_config import get_logger
import asyncio
import redis.asyncio as redis

logger = get_logger(__name__)

# Token metadata storage location (relative to credentials directory)
TOKEN_METADATA_FILE = "service_api_tokens_metadata.json"


# =============================================================================
# KEYCLOAK CONNECTION
# =============================================================================


def get_keycloak_admin_client() -> Optional[KeycloakAdmin]:
    """
    Establishes a connection with the Keycloak server and returns an admin client.

    Returns:
        KeycloakAdmin client or None if connection fails
    """
    # CRITICAL: admin-cli is a confidential client requiring a client secret
    admin_cli_secret = get_secret("KC_ADMIN_CLI_SECRET")

    if not admin_cli_secret:
        logger.error(
            "KC_ADMIN_CLI_SECRET not found in credentials directory or environment variables."
        )
        logger.error(
            "The admin-cli client is configured as a confidential client and requires a client secret."
        )
        logger.error(
            "To discover the secret, run: ./scripts/deps/discover_admin_cli_secret.sh"
        )
        logger.error(
            "Then save to /app/credentials/KC_ADMIN_CLI_SECRET or add to .env file."
        )
        return None

    keycloak_connection = KeycloakOpenIDConnection(
        server_url="http://keycloak:8180/",
        username=os.getenv("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        password=os.getenv("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"),
        realm_name="master",
        user_realm_name="master",
        verify=True,
        client_secret_key=admin_cli_secret,
    )

    for i in range(10):
        try:
            admin_client = KeycloakAdmin(connection=keycloak_connection)
            admin_client.get_realms()  # Test connection
            logger.info("Successfully connected to Keycloak.")
            return admin_client
        except Exception as e:
            logger.warning(
                f"Could not connect to Keycloak, retrying in 5 seconds... ({e})"
            )
            time.sleep(5)

    logger.error("Failed to connect to Keycloak after multiple retries.")
    return None


# =============================================================================
# TOKEN GENERATION
# =============================================================================


def generate_api_key(service_name: str, length: int = 32) -> str:
    """
    Generate a cryptographically secure service API key.

    Args:
        service_name: Service name for prefix (e.g., "my-automation-service")
        length: Random portion length (default 32 characters)

    Returns:
        Service API key with format: sk-service-{service_name}-{random}
    """
    # Sanitize service name for token prefix (alphanumeric + hyphens only)
    safe_name = "".join(
        c if c.isalnum() or c == "-" else "-" for c in service_name.lower()
    )
    safe_name = safe_name[:32]  # Limit prefix length

    alphabet = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(length))

    return f"sk-service-{safe_name}-{random_part}"


# =============================================================================
# TOKEN METADATA MANAGEMENT
# =============================================================================


def get_credentials_dir() -> str:
    """Get credentials directory path."""
    # Check common credential locations
    possible_dirs = [
        "/app/credentials",  # Container path
        "./deployment/local/docker-compose/.env-keycloak-credentials-dir",  # Host path
        "./.env-keycloak-credentials-dir",  # Project root
    ]

    for dir_path in possible_dirs:
        if os.path.exists(dir_path) and os.path.isdir(dir_path):
            return dir_path

    # Default to /app/credentials (will be created if needed)
    return "/app/credentials"


def load_token_metadata() -> Dict:
    """
    Load service API token metadata from JSON file.

    Returns:
        Dictionary of token metadata (token -> metadata dict)
    """
    credentials_dir = get_credentials_dir()
    metadata_path = os.path.join(credentials_dir, TOKEN_METADATA_FILE)

    if not os.path.exists(metadata_path):
        return {}

    try:
        with open(metadata_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load token metadata: {e}")
        return {}


def save_token_metadata(metadata: Dict) -> None:
    """
    Save service API token metadata to JSON file.

    Args:
        metadata: Dictionary of token metadata
    """
    credentials_dir = get_credentials_dir()
    os.makedirs(credentials_dir, exist_ok=True)

    metadata_path = os.path.join(credentials_dir, TOKEN_METADATA_FILE)

    try:
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Saved token metadata to: {metadata_path}")
    except Exception as e:
        logger.error(f"Failed to save token metadata: {e}")
        raise


def add_token_metadata(
    token: str,
    service_name: str,
    groups: List[str],
    description: str,
    ttl_days: int,
) -> None:
    """
    Add metadata for a new service token.

    Args:
        token: Service API token
        service_name: Service name
        groups: List of Keycloak groups
        description: Token description
        ttl_days: Time-to-live in days
    """
    metadata = load_token_metadata()

    expires_at = (datetime.utcnow() + timedelta(days=ttl_days)).isoformat()

    metadata[token] = {
        "service_name": service_name,
        "groups": groups,
        "description": description,
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": expires_at,
        "ttl_days": ttl_days,
        "revoked": False,
    }

    save_token_metadata(metadata)


def revoke_token_metadata(token: str) -> bool:
    """
    Mark a token as revoked in metadata.

    Args:
        token: Service API token to revoke

    Returns:
        True if token was found and revoked, False otherwise
    """
    metadata = load_token_metadata()

    if token not in metadata:
        logger.error(f"Token not found in metadata: {token[:20]}...")
        return False

    metadata[token]["revoked"] = True
    metadata[token]["revoked_at"] = datetime.utcnow().isoformat()

    save_token_metadata(metadata)
    return True


# =============================================================================
# TOKEN OPERATIONS
# =============================================================================


async def write_token_to_redis(
    token: str,
    service_name: str,
    groups: List[str],
    description: str,
    ttl_days: int,
    created_by: str = "admin"
) -> bool:
    """
    Write service token to Redis Database 1 (Phase 1 dual-mode).

    Args:
        token: Generated service API token
        service_name: Service name
        groups: List of Keycloak groups
        description: Human-readable description
        ttl_days: Time-to-live in days
        created_by: Username who created the token

    Returns:
        True if successful, False otherwise
    """
    try:
        # Connect to Redis Database 1
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0").rsplit("/", 1)[0]
        redis_url = f"{redis_url}/1"

        redis_client = redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

        # Initialize token manager
        token_manager = ServiceTokenManager(redis_client)

        # Create token in Redis
        success = await token_manager.create_token(
            token=token,
            service_name=service_name,
            groups=groups,
            description=description,
            created_by=created_by,
            ttl_days=ttl_days,
        )

        await redis_client.close()

        if success:
            logger.info(f"✅ Token written to Redis Database 1: {service_name}")
        else:
            logger.warning(f"⚠️  Token already exists in Redis: {service_name}")

        return success

    except Exception as e:
        logger.error(f"Failed to write token to Redis: {e}", exc_info=True)
        return False


def create_service_token(
    service_name: str,
    groups: List[str],
    description: str = "",
    ttl_days: int = 90,
    admin_client: Optional[KeycloakAdmin] = None,
) -> Optional[str]:
    """
    Create a new service API token.

    Phase 1 (Dual-Mode): Writes to BOTH file and Redis for zero-risk deployment.
    Phase 2 (Future): Will write to Redis-only.

    Args:
        service_name: Service name for token identification
        groups: List of Keycloak groups to assign
        description: Human-readable description
        ttl_days: Time-to-live in days (default 90)
        admin_client: Keycloak admin client (optional, will create if not provided)

    Returns:
        Generated service API token, or None if creation failed
    """
    # Generate token using core utility
    token = generate_service_token(service_name)

    # Phase 1 Dual-Mode: Write to BOTH file and Redis
    try:
        # 1. Write to file (existing flow)
        # Load existing SERVICE_API_KEYS_CONFIG
        existing_config_json = get_secret("SERVICE_API_KEYS_CONFIG")
        if existing_config_json:
            service_keys_config = json.loads(existing_config_json)
        else:
            service_keys_config = {}

        # Add new token
        service_keys_config[token] = {
            "client_id": f"service-{service_name}",  # Virtual client ID
            "groups": groups,
            "user_id": f"service-{service_name}",
            "username": f"{service_name}-service",
            "description": description,
        }

        # Save updated configuration to file
        secrets_to_write = {"SERVICE_API_KEYS_CONFIG": json.dumps(service_keys_config)}
        save_secrets(secrets_to_write)
        logger.info(f"✅ Token written to file: {service_name}")

        # Add metadata for tracking
        add_token_metadata(token, service_name, groups, description, ttl_days)

        # 2. Write to Redis (Phase 1 new flow)
        redis_success = asyncio.run(
            write_token_to_redis(
                token=token,
                service_name=service_name,
                groups=groups,
                description=description,
                ttl_days=ttl_days,
                created_by="admin"
            )
        )

        if redis_success:
            logger.info(f"✅ DUAL-MODE SUCCESS: Token written to both file and Redis: {service_name}")
        else:
            logger.warning(f"⚠️  Token written to file but Redis write failed: {service_name}")

        return token

    except Exception as e:
        logger.error(f"Failed to create service token: {e}")
        return None


def list_service_tokens() -> None:
    """
    List all service API tokens with their metadata.
    """
    metadata = load_token_metadata()

    print("\n" + "=" * 80)
    print("Service API Tokens")
    print("=" * 80)

    if not metadata:
        print("No service tokens found.")
        print("\nCreate a token with:")
        print("  make create-service-token NAME=my-service GROUPS=notebook-users")
        print("=" * 80 + "\n")
        return

    now = datetime.utcnow()

    active_tokens = []
    expired_tokens = []
    revoked_tokens = []

    for token, info in metadata.items():
        expires_at = datetime.fromisoformat(info["expires_at"])
        is_expired = now > expires_at
        is_revoked = info.get("revoked", False)

        token_info = {
            "token_prefix": token[:30] + "...",
            "service_name": info["service_name"],
            "groups": ", ".join(info["groups"]),
            "description": info.get("description", "N/A"),
            "created_at": info["created_at"][:10],
            "expires_at": info["expires_at"][:10],
            "days_remaining": (expires_at - now).days if not is_expired else 0,
            "status": "REVOKED" if is_revoked else ("EXPIRED" if is_expired else "ACTIVE"),
        }

        if is_revoked:
            revoked_tokens.append(token_info)
        elif is_expired:
            expired_tokens.append(token_info)
        else:
            active_tokens.append(token_info)

    # Print active tokens
    if active_tokens:
        print(f"\n🟢 ACTIVE TOKENS ({len(active_tokens)}):")
        print("-" * 80)
        for info in active_tokens:
            print(f"  Service: {info['service_name']}")
            print(f"    Token: {info['token_prefix']}")
            print(f"    Groups: {info['groups']}")
            print(f"    Description: {info['description']}")
            print(f"    Created: {info['created_at']} | Expires: {info['expires_at']} ({info['days_remaining']} days)")
            print()

    # Print expired tokens
    if expired_tokens:
        print(f"\n🟡 EXPIRED TOKENS ({len(expired_tokens)}):")
        print("-" * 80)
        for info in expired_tokens:
            print(f"  Service: {info['service_name']} | Expired: {info['expires_at']}")

    # Print revoked tokens
    if revoked_tokens:
        print(f"\n🔴 REVOKED TOKENS ({len(revoked_tokens)}):")
        print("-" * 80)
        for info in revoked_tokens:
            print(f"  Service: {info['service_name']} | Revoked")

    print("\n" + "=" * 80)
    print(f"Total: {len(metadata)} tokens ({len(active_tokens)} active, {len(expired_tokens)} expired, {len(revoked_tokens)} revoked)")
    print("=" * 80 + "\n")


async def revoke_token_from_redis(token: str, revoked_by: str = "admin") -> bool:
    """
    Revoke service token in Redis Database 1 (Phase 1 dual-mode).

    Args:
        token: Service API token to revoke
        revoked_by: Username who revoked the token

    Returns:
        True if successful, False otherwise
    """
    try:
        # Connect to Redis Database 1
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0").rsplit("/", 1)[0]
        redis_url = f"{redis_url}/1"

        redis_client = redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

        # Initialize token manager
        token_manager = ServiceTokenManager(redis_client)

        # Revoke token in Redis
        success = await token_manager.revoke_token(token, revoked_by=revoked_by)

        await redis_client.close()

        if success:
            logger.info(f"✅ Token revoked in Redis: {token[:20]}...")
        else:
            logger.warning(f"⚠️  Token not found in Redis: {token[:20]}...")

        return success

    except Exception as e:
        logger.error(f"Failed to revoke token in Redis: {e}", exc_info=True)
        return False


def revoke_service_token(token: str) -> bool:
    """
    Revoke a service API token.

    Phase 1 (Dual-Mode): Revokes from BOTH file and Redis.
    Phase 2 (Future): Will revoke from Redis-only.

    Args:
        token: Service API token to revoke

    Returns:
        True if successful, False otherwise
    """
    try:
        # Phase 1 Dual-Mode: Revoke from BOTH file and Redis
        file_success = False
        redis_success = False

        # 1. Revoke from file (existing flow)
        existing_config_json = get_secret("SERVICE_API_KEYS_CONFIG")
        if not existing_config_json:
            logger.error("SERVICE_API_KEYS_CONFIG not found")
        else:
            service_keys_config = json.loads(existing_config_json)

            if token not in service_keys_config:
                logger.warning(f"Token not found in SERVICE_API_KEYS_CONFIG: {token[:20]}...")
            else:
                del service_keys_config[token]

                # Save updated configuration
                secrets_to_write = {"SERVICE_API_KEYS_CONFIG": json.dumps(service_keys_config)}
                save_secrets(secrets_to_write)
                logger.info(f"✅ Token removed from file: {token[:20]}...")
                file_success = True

        # Mark as revoked in metadata
        revoke_token_metadata(token)

        # 2. Revoke from Redis (Phase 1 new flow)
        redis_success = asyncio.run(
            revoke_token_from_redis(token, revoked_by="admin")
        )

        if file_success or redis_success:
            print(f"\n✅ Successfully revoked token: {token[:30]}...")
            if file_success and redis_success:
                print("   ✅ Revoked from both file and Redis")
            elif file_success:
                print("   ⚠️  Revoked from file only (not found in Redis)")
            else:
                print("   ⚠️  Revoked from Redis only (not found in file)")
            print()
            return True
        else:
            print(f"\n❌ Token not found in either file or Redis: {token[:30]}...\n")
            return False

    except Exception as e:
        logger.error(f"Failed to revoke service token: {e}")
        return False


# =============================================================================
# CLI INTERFACE
# =============================================================================


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Service API Token Creation Utility for ADEPT Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create service token (90-day default)
  %(prog)s --name my-automation --groups notebook-users --description "CI/CD pipeline"

  # Create token with custom TTL (30 days)
  %(prog)s --name short-lived --groups gateway-agents --ttl-days 30

  # List all tokens
  %(prog)s --list

  # Revoke token
  %(prog)s --revoke sk-service-my-automation-abc123

Service Token vs User JWT:
  - Service Token: Long-lived bearer token for automation/services
  - User JWT: Short-lived token from Keycloak login (8 hours)

For usage examples, see: examples/openai_client_service_token_example.py
        """,
    )

    parser.add_argument(
        "--name",
        type=str,
        help="Service name for token identification",
    )

    parser.add_argument(
        "--groups",
        type=str,
        help='Comma-separated list of groups (e.g., "notebook-users,gateway-agents")',
    )

    parser.add_argument(
        "--description",
        type=str,
        default="",
        help="Human-readable description of the service/use case",
    )

    parser.add_argument(
        "--ttl-days",
        type=int,
        default=90,
        help="Time-to-live in days (default: 90 days)",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List all service API tokens",
    )

    parser.add_argument(
        "--revoke",
        type=str,
        metavar="TOKEN",
        help="Revoke a service API token",
    )

    return parser.parse_args()


def main():
    """Main entry point for service API token creation."""
    args = parse_args()

    # List tokens and exit
    if args.list:
        list_service_tokens()
        sys.exit(0)

    # Revoke token and exit
    if args.revoke:
        success = revoke_service_token(args.revoke)
        sys.exit(0 if success else 1)

    # Validate required arguments for token creation
    if not args.name:
        logger.error("--name is required (or use --list / --revoke)")
        sys.exit(1)

    if not args.groups:
        logger.error("--groups is required (e.g., --groups notebook-users)")
        sys.exit(1)

    # Parse groups
    group_list = [g.strip() for g in args.groups.split(",") if g.strip()]
    if not group_list:
        logger.error("No valid groups specified")
        sys.exit(1)

    # Connect to Keycloak (for group validation)
    admin_client = get_keycloak_admin_client()
    if not admin_client:
        logger.error("Failed to connect to Keycloak. Exiting.")
        sys.exit(1)

    # Validate groups exist
    all_groups = admin_client.get_groups()
    existing_group_names = {g["name"] for g in all_groups}
    missing_groups = [g for g in group_list if g not in existing_group_names]

    if missing_groups:
        logger.error(f"Groups do not exist in Keycloak: {', '.join(missing_groups)}")
        logger.info(f"Available groups: {', '.join(sorted(existing_group_names))}")
        sys.exit(1)

    # Create service token
    token = create_service_token(
        service_name=args.name,
        groups=group_list,
        description=args.description,
        ttl_days=args.ttl_days,
        admin_client=admin_client,
    )

    if not token:
        sys.exit(1)

    # Print success message with usage instructions
    print("\n" + "=" * 80)
    print("✅ Service API Token Created Successfully")
    print("=" * 80)
    print(f"Service Name: {args.name}")
    print(f"Groups: {', '.join(group_list)}")
    print(f"Description: {args.description or 'N/A'}")
    print(f"TTL: {args.ttl_days} days")
    print(f"\n🔑 Service API Token:")
    print(f"  {token}")
    print("\n" + "=" * 80)
    print("Usage Instructions")
    print("=" * 80)
    print("\n1. Store token securely (environment variable or secret manager):")
    print(f"   export ADEPT_SERVICE_API_TOKEN='{token}'")
    print("\n2. Use with OpenAI-compatible client:")
    print("   import openai")
    print("   client = openai.OpenAI(")
    print("       base_url='https://api.agentic.local/v1',")
    print(f"       api_key='{token}'")
    print("   )")
    print("\n3. See complete example:")
    print("   python examples/openai_client_service_token_example.py")
    print("\n4. Test authentication:")
    print(f"   curl -H 'Authorization: Bearer {token}' \\")
    print("        https://api.agentic.local/v1/models")
    print("\n" + "=" * 80)
    print("⚠️  SECURITY WARNING:")
    print("  - Treat this token like a password")
    print("  - Never commit to version control")
    print("  - Rotate before expiration")
    print("  - Revoke if compromised: make revoke-service-token TOKEN=...")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
