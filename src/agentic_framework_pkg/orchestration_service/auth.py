"""
This module handles the internal authentication for the Orchestration Service.

Its primary responsibility is to validate tokens that have been forwarded from
the Agent Gateway and establish the original user's security context for the
current request.

Supports both JWT tokens and Service API keys forwarded from the Agent Gateway.

Architectural Role:
-   **Internal Security:** Acts as the security gate for the orchestration service.
-   **Context Propagation:** It defines the `get_forwarded_user` dependency, which
    reads the `X-Forwarded-User-Token` header, validates the token within it, and
    constructs an `AuthCredentials` object. This object is then injected into
    the endpoint (e.g., `/invoke`), making the user's identity available to the
    core agent logic.

Migration Status (Session 49):
-   **Phase 1 (Dual-Mode)**: Supports both Redis and file-based tokens
-   **Phase 2 (Future)**: Will remove file-based support, Redis-only
"""
import os
import json
from typing import Optional
from fastapi import Request, HTTPException, Depends
from ..core.auth import detect_token_type, AuthCredentials, JWTValidationError, ServiceAPIKeyValidationError, validate_jwt_multi_stack
from ..core.secrets_manager import get_secret
from ..core.service_token_manager import ServiceTokenManager, BOOTSTRAP_TOKENS
from .redis_client import get_tokens_redis_client
from ..logger_config import get_logger

logger = get_logger(__name__)

# Service token manager (lazy initialization)
_token_manager: Optional[ServiceTokenManager] = None

# Service API Key Configuration for Orchestration Service
def load_service_api_keys():
    """Load service API keys from secrets manager for orchestration service (same as agent_gateway)."""
    try:
        # First try to load from secrets manager (preferred)
        service_keys_config = get_secret("SERVICE_API_KEYS_CONFIG")
        if not service_keys_config:
            # Fallback to environment variable
            service_keys_config = os.getenv("SERVICE_API_KEYS_CONFIG")
            if not service_keys_config:
                logger.warning("SERVICE_API_KEYS_CONFIG not found in secrets or environment. Service API key authentication will be disabled.")
                return {}
            logger.info("[ORCHESTRATION_SERVICE] Loading service API keys from environment (fallback)")
        else:
            logger.info("[ORCHESTRATION_SERVICE] Loading service API keys from secrets manager (preferred)")

        service_keys = json.loads(service_keys_config)

        # Bootstrap tokens are now loaded from BOOTSTRAP_SERVICE_TOKENS secret
        # via service_token_manager.BOOTSTRAP_TOKENS — no longer duplicated here.
        service_keys.update(BOOTSTRAP_TOKENS)
        logger.info(f"[ORCHESTRATION_SERVICE] Loaded {len(service_keys)} service API keys (including {len(BOOTSTRAP_TOKENS)} bootstrap tokens)")
        return service_keys
    except json.JSONDecodeError as e:
        logger.error(f"[ORCHESTRATION_SERVICE] Failed to parse SERVICE_API_KEYS_CONFIG JSON: {e}")
        return {}
    except Exception as e:
        logger.error(f"[ORCHESTRATION_SERVICE] Failed to load service API keys: {e}")
        return {}

# Load service API keys at startup
SERVICE_API_KEYS = load_service_api_keys()

# --- Hot-Reload Support (Session 48) ---
import signal

def reload_service_api_keys_handler(signum, frame):
    """
    Signal handler for hot-reloading service API keys without container restart.

    Usage:
        docker exec orchestration_service kill -HUP 1
        # Or: make reload-service-tokens

    This eliminates the need to rebuild containers when creating new service tokens.
    """
    global SERVICE_API_KEYS
    logger.info("[ORCHESTRATION_SERVICE] 🔄 Received SIGHUP signal - reloading service API keys...")

    try:
        new_keys = load_service_api_keys()
        SERVICE_API_KEYS = new_keys
        logger.info(f"[ORCHESTRATION_SERVICE] ✅ Successfully reloaded {len(SERVICE_API_KEYS)} service API keys")
    except Exception as e:
        logger.error(f"[ORCHESTRATION_SERVICE] ❌ Failed to reload service API keys: {e}")
        logger.warning("[ORCHESTRATION_SERVICE] ⚠️  Continuing with existing keys in memory")

# Register SIGHUP handler for hot-reload (Session 48 enhancement)
signal.signal(signal.SIGHUP, reload_service_api_keys_handler)
logger.info("[ORCHESTRATION_SERVICE] ✅ SIGHUP handler registered for service token hot-reload")

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
        logger.info("[ORCHESTRATION_SERVICE] Initialized ServiceTokenManager with Redis Database 1")

    return _token_manager


async def validate_service_api_key_redis(token: str) -> Optional[dict]:
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
    logger.debug(f"[ORCHESTRATION_SERVICE] Validating service API key via Redis: {token[:20]}...")

    # Step 1: Check bootstrap tokens (hardcoded, never in Redis)
    if token in BOOTSTRAP_TOKENS:
        service_info = BOOTSTRAP_TOKENS[token]
        logger.info(f"[ORCHESTRATION_SERVICE] Bootstrap token validated: {service_info['client_id']}")
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
            logger.info(f"[ORCHESTRATION_SERVICE] Redis token validated: {service_info['client_id']}")
            return service_info
        else:
            logger.debug(f"[ORCHESTRATION_SERVICE] Token not found or invalid in Redis")
            return None

    except Exception as e:
        logger.error(f"[ORCHESTRATION_SERVICE] Redis validation error: {e}", exc_info=True)
        return None


async def validate_service_api_key_local(token: str):
    """
    File-based service API key validation (Phase 1: fallback method).

    DEPRECATION NOTICE: This will be removed in Phase 2.

    Args:
        token: The service API key

    Returns:
        Dict with service information

    Raises:
        ServiceAPIKeyValidationError: If the key is invalid
    """
    logger.debug(f"[ORCHESTRATION_SERVICE] Validating service API key (FILE - deprecated): {token[:20]}...")
    logger.debug(f"[ORCHESTRATION_SERVICE] Available service keys: {list(SERVICE_API_KEYS.keys())}")

    if token not in SERVICE_API_KEYS:
        logger.warning(f"[ORCHESTRATION_SERVICE] Service API key not found in configured keys")
        raise ServiceAPIKeyValidationError("Invalid service API key")

    service_info = SERVICE_API_KEYS[token]
    logger.info(f"[ORCHESTRATION_SERVICE] Service API key validated (FILE - deprecated) for client: {service_info['client_id']}")
    return service_info

async def get_forwarded_user(request: Request) -> AuthCredentials:
    """
    FastAPI dependency to validate a token (JWT or Service API Key) passed in a header from the gateway
    and return the user's credentials.

    This is the core of the secure context propagation from the Ingress tier
    (Agent Gateway) to the Orchestrator tier. Supports both JWT tokens and Service API keys.

    Phase 1 (Dual-Mode): Tries Redis first, falls back to file-based validation.
    Phase 2 (Future): Will use Redis-only.

    Args:
        request: The incoming FastAPI request.

    Returns:
        An `AuthCredentials` object representing the original user.

    Raises:
        HTTPException: If the token is missing or invalid.
    """
    token = request.headers.get("X-Forwarded-User-Token")
    if not token:
        raise HTTPException(status_code=401, detail="User token not forwarded from gateway. Direct access to orchestration service is not allowed.")

    logger.debug(f"[ORCHESTRATION_SERVICE] Received forwarded token: {token[:20]}...")
    token_type = detect_token_type(token)
    logger.debug(f"[ORCHESTRATION_SERVICE] Detected token type: {token_type}")

    try:
        if token_type == "jwt":
            # JWT validation via core.auth — returns AuthCredentials directly
            return await validate_jwt_multi_stack(token)
        elif token_type == "service_api_key":
            # Phase 1 Dual-Mode: Try Redis first, fall back to file
            service_info = await validate_service_api_key_redis(token)

            if service_info is None:
                # Redis validation failed, try file-based (Phase 1 fallback)
                logger.debug("[ORCHESTRATION_SERVICE] Redis validation failed, trying file-based fallback...")
                service_info = await validate_service_api_key_local(token)

            return AuthCredentials(
                user_id=service_info["user_id"],
                username=service_info["username"],
                groups=service_info["groups"],
                token=token,
                auth_type="service_api_key"
            )
        else:
            raise HTTPException(status_code=401, detail=f"Unsupported token type: {token_type}")

    except (JWTValidationError, ServiceAPIKeyValidationError) as e:
        logger.warning(f"Token validation failed for type {token_type}: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid forwarded token: {e}")
    except Exception as e:
        logger.error(f"Unexpected authentication error for token type {token_type}: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail=f"Authentication failed: {e}")

def require_role(role_name: str):
    """
    FastAPI dependency factory for enforcing role-based access control in the orchestration service.
    """
    async def role_checker(credentials: AuthCredentials = Depends(get_forwarded_user)):
        if not credentials:
            raise HTTPException(status_code=403, detail="Access denied: No valid credentials provided.")
        
        if role_name not in credentials.groups:
            logger.warning(f"Access denied for user '{credentials.username}'. Missing required role: '{role_name}'.")
            raise HTTPException(status_code=403, detail=f"User does not have the required '{role_name}' role.")
        
        return credentials
    return role_checker
