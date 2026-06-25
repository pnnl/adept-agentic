"""
Globus Token Exchange
=====================

Exchanges ADEPT Keycloak JWTs for Globus access tokens,
enabling the orchestration service to call Globus APIs
(Transfer, Search, Compute, Flows, Groups) on behalf of users.

Two exchange methods:
1. Keycloak Token Exchange (RFC 8693) -- preferred, requires Keycloak config
2. Globus Client Credentials -- fallback, uses stored client credentials

Usage:
    from agentic_framework_pkg.core.globus_token_exchange import (
        exchange_for_globus_token,
        GlobusTokenResult,
    )

    result = await exchange_for_globus_token(
        keycloak_jwt="eyJ...",
        target_scopes="urn:globus:auth:scope:transfer.api.globus.org:all",
    )
    if result:
        # Use result.access_token with Globus SDK
        from globus_sdk import TransferClient, AccessTokenAuthorizer
        tc = TransferClient(authorizer=AccessTokenAuthorizer(result.access_token))
"""

import os
import time
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Globus Auth configuration
GLOBUS_CLIENT_ID = os.getenv("GLOBUS_CLIENT_ID", "")
GLOBUS_CLIENT_SECRET = os.getenv("GLOBUS_CLIENT_SECRET", "")
GLOBUS_AUTH_URL = os.getenv("GLOBUS_AUTH_URL", "https://auth.globus.org")
GLOBUS_ENABLED = os.getenv("GLOBUS_ENABLED", "false").lower() in ("true", "1", "yes")

# Keycloak configuration (for token exchange method)
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8180")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")


@dataclass
class GlobusTokenResult:
    """Result of a Globus token exchange."""

    access_token: str
    expires_in: int
    token_type: str
    scope: str
    resource_server: str = ""
    expires_at: float = 0.0

    def __post_init__(self):
        if not self.expires_at:
            self.expires_at = time.time() + self.expires_in

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - 30  # 30s buffer


async def exchange_for_globus_token(
    keycloak_jwt: str,
    target_scopes: str = "urn:globus:auth:scope:transfer.api.globus.org:all",
) -> Optional[GlobusTokenResult]:
    """
    Exchange an ADEPT Keycloak JWT for a Globus access token.

    Tries Keycloak token exchange first, then falls back to direct
    Globus client credentials exchange if available.

    Args:
        keycloak_jwt: Valid ADEPT Keycloak JWT
        target_scopes: Globus API scopes to request

    Returns:
        GlobusTokenResult with access token, or None on failure
    """
    if not GLOBUS_ENABLED:
        logger.debug("Globus integration disabled (GLOBUS_ENABLED=false)")
        return None

    if not GLOBUS_CLIENT_ID or not GLOBUS_CLIENT_SECRET:
        logger.warning(
            "Globus credentials not configured "
            "(GLOBUS_CLIENT_ID/GLOBUS_CLIENT_SECRET)"
        )
        return None

    # Method 1: Keycloak Token Exchange (RFC 8693)
    result = await _keycloak_token_exchange(keycloak_jwt, target_scopes)
    if result:
        return result

    # Method 2: Direct Globus client credentials (service-level, no user context)
    result = await _globus_client_credentials(target_scopes)
    if result:
        return result

    logger.warning("All Globus token exchange methods failed")
    return None


async def _keycloak_token_exchange(
    subject_token: str,
    target_scopes: str,
) -> Optional[GlobusTokenResult]:
    """
    Exchange token via Keycloak's RFC 8693 token exchange endpoint.

    This requires:
    - Keycloak has Globus configured as an external IdP
    - The requesting client has token-exchange permission
    """
    token_url = (
        f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"
        f"/protocol/openid-connect/token"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "subject_token": subject_token,
                    "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    "requested_issuer": "globus",
                    "audience": target_scopes,
                    "client_id": GLOBUS_CLIENT_ID,
                    "client_secret": GLOBUS_CLIENT_SECRET,
                },
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "Keycloak token exchange successful "
                    f"(scope={data.get('scope', 'unknown')})"
                )
                return GlobusTokenResult(
                    access_token=data["access_token"],
                    expires_in=data.get("expires_in", 3600),
                    token_type=data.get("token_type", "Bearer"),
                    scope=data.get("scope", target_scopes),
                )
            else:
                logger.debug(
                    "Keycloak token exchange failed: "
                    f"{response.status_code} {response.text[:200]}"
                )
                return None
    except Exception as e:
        logger.debug(f"Keycloak token exchange error: {e}")
        return None


async def _globus_client_credentials(
    target_scopes: str,
) -> Optional[GlobusTokenResult]:
    """
    Get a Globus access token using client credentials grant.

    This provides service-level access (no user identity).
    Use as fallback when user-level token exchange is not available.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{GLOBUS_AUTH_URL}/v2/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": GLOBUS_CLIENT_ID,
                    "client_secret": GLOBUS_CLIENT_SECRET,
                    "scope": target_scopes,
                },
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "Globus client credentials grant successful "
                    f"(scope={data.get('scope', 'unknown')})"
                )
                return GlobusTokenResult(
                    access_token=data["access_token"],
                    expires_in=data.get("expires_in", 3600),
                    token_type=data.get("token_type", "Bearer"),
                    scope=data.get("scope", target_scopes),
                    resource_server=data.get("resource_server", ""),
                )
            else:
                logger.debug(
                    "Globus client credentials failed: "
                    f"{response.status_code} {response.text[:200]}"
                )
                return None
    except Exception as e:
        logger.debug(f"Globus client credentials error: {e}")
        return None
