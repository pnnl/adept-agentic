"""
This module provides the Keycloak-specific security integration for the A2A
(Agent-to-Agent) server.

It implements the `CallContextBuilder` interface from the `a2a-sdk` to create
a security context for each incoming A2A request.

Architectural Role:
-   **Security Middleware:** Acts as the primary authentication and authorization
    gate for all incoming A2A traffic. It is the first piece of custom code to
    run when another gateway sends a message.
-   **JWT Validation:** It extracts the Bearer token from the request's
    Authorization header.
-   **Authentication:** Performs synchronous JWT validation using python-jose
    with JWKS keys fetched synchronously via httpx.Client. The A2A SDK's
    CallContextBuilder.build() is called synchronously (no await), so we
    cannot use async auth functions directly.
-   **Authorization:** After authenticating the client, it performs an RBAC check
    to ensure the client belongs to the `gateway-agents` group, authorizing it
    to perform inter-gateway communication.

Why synchronous JWKS fetching:
    The A2A SDK calls `CallContextBuilder.build(request)` without `await`.
    The agent_gateway's auth.py `validate_jwt()` is async (uses httpx.AsyncClient).
    `asyncio.run()` cannot be called from within a running event loop (FastAPI/uvicorn).
    Therefore this module uses `httpx.Client` (synchronous) to fetch JWKS keys
    directly from Keycloak, with a module-level cache to avoid repeated fetches.
"""
import os
import time
from jose import jwt, JWTError
from starlette.requests import Request
from fastapi import HTTPException
import httpx

from a2a.server.apps.jsonrpc import CallContextBuilder
from a2a.server.context import ServerCallContext
from a2a.auth.user import User

from ...auth import AuthCredentials, KEYCLOAK_URL, KEYCLOAK_REALM, KEYCLOAK_EXTERNAL_URL, A2A_TRUSTED_PEER_JWKS_URLS
from ....logger_config import get_logger
from ....core.observability.smart_logger import create_trace


class A2AUser(User):
    """Adapter that wraps AuthCredentials to satisfy the A2A SDK's User interface.

    ServerCallContext.user requires an instance of a2a.auth.user.User (abstract class
    with is_authenticated and user_name properties). Our internal AuthCredentials
    dataclass does not extend User, so this adapter bridges the two.
    """

    def __init__(self, credentials: AuthCredentials):
        self._credentials = credentials

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        return self._credentials.username

    @property
    def credentials(self) -> AuthCredentials:
        """Access the underlying AuthCredentials for groups, token, etc."""
        return self._credentials

logger = get_logger(__name__)

# Module-level JWKS cache: { "keys": [...], "fetched_at": timestamp }
# Refreshed when keys are older than _JWKS_CACHE_TTL_SECONDS or when a kid is not found.
_jwks_cache: dict = {"keys": [], "fetched_at": 0}
_JWKS_CACHE_TTL_SECONDS = 300  # 5 minutes

# JWKS cache metrics for observability
_jwks_cache_metrics: dict = {
    "cache_hits": 0,
    "cache_misses": 0,
    "cache_refreshes_kid_not_found": 0,
    "total_fetch_time_ms": 0.0,
    "last_fetch_time_ms": 0.0,
}


def get_jwks_cache_metrics() -> dict:
    """Return a snapshot of JWKS cache metrics for observability."""
    total = _jwks_cache_metrics["cache_hits"] + _jwks_cache_metrics["cache_misses"]
    hit_ratio = (
        _jwks_cache_metrics["cache_hits"] / total if total > 0 else 0.0
    )
    return {**_jwks_cache_metrics, "hit_ratio": round(hit_ratio, 3)}


def _fetch_jwks_sync(token_kid: str = None) -> list:
    """
    Synchronously fetches JWKS keys from local Keycloak and trusted peers.

    Uses httpx.Client (synchronous) because this is called from a sync context
    (CallContextBuilder.build). Results are cached in the module-level _jwks_cache.

    Args:
        token_kid: Optional key ID to search for in peer JWKS if not found locally.

    Returns:
        List of JWKS key dicts.
    """
    global _jwks_cache

    # Check cache freshness
    cache_age = time.time() - _jwks_cache["fetched_at"]
    if _jwks_cache["keys"] and cache_age < _JWKS_CACHE_TTL_SECONDS:
        # Cache is fresh — but check if the requested kid exists
        if token_kid is None:
            _jwks_cache_metrics["cache_hits"] += 1
            return _jwks_cache["keys"]
        cached_kids = [k.get("kid") for k in _jwks_cache["keys"]]
        if token_kid in cached_kids:
            _jwks_cache_metrics["cache_hits"] += 1
            return _jwks_cache["keys"]
        # kid not found in cache — force refresh below
        _jwks_cache_metrics["cache_refreshes_kid_not_found"] += 1
        logger.info(f"[A2A_AUTH] kid {token_kid} not in cached JWKS ({cached_kids}), refreshing")

    _jwks_cache_metrics["cache_misses"] += 1
    all_keys = []
    fetch_start = time.time()

    try:
        with httpx.Client(verify=False, timeout=10.0) as client:
            # Step 1: Fetch from local Keycloak
            local_jwks_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
            logger.info(f"[A2A_AUTH] Fetching local JWKS (sync): {local_jwks_url}")
            response = client.get(local_jwks_url)
            response.raise_for_status()
            local_keys = response.json().get("keys", [])
            all_keys.extend(local_keys)

            # Step 2: If kid not found locally, try trusted peer endpoints
            if token_kid and A2A_TRUSTED_PEER_JWKS_URLS:
                local_kids = [k.get("kid") for k in local_keys]
                if token_kid not in local_kids:
                    logger.info(
                        f"[A2A_AUTH] kid {token_kid} not in local JWKS ({local_kids}), "
                        f"checking {len(A2A_TRUSTED_PEER_JWKS_URLS)} peer(s)"
                    )
                    for peer_jwks_url in A2A_TRUSTED_PEER_JWKS_URLS:
                        try:
                            logger.info(f"[A2A_AUTH] Fetching peer JWKS (sync): {peer_jwks_url}")
                            peer_response = client.get(peer_jwks_url)
                            peer_response.raise_for_status()
                            peer_keys = peer_response.json().get("keys", [])
                            peer_kids = [k.get("kid") for k in peer_keys]
                            if token_kid in peer_kids:
                                logger.info(f"[A2A_AUTH] Found kid {token_kid} in peer JWKS from {peer_jwks_url}")
                                all_keys.extend(peer_keys)
                                break
                            else:
                                logger.debug(f"[A2A_AUTH] kid {token_kid} not in peer JWKS ({peer_kids})")
                        except Exception as e:
                            logger.warning(f"[A2A_AUTH] Failed to fetch peer JWKS from {peer_jwks_url}: {e}")

    except Exception as e:
        logger.error(f"[A2A_AUTH] Failed to fetch JWKS keys: {e}")
        # Return stale cache if available
        if _jwks_cache["keys"]:
            logger.warning("[A2A_AUTH] Using stale JWKS cache as fallback")
            return _jwks_cache["keys"]
        raise ValueError(f"Cannot fetch JWKS keys from Keycloak: {e}") from e

    # Update cache and metrics
    fetch_ms = (time.time() - fetch_start) * 1000
    _jwks_cache_metrics["total_fetch_time_ms"] += fetch_ms
    _jwks_cache_metrics["last_fetch_time_ms"] = fetch_ms
    _jwks_cache = {"keys": all_keys, "fetched_at": time.time()}
    logger.info(f"[A2A_AUTH] JWKS cache updated: {len(all_keys)} keys, fetch_ms={fetch_ms:.1f}, kids={[k.get('kid') for k in all_keys]}")
    return all_keys


class KeycloakContextBuilder(CallContextBuilder):
    """
    Builds a ServerCallContext for an A2A request and performs Keycloak JWT
    validation and authorization.

    Uses synchronous JWT validation with httpx.Client because the A2A SDK's
    CallContextBuilder interface requires a synchronous build() method.
    """
    def build(self, request: Request) -> ServerCallContext:
        """
        Validates the token from the request and builds the context.

        This method is called synchronously by the A2A server for every
        incoming request.

        Args:
            request: The incoming Starlette request object.

        Returns:
            A ServerCallContext containing the authenticated credentials.

        Raises:
            Exception: If authentication or authorization fails.
        """
        build_start = time.time()

        with create_trace(logger, "a2a_auth") as t:
            # 1. Extract the token from the header
            with t.span("token_extraction") as s:
                auth_header = request.headers.get("Authorization")
                if not auth_header or not auth_header.startswith("Bearer "):
                    raise HTTPException(status_code=401, detail="Not authenticated")
                token = auth_header.split(" ")[1]
                extract_ms = s.end()

            # 2. Validate the JWT synchronously
            with t.span("jwt_validation") as s:
                try:
                    credentials = self._validate_jwt_sync(token)
                except Exception as e:
                    raise Exception(f"Auth error: {e}") from e
                if not credentials:
                    raise Exception("Authentication failed, no credentials returned.")
                validation_ms = s.end()

            # 3. Perform the authorization check
            with t.span("authorization_check") as s:
                required_group = "gateway-agents"
                if required_group not in credentials.groups:
                    raise Exception(
                        f"Client '{credentials.username}' is not authorized for "
                        f"inter-gateway communication (missing '{required_group}' group)."
                    )
                auth_check_ms = s.end()

        build_ms = (time.time() - build_start) * 1000
        logger.info(
            f"[A2A_AUTH] Authenticated: user={credentials.username}, "
            f"groups={credentials.groups}, auth_type=jwt, "
            f"validation_ms={validation_ms:.1f}, build_ms={build_ms:.1f}"
        )

        # 4. Build and return the context
        # ServerCallContext.user requires a2a.auth.user.User (not our AuthCredentials)
        a2a_user = A2AUser(credentials)
        auth_timing = {
            "extract_ms": round(extract_ms, 1),
            "validation_ms": round(validation_ms, 1),
            "auth_check_ms": round(auth_check_ms, 1),
            "build_ms": round(build_ms, 1),
        }
        return ServerCallContext(
            user=a2a_user,
            state={
                "auth": credentials.token,
                "username": credentials.username,
                "groups": credentials.groups,
                "auth_timing": auth_timing,
            },
        )

    def _validate_jwt_sync(self, token: str) -> AuthCredentials:
        """
        Synchronous JWT validation using python-jose and synchronously-fetched
        JWKS keys.
        """
        if not token:
            raise ValueError("No token provided.")

        try:
            unverified_header = jwt.get_unverified_header(token)
            unverified_claims = jwt.get_unverified_claims(token)
        except JWTError as e:
            raise ValueError(f"Invalid JWT format: {e}") from e

        token_issuer = unverified_claims.get("iss")
        if not token_issuer:
            raise ValueError("Token is missing the 'iss' (issuer) claim.")

        # Define valid issuers (matches auth.py validate_jwt logic)
        valid_issuers = [
            f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
            f"{KEYCLOAK_EXTERNAL_URL}/realms/{KEYCLOAK_REALM}",
            f"http://api.agentic.local/realms/{KEYCLOAK_REALM}",
            f"https://api.agentic.local/realms/{KEYCLOAK_REALM}",
            f"http://localhost:8180/realms/{KEYCLOAK_REALM}",
        ]

        # Also accept peer Keycloak issuers (for cross-gateway A2A tokens)
        for peer_url in A2A_TRUSTED_PEER_JWKS_URLS:
            if "/protocol/openid-connect/certs" in peer_url:
                peer_issuer = peer_url.replace("/protocol/openid-connect/certs", "")
                if peer_issuer not in valid_issuers:
                    valid_issuers.append(peer_issuer)

        if token_issuer not in valid_issuers:
            raise ValueError(
                f"Invalid issuer. Expected one of {valid_issuers}, "
                f"but got {token_issuer}."
            )

        # Fetch JWKS keys (sync, with cache)
        token_kid = unverified_header.get("kid")
        jwks_keys = _fetch_jwks_sync(token_kid=token_kid)

        if not jwks_keys:
            raise ValueError("No JWKS keys available from Keycloak.")

        # Find matching key
        rsa_key = {}
        for key in jwks_keys:
            if key.get("kid") == token_kid:
                rsa_key = key
                break

        if not rsa_key:
            raise ValueError(
                f"No matching JWKS key found for kid={token_kid}. "
                f"Available kids: {[k.get('kid') for k in jwks_keys]}"
            )

        # Verify the token (matches auth.py: verify_aud=False, manual audience check)
        try:
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=None,
                issuer=token_issuer,
                options={"verify_aud": False},
            )
        except JWTError as e:
            raise ValueError(f"JWT verification failed: {e}") from e

        # Extract user info
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Token is missing the 'sub' (subject) claim.")

        username = payload.get("preferred_username") or payload.get("clientId", "unknown_user")
        groups = payload.get("groups", [])

        return AuthCredentials(
            user_id=user_id,
            username=username,
            groups=groups,
            token=token,
            auth_type="jwt",
        )
