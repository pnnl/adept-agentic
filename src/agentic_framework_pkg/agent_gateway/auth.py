"""
Agent Gateway Authentication Module (Legacy Compatibility Layer)

DEPRECATED: This module now serves as a compatibility layer that delegates
to the centralized authentication system in src/agentic_framework_pkg/core/auth.py.

For new code, import directly from the core auth module:
    from agentic_framework_pkg.core.auth import (
        AuthCredentials,
        get_current_user,
        require_role,
        require_any_role,
        validate_jwt_token,
        validate_service_api_key
    )

This compatibility layer maintains backward compatibility for existing imports
while providing a migration path to the centralized authentication system.

Migration Status (Session 49):
-   **Phase 1 (Dual-Mode)**: Supports both Redis and file-based tokens
-   **Phase 2 (Future)**: Will remove file-based support, Redis-only
"""
import os
import hashlib
import hmac
from typing import Dict, Any, Optional, List, Union
from keycloak import KeycloakOpenID
from jose import jwt
from jose.exceptions import JOSEError
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
import httpx

from ..logger_config import get_logger
from ..core.service_token_manager import ServiceTokenManager, BOOTSTRAP_TOKENS
from .redis_client import get_tokens_redis_client

logger = get_logger(__name__)

# Service token manager (lazy initialization)
_token_manager: Optional[ServiceTokenManager] = None

# --- Keycloak Configuration ---
# These should be set in your environment (e.g., .env file, docker-compose)
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
KEYCLOAK_EXTERNAL_URL = os.getenv("KEYCLOAK_EXTERNAL_URL", KEYCLOAK_URL) # Fallback to KEYCLOAK_URL
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID")

# A2A JWKS Federation: Trusted peer Keycloak JWKS endpoints for cross-gateway token validation.
# When a token's signing key (kid) is not found in the local Keycloak's JWKS, the gateway will
# try fetching keys from these peer endpoints. This enables cross-instance A2A communication
# where each gateway has its own Keycloak with different signing keys but the same issuer URL.
# Format: comma-separated full JWKS URLs (e.g., https://10.0.0.1/realms/master/protocol/openid-connect/certs)
_raw_peer_jwks = os.getenv("A2A_TRUSTED_PEER_JWKS_URLS", "")
A2A_TRUSTED_PEER_JWKS_URLS = [url.strip() for url in _raw_peer_jwks.split(",") if url.strip()]

keycloak_openid = KeycloakOpenID(
    server_url=KEYCLOAK_URL,
    realm_name=KEYCLOAK_REALM,
    client_id=KEYCLOAK_CLIENT_ID,
)

# Re-export canonical AuthCredentials and exceptions from core.auth (Phase 0c consolidation)
from ..core.auth import AuthCredentials, JWTValidationError, ServiceAPIKeyValidationError

# --- Service API Key Configuration ---
from ..core.secrets_manager import get_secret

def load_service_api_keys() -> Dict[str, Any]:
    """Load service API keys from secure credentials using existing secrets manager."""
    import json
    
    service_keys_config = get_secret("SERVICE_API_KEYS_CONFIG")
    if not service_keys_config:
        logger.warning("SERVICE_API_KEYS_CONFIG not found in secrets. Service API key authentication will be disabled.")
        return {}
    
    try:
        service_keys = json.loads(service_keys_config)

        # Bootstrap tokens are now loaded from BOOTSTRAP_SERVICE_TOKENS secret
        # via service_token_manager.BOOTSTRAP_TOKENS — no longer duplicated here.
        # The Redis validation path checks BOOTSTRAP_TOKENS first (before Redis),
        # and this file-based path merges them for backward compatibility.
        service_keys.update(BOOTSTRAP_TOKENS)
        logger.info(f"Loaded {len(service_keys)} service API keys from secrets manager (including {len(BOOTSTRAP_TOKENS)} bootstrap tokens)")
        return service_keys
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse SERVICE_API_KEYS_CONFIG JSON: {e}")
        return {}
    except Exception as e:
        logger.error(f"Failed to load service API keys: {e}")
        return {}

# Load service API keys at startup using existing secrets manager
SERVICE_API_KEYS = load_service_api_keys()

# --- Hot-Reload Support (Session 48) ---
import signal

def reload_service_api_keys_handler(signum, frame):
    """
    Signal handler for hot-reloading service API keys without container restart.

    Usage:
        docker exec agent_gateway kill -HUP 1
        # Or: make reload-service-tokens

    This eliminates the need to rebuild containers when creating new service tokens.
    """
    global SERVICE_API_KEYS
    logger.info("🔄 Received SIGHUP signal - reloading service API keys...")

    try:
        new_keys = load_service_api_keys()
        SERVICE_API_KEYS = new_keys
        logger.info(f"✅ Successfully reloaded {len(SERVICE_API_KEYS)} service API keys")
    except Exception as e:
        logger.error(f"❌ Failed to reload service API keys: {e}")
        logger.warning("⚠️  Continuing with existing keys in memory")

# Register SIGHUP handler for hot-reload (Session 48 enhancement)
signal.signal(signal.SIGHUP, reload_service_api_keys_handler)
logger.info("✅ SIGHUP handler registered for service token hot-reload")

# --- Authentication Setup ---
AUTH_ENABLED = os.getenv("AGENT_GATEWAY_AUTH_ENABLED", "false").lower() == "true"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False) # auto_error=False makes it optional

def detect_token_type(token: str) -> str:
    """
    Detects the type of authentication token.
    
    Args:
        token: The bearer token
        
    Returns:
        str: "jwt", "service_api_key", or "api_key"
    """
    if token.startswith("sk-service-"):
        return "service_api_key"
    elif token.startswith("sk-"):
        return "api_key"
    elif "." in token and len(token.split(".")) == 3:
        return "jwt"
    else:
        return "unknown"

async def get_token_manager() -> ServiceTokenManager:
    """
    Get or create singleton ServiceTokenManager instance.

    Returns:
        ServiceTokenManager: Initialized token manager
    """
    global _token_manager

    if _token_manager is None:
        redis_client = await get_tokens_redis_client()
        _token_manager = ServiceTokenManager(redis_client)
        logger.info("Initialized ServiceTokenManager with Redis Database 1")

    return _token_manager


async def validate_service_api_key_redis(token: str) -> Optional[Dict[str, Any]]:
    """
    Redis-based service API key validation (Phase 1: primary method).

    Validation flow:
    1. Check BOOTSTRAP_TOKENS (hardcoded, never in Redis)
    2. Check Redis with TokenCache (1-hour cache)
    3. Validate not revoked, not expired

    Args:
        token: The service API key

    Returns:
        Dict with service information, or None if invalid
    """
    logger.debug(f"Validating service API key via Redis: {token[:20]}...")

    # Step 1: Check bootstrap tokens (hardcoded, never in Redis)
    if token in BOOTSTRAP_TOKENS:
        service_info = BOOTSTRAP_TOKENS[token]
        logger.info(f"Bootstrap token validated: {service_info['client_id']}")
        return service_info

    # Step 2: Check Redis with caching
    try:
        token_manager = await get_token_manager()
        metadata = await token_manager.validate_token(token, update_usage=True)

        if metadata:
            # Convert metadata format to match auth expectations
            service_info = {
                "user_id": metadata["service_name"],  # Use service name as user_id
                "username": f"{metadata['service_name']}-service",
                "groups": metadata["groups"],
                "client_id": f"service-{metadata['service_name']}",
                "description": metadata.get("description", ""),
            }
            logger.info(f"Redis token validated: {service_info['client_id']}")
            return service_info
        else:
            logger.debug(f"Token not found or invalid in Redis")
            return None

    except Exception as e:
        logger.error(f"Redis validation error: {e}", exc_info=True)
        return None


async def validate_service_api_key(token: str) -> Dict[str, Any]:
    """
    Validates a service API key against the configured service keys.

    Phase 1 (Dual-Mode): Tries Redis first, falls back to file-based validation.
    Phase 2 (Future): Will use Redis-only.

    Args:
        token: The service API key (e.g., "sk-service-openwebui")

    Returns:
        Dict with service information

    Raises:
        ServiceAPIKeyValidationError: If the key is invalid
    """
    # Phase 1 Dual-Mode: Try Redis first, fall back to file
    service_info = await validate_service_api_key_redis(token)

    if service_info is None:
        # Redis validation failed, try file-based (Phase 1 fallback)
        logger.debug("Redis validation failed, trying file-based fallback...")

        if token not in SERVICE_API_KEYS:
            raise ServiceAPIKeyValidationError("Invalid service API key")

        service_info = SERVICE_API_KEYS[token]
        logger.info(f"Service API key validated (FILE - deprecated) for client: {service_info['client_id']}")

    return service_info

async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[AuthCredentials]:
    """
    Enhanced FastAPI dependency to get the current user's credentials from various auth types.

    Supports:
    1. JWT tokens (existing flow)
    2. Service API keys (sk-service-*)
    3. Regular API keys (sk-*) - future implementation

    Args:
        token: The bearer token from the Authorization header, injected by FastAPI.

    Returns:
        An AuthCredentials object if the token is valid, otherwise None.

    Raises:
        HTTPException: If authentication is enabled and the token is missing or invalid.
    """
    if not AUTH_ENABLED:
        return None # No auth, no user
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_type = detect_token_type(token)
    
    try:
        if token_type == "jwt":
            # Existing JWT validation flow
            payload = await validate_jwt(token)
            user_id = payload.get("sub")
            if not user_id:
                raise JWTValidationError("Token is missing the 'sub' (subject) claim.")
                
            username = payload.get("preferred_username") or payload.get("clientId", "unknown_user")
            return AuthCredentials(
                user_id=user_id,
                username=username,
                groups=payload.get("groups", []),
                token=token,
                auth_type="jwt"
            )
            
        elif token_type == "service_api_key":
            # New service API key validation
            service_info = await validate_service_api_key(token)
            return AuthCredentials(
                user_id=service_info["user_id"],
                username=service_info["username"], 
                groups=service_info["groups"],
                token=token,
                auth_type="service_api_key"
            )
            
        elif token_type == "api_key":
            # Future: Regular API key validation
            raise HTTPException(status_code=401, detail="Regular API keys not yet implemented")
            
        else:
            raise HTTPException(status_code=401, detail="Unknown token format")
            
    except (JWTValidationError, ServiceAPIKeyValidationError) as e:
        logger.warning(f"Authentication failed for token type {token_type}: {e}")
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected authentication error for token type {token_type}: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="Authentication failed")


async def get_public_key(token_issuer: str = None, token_kid: str = None):
    """
    Fetches JWKS from Keycloak. Tries local Keycloak first, then A2A trusted peer endpoints
    if the token's signing key (kid) is not found locally.

    Args:
        token_issuer: The issuer claim from the JWT token (for logging)
        token_kid: The key ID from the JWT header (used to check if local keys suffice)

    Returns:
        JWKS response dict with 'keys' array (may include keys from multiple sources)
    """
    async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
        # Step 1: Always fetch from local Keycloak first
        jwks_uri = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
        logger.info(f"JWT DEBUG - Token issuer: {repr(token_issuer)}, kid: {repr(token_kid)}")
        logger.info(f"JWT DEBUG - Fetching local Keycloak JWKS: {jwks_uri}")

        jwks_response = await client.get(jwks_uri)
        jwks_response.raise_for_status()
        jwks = jwks_response.json()

        # Step 2: Check if the token's kid exists in local JWKS
        if token_kid and A2A_TRUSTED_PEER_JWKS_URLS:
            local_kids = [k.get("kid") for k in jwks.get("keys", [])]
            if token_kid not in local_kids:
                logger.info(f"JWT A2A - kid {token_kid} not in local JWKS ({local_kids}), checking {len(A2A_TRUSTED_PEER_JWKS_URLS)} peer endpoint(s)")

                # Step 3: Try each trusted peer JWKS endpoint
                for peer_jwks_url in A2A_TRUSTED_PEER_JWKS_URLS:
                    try:
                        logger.info(f"JWT A2A - Fetching peer JWKS from: {peer_jwks_url}")
                        peer_response = await client.get(peer_jwks_url)
                        peer_response.raise_for_status()
                        peer_jwks = peer_response.json()

                        peer_kids = [k.get("kid") for k in peer_jwks.get("keys", [])]
                        if token_kid in peer_kids:
                            logger.info(f"JWT A2A - Found matching kid {token_kid} in peer JWKS from {peer_jwks_url}")
                            # Merge peer keys into the response
                            jwks["keys"].extend(peer_jwks.get("keys", []))
                            break
                        else:
                            logger.debug(f"JWT A2A - kid {token_kid} not in peer JWKS ({peer_kids}) from {peer_jwks_url}")
                    except Exception as e:
                        logger.warning(f"JWT A2A - Failed to fetch peer JWKS from {peer_jwks_url}: {e}")

        return jwks

async def validate_jwt(token: str) -> Dict[str, Any]:
    """
    Validates a JWT token against Keycloak's public keys using python-jose.
    Accepts tokens from both the internal (Docker) and external (host) Keycloak URLs.
    """
    if not token:
        raise JWTValidationError("No token provided.")

    try:
        unverified_header = jwt.get_unverified_header(token)
        unverified_claims = jwt.get_unverified_claims(token)
        
        token_issuer = unverified_claims.get("iss")
        if not token_issuer:
            raise JWTValidationError("Token is missing the 'iss' (issuer) claim.")

        # Fetch JWKS from local Keycloak (and peer endpoints if kid not found locally)
        token_kid = unverified_header.get("kid")
        jwks = await get_public_key(token_issuer, token_kid=token_kid)

        # Define valid issuers for internal and external access
        valid_issuers = [
            f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
            f"{KEYCLOAK_EXTERNAL_URL}/realms/{KEYCLOAK_REALM}",
            # Additional issuer patterns for NGINX proxy forwarding
            f"http://api.agentic.local/realms/{KEYCLOAK_REALM}",
            f"https://api.agentic.local/realms/{KEYCLOAK_REALM}",
            # Legacy localhost issuer (for tokens obtained via localhost endpoints)
            f"http://localhost:8180/realms/{KEYCLOAK_REALM}",
            # Internal Docker service DNS (container-to-container A2A communication)
            f"http://keycloak:8180/realms/{KEYCLOAK_REALM}",
            # JupyterLab frontend_net isolation (tokens acquired via nginx_proxy)
            f"https://nginx_proxy/realms/{KEYCLOAK_REALM}",
        ]

        if token_issuer not in valid_issuers:
            logger.debug(f"JWT Validation Debug - KEYCLOAK_URL: {KEYCLOAK_URL}")
            logger.debug(f"JWT Validation Debug - KEYCLOAK_EXTERNAL_URL: {KEYCLOAK_EXTERNAL_URL}")
            logger.debug(f"JWT Validation Debug - KEYCLOAK_REALM: {KEYCLOAK_REALM}")
            logger.debug(f"JWT Validation Debug - Valid issuers: {valid_issuers}")
            logger.debug(f"JWT Validation Debug - Token issuer: {token_issuer}")
            raise JWTValidationError(f"Invalid issuer. Expected one of {valid_issuers}, but got {token_issuer}.")

        rsa_key = {}
        logger.debug(f"JWT DEBUG - Looking for key ID: {unverified_header.get('kid')}")
        logger.debug(f"JWT DEBUG - Available keys: {[k.get('kid') for k in jwks.get('keys', [])]}")
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                logger.debug(f"JWT DEBUG - Found matching key: {key['kid']}")
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
        if rsa_key:
            # Decode the JWT payload using the found RSA key
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=None,  # We'll validate audience manually below
                issuer=token_issuer,  # Validate the issuer we already checked
                options={"verify_aud": False}  # Disable automatic audience verification since we handle it manually
            )
            
            # The audience can be 'account' for user tokens or the client_id for S2S tokens
            valid_audiences = ["account", KEYCLOAK_CLIENT_ID]
            
            # We must verify the audience, but the claim may be a string or a list.
            # A token for a user might have 'account', while a service token might have the client_id.
            # A missing 'aud' claim is also possible for certain legacy or direct grant flows.
            token_audience = payload.get("aud")
            if token_audience: # Only validate audience if the claim exists
                # Coerce to a set for easy intersection checking
                if isinstance(token_audience, str):
                    token_audience_set = {token_audience}
                else:
                    token_audience_set = set(token_audience)
                
                valid_audiences_set = set(valid_audiences)

                if not token_audience_set.intersection(valid_audiences_set):
                    raise JWTValidationError(f"Invalid audience. Expected one of {valid_audiences}, but got {token_audience}.")

            return payload
        raise JWTValidationError("Unable to find a matching key.")
    except JOSEError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise JWTValidationError(f"Token validation error: {e}") from e
    except Exception as e:
        logger.error(f"An unexpected error occurred during JWT validation: {e}", exc_info=True)
        raise JWTValidationError(f"An unexpected error occurred during token validation: {e}")

def require_role(role_name: str):
    """
    FastAPI dependency factory for enforcing role-based access control.

    Creates a dependency that checks if the current user is a member of the
    specified group (role).

    Args:
        role_name: The name of the Keycloak group the user must belong to.

    Returns:
        An async function (FastAPI dependency) that performs the check.
    """
    async def role_checker(credentials: AuthCredentials = Depends(get_current_user)):
        if not credentials:
            # This case is hit when AUTH_ENABLED is false.
            # An endpoint requiring a role should not be accessible when auth is off.
            logger.warning(f"Access denied to endpoint requiring role '{role_name}' because authentication is disabled.")
            raise HTTPException(status_code=403, detail=f"Access denied: Authentication is required to verify role '{role_name}'.")
        
        if role_name not in credentials.groups:
            logger.warning(f"Access denied for user '{credentials.username}'. Missing required role: '{role_name}'.")
            raise HTTPException(status_code=403, detail=f"User does not have the required '{role_name}' role.")
        
        return credentials
    return role_checker

def require_any_role(role_names: List[str]):
    """
    FastAPI dependency factory for enforcing role-based access control with multiple allowed roles.

    Creates a dependency that checks if the current user is a member of any of the
    specified groups (roles).

    Args:
        role_names: List of Keycloak group names, user must belong to at least one.

    Returns:
        An async function (FastAPI dependency) that performs the check.
    """
    async def role_checker(credentials: AuthCredentials = Depends(get_current_user)):
        if not credentials:
            # This case is hit when AUTH_ENABLED is false.
            # An endpoint requiring a role should not be accessible when auth is off.
            logger.warning(f"Access denied to endpoint requiring any of roles {role_names} because authentication is disabled.")
            raise HTTPException(status_code=403, detail=f"Access denied: Authentication is required to verify roles.")
        
        if not credentials.has_any_group(role_names):
            logger.warning(f"Access denied for user '{credentials.username}'. Missing any of required roles: '{role_names}'.")
            raise HTTPException(status_code=403, detail=f"User does not have any of the required roles: {', '.join(role_names)}.")
        
        return credentials
    return role_checker

def validate_service_api_key_legacy(api_key: str) -> Dict[str, Any]:
    """
    Legacy function for backward compatibility with service API key validation.
    
    Args:
        api_key: Service API key string
        
    Returns:
        Dict with service information for backward compatibility
    """
    if api_key not in SERVICE_API_KEYS:
        raise ServiceAPIKeyValidationError("Invalid service API key")
    
    service_info = SERVICE_API_KEYS[api_key]
    return {
        "user_id": service_info.get("user_id"),
        "username": service_info.get("username"),
        "groups": service_info.get("groups", []),
        "client_id": service_info.get("client_id")
    }

# Phase 0c: Compatibility layer removed — AuthCredentials, JWTValidationError,
# and ServiceAPIKeyValidationError are now re-exported from core.auth at the
# top of this file.  All imports of the form
#     from ..agent_gateway.auth import AuthCredentials
# transparently resolve to the canonical core.auth definition.
from ..core.auth import AuthenticationError  # noqa: F401 – re-export for legacy callers
