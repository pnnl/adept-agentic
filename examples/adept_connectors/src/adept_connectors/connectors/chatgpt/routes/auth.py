"""OAuth2 authorization code flow routes for ChatGPT Actions.

ChatGPT custom GPTs use OAuth2 authorization code grant to authenticate
users. This module proxies the OAuth2 flow to Keycloak:

1. GET /auth/authorize — Redirects ChatGPT to Keycloak's authorize endpoint
2. GET /auth/callback  — Handles Keycloak callback, exchanges code for tokens
3. POST /auth/token    — Token exchange endpoint (ChatGPT calls this)

The flow:
    ChatGPT → GET /auth/authorize → Keycloak login page
    User authenticates → Keycloak → GET /auth/callback?code=...
    Callback exchanges code → stores refresh token → redirects to ChatGPT
    ChatGPT → POST /auth/token → returns access_token
"""

from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory token store keyed by authorization code or refresh token.
# Production deployments should use Redis or a database.
_token_store: dict[str, dict] = {}


class TokenRequest(BaseModel):
    """Request body for POST /auth/token."""

    grant_type: str = Field(..., description="'authorization_code' or 'refresh_token'")
    code: Optional[str] = Field(default=None, description="Authorization code from callback")
    refresh_token: Optional[str] = Field(default=None, description="Refresh token for renewal")
    redirect_uri: Optional[str] = Field(default=None, description="Must match the original redirect_uri")


class TokenResponse(BaseModel):
    """Response body for POST /auth/token."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 300
    refresh_token: Optional[str] = None
    scope: str = "openid"


@router.get("/authorize")
async def authorize(
    request: Request,
    redirect_uri: Optional[str] = None,
    state: Optional[str] = None,
    scope: str = "openid",
) -> RedirectResponse:
    """Redirect to Keycloak's authorization endpoint.

    ChatGPT calls this to start the OAuth2 flow. The user authenticates
    at Keycloak and is redirected back to /auth/callback.
    """
    config = request.app.state.config

    params = {
        "client_id": config.chatgpt_client_id,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": config.effective_redirect_uri,
    }
    if state:
        params["state"] = state

    keycloak_authorize_url = (
        f"{config.keycloak_url}/realms/{config.keycloak_realm}"
        f"/protocol/openid-connect/auth?{urlencode(params)}"
    )

    logger.info("Redirecting to Keycloak authorize: %s", keycloak_authorize_url)
    return RedirectResponse(url=keycloak_authorize_url)


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: Optional[str] = None,
) -> RedirectResponse:
    """Handle Keycloak callback after user authentication.

    Exchanges the authorization code for tokens and stores the
    refresh token. Redirects back to ChatGPT with the code.
    """
    config = request.app.state.config

    # Exchange code for tokens at Keycloak
    token_url = (
        f"{config.keycloak_url}/realms/{config.keycloak_realm}"
        f"/protocol/openid-connect/token"
    )

    data = {
        "grant_type": "authorization_code",
        "client_id": config.chatgpt_client_id,
        "code": code,
        "redirect_uri": config.effective_redirect_uri,
    }
    if config.chatgpt_client_secret:
        data["client_secret"] = config.chatgpt_client_secret

    try:
        async with httpx.AsyncClient(verify=config.verify_ssl) as client:
            resp = await client.post(token_url, data=data, timeout=15.0)
            resp.raise_for_status()
            token_data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Token exchange failed: %d %s", e.response.status_code, e.response.text[:300])
        raise HTTPException(
            status_code=502,
            detail=f"Keycloak token exchange failed: {e.response.status_code}",
        )
    except Exception as e:
        logger.error("Token exchange error: %s", e)
        raise HTTPException(status_code=502, detail="Keycloak unreachable")

    # Store tokens keyed by the authorization code
    _token_store[code] = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data.get("expires_in", 300),
        "obtained_at": time.time(),
    }

    logger.info("OAuth2 callback: code exchanged successfully")

    # ChatGPT expects the callback to include the authorization code
    # in a way it can retrieve. Redirect to ChatGPT's redirect_uri
    # with the code and state.
    # For ChatGPT Actions, the callback URL IS this endpoint, so we
    # return a simple success page. ChatGPT then calls POST /auth/token.
    return RedirectResponse(
        url=f"/auth/success?code={code}" + (f"&state={state}" if state else ""),
        status_code=302,
    )


@router.get("/success")
async def auth_success(code: str, state: Optional[str] = None) -> dict:
    """Simple success page after OAuth2 callback.

    ChatGPT uses this to confirm authentication succeeded, then
    calls POST /auth/token to get the access token.
    """
    return {
        "status": "authenticated",
        "message": "OAuth2 authentication successful. You can close this window.",
    }


@router.post("/token", response_model=TokenResponse)
async def token_exchange(
    request: Request,
    body: TokenRequest,
) -> TokenResponse:
    """Exchange authorization code or refresh token for access token.

    ChatGPT calls this endpoint to obtain and refresh access tokens.
    Supports both ``authorization_code`` and ``refresh_token`` grant types.
    """
    config = request.app.state.config

    if body.grant_type == "authorization_code":
        if not body.code:
            raise HTTPException(status_code=400, detail="code is required")

        stored = _token_store.get(body.code)
        if not stored:
            raise HTTPException(status_code=400, detail="Invalid or expired authorization code")

        # Remove code (single use)
        del _token_store[body.code]

        return TokenResponse(
            access_token=stored["access_token"],
            expires_in=stored["expires_in"],
            refresh_token=stored.get("refresh_token"),
        )

    elif body.grant_type == "refresh_token":
        if not body.refresh_token:
            raise HTTPException(status_code=400, detail="refresh_token is required")

        # Exchange refresh token at Keycloak
        token_url = (
            f"{config.keycloak_url}/realms/{config.keycloak_realm}"
            f"/protocol/openid-connect/token"
        )
        data = {
            "grant_type": "refresh_token",
            "client_id": config.chatgpt_client_id,
            "refresh_token": body.refresh_token,
        }
        if config.chatgpt_client_secret:
            data["client_secret"] = config.chatgpt_client_secret

        try:
            async with httpx.AsyncClient(verify=config.verify_ssl) as client:
                resp = await client.post(token_url, data=data, timeout=15.0)
                resp.raise_for_status()
                token_data = resp.json()
        except Exception as e:
            logger.error("Refresh token exchange failed: %s", e)
            raise HTTPException(status_code=401, detail="Token refresh failed")

        return TokenResponse(
            access_token=token_data["access_token"],
            expires_in=token_data.get("expires_in", 300),
            refresh_token=token_data.get("refresh_token"),
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported grant_type: {body.grant_type}",
        )
