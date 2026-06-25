"""
This module provides the OpenAI-compatible `/v1/models` endpoint.

Architectural Role (in Three-Tier Model):
-   **Tier 1 (Ingress):** This router acts as the ingress point for model
    listing and retrieval requests.
-   **Proxy to Orchestrator:** It proxies all requests directly to the
    `orchestration_service`, which is the single source of truth for what agent
    "models" (configurations) are available. This keeps the gateway stateless
    and ensures a consistent view of available agents.
"""
from fastapi import APIRouter, Request, Depends

from ....logger_config import get_logger
from .assistants import proxy_request # Re-use the proxy function
from ...auth import AuthCredentials, get_current_user

router = APIRouter()
logger = get_logger(__name__)

@router.get("", summary="List Available Agent Models")
async def list_models(request: Request, user: AuthCredentials = Depends(get_current_user)):
    """
    Lists all available agent model configurations by proxying the request
    to the orchestration service.
    """
    logger.info("[AGENT_GATEWAY] Handling GET /v1/models/")
    return await proxy_request(request, user)

# IMPORTANT: Register specific routes BEFORE greedy :path route (Session 48 fix)
@router.get("/{model_id}/tools", summary="List Tools for a specific agent model")
async def get_tools_for_model(request: Request, model_id: str, user: AuthCredentials = Depends(get_current_user)):
    """
    Retrieves the list of tools for a specific agent model configuration by proxying
    the request to the orchestration service.

    Note: Registered before /{model_id:path} to ensure /tools suffix is matched correctly.
    Does NOT use :path parameter - that's only for the greedy route at the end.
    """
    logger.info(f"[AGENT_GATEWAY] Handling GET /v1/models/{model_id}/tools")
    return await proxy_request(request, user)

@router.get("/{model_id:path}", summary="Retrieve a specific agent model")
async def get_model(request: Request, model_id: str, user: AuthCredentials = Depends(get_current_user)):
    """
    Retrieves details for a specific agent model configuration by proxying
    the request to the orchestration service.

    Note: Uses :path to support model IDs with slashes (e.g., adept/scientific-agent-v1).
    Registered AFTER /{model_id}/tools to avoid catching /tools paths.
    """
    logger.info(f"[AGENT_GATEWAY] Handling GET /v1/models/{model_id}")
    return await proxy_request(request, user)
