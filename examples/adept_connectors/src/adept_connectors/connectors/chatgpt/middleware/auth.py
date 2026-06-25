"""Bearer token validation middleware for ChatGPT Actions.

ChatGPT sends an ``Authorization: Bearer <token>`` header on every
request after completing the OAuth2 flow. This middleware validates
the token against Keycloak's JWKS endpoint before allowing the
request through.

For development/testing, the ``CHATGPT_AUTH_DISABLED=true`` env var
bypasses validation entirely.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Paths that skip authentication
_PUBLIC_PATHS = frozenset({
    "/health",
    "/auth/authorize",
    "/auth/callback",
    "/auth/token",
    "/.well-known/openapi.yaml",
    "/openapi.json",
    "/docs",
    "/redoc",
})


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Validates Bearer tokens via Keycloak token introspection.

    Uses the ``userinfo`` endpoint for lightweight validation instead
    of full JWT signature verification (avoids JWKS key management).

    Args:
        app: ASGI application.
        keycloak_url: Keycloak server URL.
        realm: Keycloak realm name.
        verify_ssl: Whether to verify TLS certificates.
    """

    def __init__(
        self,
        app,
        keycloak_url: str = "http://localhost:8180",
        realm: str = "master",
        verify_ssl: bool = True,
    ) -> None:
        super().__init__(app)
        self._userinfo_url = (
            f"{keycloak_url}/realms/{realm}/protocol/openid-connect/userinfo"
        )
        self._verify_ssl = verify_ssl
        # Simple cache: token → (userinfo_dict, expiry_time)
        self._cache: dict[str, tuple[dict, float]] = {}
        self._cache_ttl = 60  # seconds

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip auth for public paths
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        # Dev/test bypass
        if os.getenv("CHATGPT_AUTH_DISABLED", "").lower() in ("true", "1", "yes"):
            request.state.user = {"sub": "dev-user", "preferred_username": "developer"}
            return await call_next(request)

        # Extract bearer token
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or invalid Authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[7:]

        # Check cache
        userinfo = self._get_cached(token)
        if userinfo is None:
            userinfo = await self._validate_token(token)
            if userinfo is None:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid or expired token"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            self._cache[token] = (userinfo, time.time() + self._cache_ttl)

        # Attach user info to request state
        request.state.user = userinfo
        return await call_next(request)

    async def _validate_token(self, token: str) -> Optional[dict]:
        """Validate token via Keycloak userinfo endpoint."""
        try:
            async with httpx.AsyncClient(verify=self._verify_ssl) as client:
                resp = await client.get(
                    self._userinfo_url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    return resp.json()
                logger.warning(
                    "Token validation failed: %d %s", resp.status_code, resp.text[:200]
                )
                return None
        except Exception as e:
            logger.error("Token validation error: %s", e)
            return None

    def _get_cached(self, token: str) -> Optional[dict]:
        """Get cached userinfo if still valid."""
        entry = self._cache.get(token)
        if entry is None:
            return None
        userinfo, expiry = entry
        if time.time() > expiry:
            del self._cache[token]
            return None
        return userinfo
