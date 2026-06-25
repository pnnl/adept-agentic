"""
This module handles JWT-based authentication and authorization for the Gateway Registry.

It is adapted from the agent_gateway's auth module but is configured to use
the registry's own service client ID for token validation. It provides
dependencies for enforcing role-based access control on its endpoints.
"""
import os
from typing import Dict, Any, Optional, List
from keycloak import KeycloakOpenID
from jose import jwt
from jose.exceptions import JOSEError
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
import httpx

from ..logger_config import get_logger
from ..core.secrets_manager import get_secret
from ..core.auth import validate_service_api_key, ServiceAPIKeyValidationError, AuthCredentials, JWTValidationError

logger = get_logger(__name__)

# --- Keycloak Configuration ---
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")
# This service uses its own client ID for validation, but the roles checked belong to the CALLING service.
KEYCLOAK_CLIENT_ID = os.getenv("REGISTRY_CLIENT_ID", "gateway-registry-client")

keycloak_openid = KeycloakOpenID(
    server_url=KEYCLOAK_URL,
    realm_name=KEYCLOAK_REALM,
    client_id=KEYCLOAK_CLIENT_ID,
    client_secret_key=get_secret("REGISTRY_CLIENT_SECRET")
)

# --- Authentication Setup ---
AUTH_ENABLED = os.getenv("REGISTRY_AUTH_ENABLED", "true").lower() == "true"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

async def get_public_key():
    """Fetches the public key from Keycloak."""
    async with httpx.AsyncClient() as client:
        well_known = await client.get(f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration")
        well_known.raise_for_status()
        jwks_uri = well_known.json()["jwks_uri"]
        
        jwks_response = await client.get(jwks_uri)
        jwks_response.raise_for_status()
        return jwks_response.json()

async def validate_token(token: str) -> Dict[str, Any]:
    """
    Validates either a JWT token or a service API key.
    Returns a payload dict compatible with the rest of the auth flow.
    """
    if not token:
        raise JWTValidationError("No token provided.")
    
    # First check if it's a service API key
    if token.startswith("sk-service-"):
        try:
            credentials = validate_service_api_key(token)
            # Convert to payload format expected by get_current_user
            logger.debug(f"REGISTRY AUTH: Service API key validation successful for service '{credentials.username}'. Groups: {credentials.groups}")
            return {
                "sub": credentials.user_id,
                "preferred_username": credentials.username,
                "groups": credentials.groups,
                "clientId": credentials.username
            }
        except ServiceAPIKeyValidationError as e:
            logger.debug(f"Not a valid service API key, trying JWT validation: {e}")
            # Fall through to JWT validation
    
    # Check if multi-stack mode is enabled
    from ..core.auth import MULTI_STACK_MODE, validate_jwt_multi_stack
    if MULTI_STACK_MODE:
        # Use multi-stack JWT validation that accepts tokens from trusted Keycloaks
        try:
            import asyncio
            if asyncio.iscoroutinefunction(validate_jwt_multi_stack):
                credentials = await validate_jwt_multi_stack(token)
            else:
                credentials = validate_jwt_multi_stack(token)
            return {
                "sub": credentials.user_id,
                "preferred_username": credentials.username,
                "groups": credentials.groups,
                "clientId": credentials.username
            }
        except Exception as e:
            logger.debug(f"Multi-stack JWT validation failed: {e}")
            # Fall through to standard validation
    
    # Original JWT validation for regular tokens
    return await validate_jwt(token)

async def validate_jwt(token: str) -> Dict[str, Any]:
    """
    Validates a JWT token against Keycloak's public keys using python-jose.
    """
    try:
        jwks = await get_public_key()
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
        if rsa_key:
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience="account",  # Standard audience for Keycloak S2S
                issuer=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
            )
            logger.debug(f"REGISTRY AUTH: JWT validation successful for issuer '{payload.get('iss')}'. Claims: sub={payload.get('sub')}, client_id={payload.get('azp')}, groups={payload.get('groups')}")
            return payload
        raise JWTValidationError("Unable to find a matching key.")
    except JOSEError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise JWTValidationError(f"Token validation error: {e}") from e
    except Exception as e:
        logger.error(f"An unexpected error occurred during JWT validation: {e}", exc_info=True)
        raise JWTValidationError(f"An unexpected error occurred: {e}") from e


async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[AuthCredentials]:
    """
    FastAPI dependency to get the current user or service client's credentials.
    """
    if not AUTH_ENABLED:
        # Create a dummy credentials object for non-auth environments
        return AuthCredentials(user_id="anonymous", username="anonymous", groups=["admin", "gateway-service"], token="")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = await validate_token(token)
        # For service accounts, 'preferred_username' might not exist. Use 'clientId'.
        username = payload.get("preferred_username") or payload.get("clientId", "unknown_service")
        return AuthCredentials(
            user_id=payload.get("sub"),
            username=username,
            groups=payload.get("groups", []),
            token=token
        )
    except JWTValidationError as e:
        raise HTTPException(status_code=401, detail=str(e))

# --- Dependency for Role-Based Access Control (RBAC) ---
def require_role(role_name: str):
    """
    FastAPI dependency factory for enforcing a single required role.
    """
    async def role_checker(credentials: AuthCredentials = Depends(get_current_user)):
        if not credentials or role_name not in credentials.groups:
            logger.warning(f"Access denied for user '{credentials.username}'. Missing required role: '{role_name}'.")
            raise HTTPException(status_code=403, detail=f"User does not have the required '{role_name}' role.")
        return credentials
    return role_checker

def require_any_role(roles: List[str]):
    """
    FastAPI dependency factory for enforcing at least one of a list of roles.
    """
    async def role_checker(credentials: AuthCredentials = Depends(get_current_user)):
        if not credentials or not any(role in credentials.groups for role in roles):
            logger.warning(f"Access denied for user '{credentials.username}'. Missing one of the required roles: {roles}.")
            raise HTTPException(status_code=403, detail=f"User does not have any of the required roles: {roles}.")
        return credentials
    return role_checker