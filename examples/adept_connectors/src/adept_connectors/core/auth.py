"""Authentication manager for ADEPT Connectors.

Supports three strategies:
- api_key: Static Authorization: Bearer sk-... header
- jwt: Static Authorization: Bearer <jwt> header
- password: Keycloak ROPC flow with auto-refresh
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from .config import AdeptConnectorConfig, AuthMethod

logger = logging.getLogger(__name__)


class AuthManager:
    """Manages authentication tokens for ADEPT API requests."""

    def __init__(self, config: AdeptConnectorConfig) -> None:
        self._config = config
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._expires_at: float = 0.0

    async def get_auth_headers(self) -> dict[str, str]:
        """Return Authorization header dict, refreshing token if needed."""
        if self._config.auth_method == AuthMethod.API_KEY:
            return {"Authorization": f"Bearer {self._config.api_key}"}

        if self._config.auth_method == AuthMethod.JWT:
            return {"Authorization": f"Bearer {self._config.jwt_token}"}

        # password (ROPC) — obtain or refresh token
        if self._needs_refresh():
            await self._authenticate()
        return {"Authorization": f"Bearer {self._access_token}"}

    def _needs_refresh(self) -> bool:
        if self._access_token is None:
            return True
        # Refresh if less than 60 seconds remaining
        return time.time() > (self._expires_at - 60)

    async def _authenticate(self) -> None:
        """Authenticate via Keycloak ROPC or refresh token."""
        token_url = (
            f"{self._config.keycloak_url}/realms/{self._config.keycloak_realm}"
            f"/protocol/openid-connect/token"
        )

        if self._refresh_token and not self._access_token_expired_hard():
            data = {
                "grant_type": "refresh_token",
                "client_id": self._config.keycloak_client_id,
                "refresh_token": self._refresh_token,
            }
            logger.debug("Refreshing Keycloak token")
        else:
            data = {
                "grant_type": "password",
                "client_id": self._config.keycloak_client_id,
                "username": self._config.username,
                "password": self._config.password,
                "scope": "openid",
            }
            logger.debug("Authenticating to Keycloak via ROPC")

        async with httpx.AsyncClient(verify=self._config.verify_ssl) as client:
            resp = await client.post(token_url, data=data)
            resp.raise_for_status()
            token_data = resp.json()

        self._access_token = token_data["access_token"]
        self._refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 300)
        self._expires_at = time.time() + expires_in
        logger.debug("Token obtained, expires in %ds", expires_in)

    def _access_token_expired_hard(self) -> bool:
        """True if access token is fully expired (not just near-expiry)."""
        return time.time() > self._expires_at
