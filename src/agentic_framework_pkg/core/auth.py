"""
Core Authentication & Authorization Module

Centralizes JWT validation, service API key validation, user context extraction, 
and role-based access control across all services in the framework.

This module replaces the duplicated auth logic in:
- agent_gateway/auth.py
- orchestration_service/auth.py

And provides a unified authentication system that can be extended with:
- Azure Entra ID integration
- Social IDP support
- MFA validation hooks
- Enhanced authorization policies
"""
import os
import hashlib
import hmac
import json
from typing import Dict, Any, Optional, List, Union, Callable
from keycloak import KeycloakOpenID
from jose import jwt
from jose.exceptions import JOSEError
from pydantic import BaseModel
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
import httpx

from .user_context import UserContext, extract_user_context_from_headers, create_forwarding_headers
from .service_token_manager import BOOTSTRAP_TOKENS
from .secrets_manager import get_secret
from ..logger_config import get_logger

logger = get_logger(__name__)

# --- Configuration ---
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
KEYCLOAK_EXTERNAL_URL = os.getenv("KEYCLOAK_EXTERNAL_URL", KEYCLOAK_URL)
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID")

# Multi-stack configuration for trusted Keycloak instances
MULTI_STACK_MODE = os.getenv("MULTI_STACK_MODE", "false").lower() == "true"
TRUSTED_KEYCLOAK_URLS = os.getenv("TRUSTED_KEYCLOAK_URLS", "").split(",") if os.getenv("TRUSTED_KEYCLOAK_URLS") else []

# A2A peer JWKS endpoints for cross-VM token validation
# When VMs use the same internal Keycloak hostname (e.g., http://keycloak:8180),
# tokens from peer VMs have issuer URLs that resolve to LOCAL Keycloak.
# This list provides peer JWKS endpoints to check when kid is not found locally.
_raw_peer_jwks = os.getenv("A2A_TRUSTED_PEER_JWKS_URLS", "")
A2A_TRUSTED_PEER_JWKS_URLS = [url.strip() for url in _raw_peer_jwks.split(",") if url.strip()]

# --- Helper Functions ---
def _format_public_key(key_data: str) -> str:
    """
    Format a public key to ensure it has proper PEM headers and formatting.
    
    Args:
        key_data: Raw public key data (may or may not have PEM headers)
        
    Returns:
        Properly formatted PEM public key
    """
    if isinstance(key_data, bytes):
        key_data = key_data.decode('utf-8')
    
    # Remove any existing PEM headers/footers and whitespace
    key_data = key_data.strip()
    
    # Remove PEM headers if present
    if "-----BEGIN" in key_data:
        # Extract just the key content between headers
        lines = key_data.split('\n')
        key_lines = []
        in_key = False
        for line in lines:
            if "-----BEGIN" in line:
                in_key = True
                continue
            elif "-----END" in line:
                in_key = False
                continue
            elif in_key:
                key_lines.append(line.strip())
        key_data = ''.join(key_lines)
    
    # Remove all whitespace and newlines
    key_data = key_data.replace('\n', '').replace('\r', '').replace(' ', '').replace('\t', '')
    
    # Add proper PEM formatting with 64-character lines
    formatted_lines = []
    for i in range(0, len(key_data), 64):
        formatted_lines.append(key_data[i:i+64])
    
    # Construct proper PEM format
    pem_key = "-----BEGIN PUBLIC KEY-----\n"
    pem_key += '\n'.join(formatted_lines)
    pem_key += "\n-----END PUBLIC KEY-----"
    
    return pem_key

def _extract_user_from_token(decoded_token: dict, original_token: str) -> "AuthCredentials":
    """
    Extract user information from a decoded JWT token.
    
    Args:
        decoded_token: The decoded JWT payload
        original_token: The original token string
        
    Returns:
        AuthCredentials with user information
    """
    # Validate audience manually if present
    token_audience = decoded_token.get("aud")
    if token_audience:
        valid_audiences = ["account", KEYCLOAK_CLIENT_ID]
        if isinstance(token_audience, str):
            if token_audience not in valid_audiences:
                raise JWTValidationError(f"Invalid audience: {token_audience}")
        elif isinstance(token_audience, list):
            if not any(aud in valid_audiences for aud in token_audience):
                raise JWTValidationError(f"Invalid audience: {token_audience}")
    
    # Extract user information
    user_id = decoded_token.get("sub")
    username = decoded_token.get("preferred_username") or decoded_token.get("clientId")
    groups = decoded_token.get("groups", [])
    
    if not user_id:
        raise JWTValidationError("Token missing required user ID (sub claim)")
    if not username:
        username = f"user-{user_id}"  # Fallback username
    
    return AuthCredentials(
        user_id=user_id,
        username=username,
        groups=groups,
        token=original_token,
        auth_type="jwt"
    )

# --- Token Detection ---
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

# --- Exceptions ---
class AuthenticationError(Exception):
    """Base authentication exception."""
    pass

class JWTValidationError(AuthenticationError):
    """JWT validation specific exception."""
    pass

class ServiceAPIKeyValidationError(AuthenticationError):
    """Service API key validation specific exception."""
    pass

# --- Models ---
class AuthCredentials(BaseModel):
    """Unified model for storing validated user credentials across all services."""
    user_id: str
    username: str
    groups: List[str]
    token: str
    auth_type: str = "jwt"  # "jwt", "service_api_key", or "api_key"
    
    def to_user_context(self) -> UserContext:
        """Convert to UserContext for service communication."""
        return UserContext(
            user_id=self.user_id,
            username=self.username,
            groups=self.groups
        )
    
    def has_group(self, group_name: str) -> bool:
        """Check if user belongs to a specific group."""
        return group_name in self.groups
    
    def has_any_group(self, group_names: List[str]) -> bool:
        """Check if user belongs to any of the specified groups."""
        return any(group in self.groups for group in group_names)

# --- Keycloak Client ---
def get_keycloak_client() -> KeycloakOpenID:
    """Get configured Keycloak OpenID client."""
    return KeycloakOpenID(
        server_url=KEYCLOAK_URL,
        realm_name=KEYCLOAK_REALM,
        client_id=KEYCLOAK_CLIENT_ID,
    )

# --- Service API Key Management ---
def load_service_api_keys() -> Dict[str, Any]:
    """
    Load service API keys from secure credentials.
    
    Returns a dictionary mapping API keys to their configuration:
    {
        "sk-service-...": {
            "client_id": "...",
            "groups": [...],
            "user_id": "...",
            "username": "..."
        }
    }
    """
    service_keys_config = get_secret("SERVICE_API_KEYS_CONFIG")
    if not service_keys_config:
        logger.warning("SERVICE_API_KEYS_CONFIG not found. Service API key authentication disabled.")
        return {}
    
    try:
        service_keys = json.loads(service_keys_config)

        # Bootstrap tokens are now loaded from BOOTSTRAP_SERVICE_TOKENS secret
        # via service_token_manager.BOOTSTRAP_TOKENS — no longer duplicated here.
        service_keys.update(BOOTSTRAP_TOKENS)
        logger.info(f"Loaded {len(service_keys)} service API keys (including {len(BOOTSTRAP_TOKENS)} bootstrap tokens)")
        return service_keys
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse SERVICE_API_KEYS_CONFIG JSON: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading service API keys: {e}")
        return {}

# Cache for loaded service keys
_service_keys_cache: Optional[Dict[str, Any]] = None

def get_service_api_keys() -> Dict[str, Any]:
    """Get cached service API keys, loading if necessary."""
    global _service_keys_cache
    if _service_keys_cache is None:
        _service_keys_cache = load_service_api_keys()
    return _service_keys_cache

# --- Multi-Stack JWT Validation ---
async def validate_jwt_multi_stack(token: str) -> AuthCredentials:
    """
    Validate a JWT token from multiple trusted Keycloak instances.
    Used in multi-stack deployments for A2A communication.
    
    Args:
        token: JWT token string
        
    Returns:
        AuthCredentials with user information
        
    Raises:
        JWTValidationError: If token validation fails
    """
    if not token:
        raise JWTValidationError("No token provided.")
    
    try:
        unverified_header = jwt.get_unverified_header(token)
        unverified_claims = jwt.get_unverified_claims(token)
        
        token_issuer = unverified_claims.get("iss")
        if not token_issuer:
            raise JWTValidationError("Token is missing the 'iss' (issuer) claim.")
        
        # Extract base Keycloak URL from issuer
        # Format: http://keycloak:8180/realms/master -> http://keycloak:8180
        issuer_parts = token_issuer.split("/realms/")
        if len(issuer_parts) == 2:
            issuer_base = issuer_parts[0]
            realm = issuer_parts[1]
        else:
            issuer_base = token_issuer
            realm = KEYCLOAK_REALM
        
        # Check if this is from a trusted Keycloak
        is_trusted = False

        # Trust our own Keycloak
        if issuer_base == KEYCLOAK_URL or issuer_base == KEYCLOAK_EXTERNAL_URL:
            is_trusted = True

        # Trust nginx_proxy (JupyterLab acquires tokens via frontend_net proxy)
        if issuer_base == "https://nginx_proxy":
            is_trusted = True

        # Check against trusted Keycloak URLs list
        for trusted_url in TRUSTED_KEYCLOAK_URLS:
            if trusted_url and (issuer_base == trusted_url or trusted_url in issuer_base):
                is_trusted = True
                break
        
        if not is_trusted:
            logger.warning(f"Untrusted token issuer: {token_issuer}")
            logger.warning(f"Trusted Keycloaks: {[KEYCLOAK_URL, KEYCLOAK_EXTERNAL_URL] + TRUSTED_KEYCLOAK_URLS}")
            raise JWTValidationError(f"Token from untrusted issuer: {token_issuer}")
        
        # Fetch JWKS from the token's issuer
        jwks_uri = f"{issuer_base}/realms/{realm}/protocol/openid-connect/certs"
        
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            jwks_response = await client.get(jwks_uri)
            jwks_response.raise_for_status()
            jwks = jwks_response.json()
        
        # Find the matching key
        rsa_key = {}
        for key in jwks.get("keys", []):
            if key.get("kid") == unverified_header.get("kid"):
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key.get("use", "sig"),
                    "n": key["n"],
                    "e": key["e"],
                }
                break
        
        # Peer JWKS fallback: If kid not found in issuer's JWKS,
        # check trusted peer JWKS endpoints. This handles cross-VM A2A delegation
        # where both VMs use the same internal Keycloak hostname (e.g., http://keycloak:8180)
        # so the issuer URL resolves to LOCAL Keycloak which doesn't have peer's signing keys.
        if not rsa_key:
            token_kid = unverified_header.get("kid")
            if token_kid and A2A_TRUSTED_PEER_JWKS_URLS:
                logger.info(
                    f"[A2A_USER_TOKEN] kid {token_kid} not in issuer JWKS from {jwks_uri}, "
                    f"checking {len(A2A_TRUSTED_PEER_JWKS_URLS)} peer endpoint(s)"
                )
                for peer_jwks_url in A2A_TRUSTED_PEER_JWKS_URLS:
                    try:
                        # verify=False: peer JWKS URLs traverse internal mesh with
                        # self-signed certs (same pattern as keycloak_context_builder.py:130
                        # and local JWKS fetch above). External-facing endpoints use CA certs.
                        async with httpx.AsyncClient(verify=False, timeout=10.0) as peer_client:
                            peer_resp = await peer_client.get(peer_jwks_url)
                            peer_resp.raise_for_status()
                            peer_jwks = peer_resp.json()
                        for key in peer_jwks.get("keys", []):
                            if key.get("kid") == token_kid:
                                rsa_key = {
                                    "kty": key["kty"],
                                    "kid": key["kid"],
                                    "use": key.get("use", "sig"),
                                    "n": key["n"],
                                    "e": key["e"],
                                }
                                logger.info(f"[A2A_USER_TOKEN] Found kid {token_kid} in peer JWKS: {peer_jwks_url}")
                                break
                        if rsa_key:
                            break
                    except Exception as e:
                        logger.warning(f"[A2A_USER_TOKEN] Failed to fetch peer JWKS from {peer_jwks_url}: {e}")

        if not rsa_key:
            raise JWTValidationError("Unable to find a matching key.")

        # Decode and validate the JWT
        decoded_token = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            issuer=token_issuer,
            options={"verify_aud": False}  # Don't verify audience for cross-stack tokens
        )
        
        logger.info(f"Successfully validated token from {token_issuer}")
        
        # Extract user information
        return _extract_user_from_token(decoded_token, token)
        
    except JOSEError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise JWTValidationError(f"Token validation error: {e}") from e
    except Exception as e:
        logger.error(f"Unexpected error during JWT validation: {e}", exc_info=True)
        raise JWTValidationError(f"Token validation failed: {e}")

# --- JWT Validation ---
def validate_jwt_token(token: str) -> AuthCredentials:
    """
    Validate a JWT token and extract user credentials.
    
    Args:
        token: JWT token string
        
    Returns:
        AuthCredentials with user information
        
    Raises:
        JWTValidationError: If token validation fails
    """
    try:
        keycloak_openid = get_keycloak_client()
        
        # Get Keycloak public key with multiple format handling
        public_key = None
        key_error_msg = None
        
        # Method 1: Try getting public key from Keycloak client
        try:
            raw_key = keycloak_openid.public_key()
            if raw_key:
                # Format the key properly
                public_key = _format_public_key(raw_key)
                logger.debug("Successfully retrieved public key from Keycloak client")
        except Exception as e:
            key_error_msg = str(e)
            logger.warning(f"Failed to get public key from Keycloak client: {e}")
        
        # Method 2: Try getting from environment variable
        if not public_key:
            public_key_env = os.getenv("KEYCLOAK_PUBLIC_KEY", "")
            if public_key_env:
                public_key = _format_public_key(public_key_env)
                logger.debug("Using public key from environment variable")
            
        # Method 3: Try fetching from Keycloak JWKS endpoint
        if not public_key:
            try:
                jwks_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(jwks_url)
                    if response.status_code == 200:
                        # For JWKS, we'll let jose handle it directly
                        jwks = response.json()
                        # Try decoding with JWKS
                        try:
                            decoded_token = jwt.decode(
                                token,
                                jwks,
                                algorithms=["RS256"],
                                options={"verify_aud": False}
                            )
                            # If successful, extract user info and return
                            return _extract_user_from_token(decoded_token, token)
                        except Exception as jwks_error:
                            logger.warning(f"JWKS decode failed: {jwks_error}")
            except Exception as fetch_error:
                logger.warning(f"Failed to fetch JWKS: {fetch_error}")
        
        if not public_key:
            raise JWTValidationError(
                f"Unable to obtain public key for JWT validation. "
                f"Original error: {key_error_msg or 'No public key sources available'}"
            )
        
        # Validate and decode token with the formatted public key
        try:
            decoded_token = jwt.decode(
                token, 
                public_key, 
                algorithms=["RS256"],
                audience="account",
                options={"verify_aud": False}  # We'll validate audience manually
            )
        except JOSEError as decode_error:
            # Try with different audience options
            try:
                decoded_token = jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    options={"verify_aud": False}
                )
            except Exception:
                raise JWTValidationError(f"Token decode failed: {decode_error}")
        
        # Extract user information and return
        return _extract_user_from_token(decoded_token, token)
        
    except JWTValidationError:
        raise  # Re-raise JWT validation errors as-is
    except JOSEError as e:
        # Handle malformed public key specifically
        if "Could not deserialize key data" in str(e):
            raise JWTValidationError("JWT validation failed: Invalid public key format. Ensure KEYCLOAK_PUBLIC_KEY is properly formatted as PEM.") from e
        raise JWTValidationError(f"JWT validation failed: {e}") from e
    except Exception as e:
        raise JWTValidationError(f"Unexpected error during token validation: {e}") from e

# --- Service API Key Validation ---
def validate_service_api_key(api_key: str) -> AuthCredentials:
    """
    Validate a service API key and extract service credentials.
    
    Args:
        api_key: Service API key string
        
    Returns:
        AuthCredentials with service information
        
    Raises:
        ServiceAPIKeyValidationError: If key validation fails
    """
    try:
        service_keys = get_service_api_keys()
        
        if api_key not in service_keys:
            raise ServiceAPIKeyValidationError("Invalid service API key")
        
        key_config = service_keys[api_key]
        
        return AuthCredentials(
            user_id=key_config["user_id"],
            username=key_config["username"],
            groups=key_config["groups"],
            token=api_key,
            auth_type="service_api_key"
        )
        
    except KeyError as e:
        raise ServiceAPIKeyValidationError(f"Service API key configuration missing field: {e}") from e
    except Exception as e:
        raise ServiceAPIKeyValidationError(f"Error validating service API key: {e}") from e

# --- Unified Token Validation ---
def validate_authorization_header(authorization: str) -> AuthCredentials:
    """
    Validate authorization header supporting both JWT and service API keys.
    
    Args:
        authorization: Authorization header value (e.g., "Bearer token...")
        
    Returns:
        AuthCredentials with user/service information
        
    Raises:
        AuthenticationError: If validation fails
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("Missing or invalid authorization header")
    
    token = authorization.replace("Bearer ", "")
    
    # Try service API key first (they have specific prefixes)
    if token.startswith("sk-service-"):
        return validate_service_api_key(token)
    
    # Try JWT validation
    try:
        return validate_jwt_token(token)
    except JWTValidationError:
        # If JWT fails, try as service API key (fallback)
        try:
            return validate_service_api_key(token)
        except ServiceAPIKeyValidationError:
            raise AuthenticationError("Invalid token: not a valid JWT or service API key")

# --- FastAPI Dependencies ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> AuthCredentials:
    """
    FastAPI dependency to get current authenticated user/service.
    
    Supports multiple authentication methods:
    1. JWT tokens from Keycloak
    2. Service API keys
    3. Forwarded user context from other services
    
    Args:
        request: FastAPI request object
        token: OAuth2 token (optional)
        credentials: HTTP Bearer credentials (optional)
        
    Returns:
        AuthCredentials for the authenticated user/service
        
    Raises:
        HTTPException: If authentication fails
    """
    # Try forwarded user context first (for service-to-service calls)
    user_context = extract_user_context_from_headers(dict(request.headers))
    if user_context:
        return AuthCredentials(
            user_id=user_context.user_id,
            username=user_context.username,
            groups=user_context.groups,
            token="forwarded",
            auth_type="forwarded_context"
        )
    
    # Try authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header:
        try:
            return validate_authorization_header(auth_header)
        except AuthenticationError as e:
            raise HTTPException(status_code=401, detail=str(e))
    
    # Try token from OAuth2 scheme
    if token:
        try:
            return validate_jwt_token(token)
        except JWTValidationError as e:
            raise HTTPException(status_code=401, detail=str(e))
    
    # Try credentials from Bearer scheme
    if credentials:
        try:
            return validate_authorization_header(f"Bearer {credentials.credentials}")
        except AuthenticationError as e:
            raise HTTPException(status_code=401, detail=str(e))
    
    raise HTTPException(status_code=401, detail="Authentication required")

# --- Authorization Decorators ---
def require_role(required_role: str) -> Callable:
    """
    FastAPI dependency factory that requires a specific role/group.
    
    Args:
        required_role: Required group name
        
    Returns:
        FastAPI dependency function
    """
    def dependency(current_user: AuthCredentials = Depends(get_current_user)) -> AuthCredentials:
        if not current_user.has_group(required_role):
            raise HTTPException(
                status_code=403, 
                detail=f"Access denied. Required role: {required_role}"
            )
        return current_user
    
    return dependency

def require_any_role(required_roles: List[str]) -> Callable:
    """
    FastAPI dependency factory that requires any of the specified roles/groups.
    
    Args:
        required_roles: List of acceptable group names
        
    Returns:
        FastAPI dependency function
    """
    def dependency(current_user: AuthCredentials = Depends(get_current_user)) -> AuthCredentials:
        if not current_user.has_any_group(required_roles):
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required roles (any): {', '.join(required_roles)}"
            )
        return current_user
    
    return dependency

# --- Future Extensions ---
class AzureEntraIDAuth:
    """
    Placeholder for Azure Entra ID integration.
    
    Future implementation will include:
    - OIDC federation with Azure Entra ID
    - Social login capabilities
    - Conditional access policy enforcement
    - MFA validation
    """
    pass

class SocialIDPAuth:
    """
    Placeholder for social IDP integrations.
    
    Future implementation will include:
    - Google OAuth
    - GitHub OAuth
    - Microsoft OAuth
    - Generic OIDC providers
    """
    pass