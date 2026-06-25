"""
This module provides the OpenAI-compatible `/v1/assistants` API endpoints.
It acts as a stateless proxy, forwarding requests to the orchestration_service.

DEPRECATED: The Assistants API is deprecated in favor of the Responses API.
Please use /v1/responses/completions for new implementations.
This API is maintained for backward compatibility only.
"""
import os
import httpx
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

from ...auth import AuthCredentials, get_current_user
from ....logger_config import get_logger
from ...forwarded_headers import HeaderBuilder

router = APIRouter()
logger = get_logger(__name__)

# Initialize header builder for X-Forwarded-* header management
_header_builder = HeaderBuilder()

ORCHESTRATION_SERVICE_URL = os.getenv("ORCHESTRATION_SERVICE_URL", "http://orchestration_service:8084")

class AssistantModel(BaseModel):
    id: str
    object: str = "assistant"
    created_at: int
    name: Optional[str] = None
    description: Optional[str] = None
    model: str
    instructions: Optional[str] = None
    tools: List[Dict] = []

async def proxy_request(request: Request, user: Optional[AuthCredentials]):
    # Build headers with X-Forwarded-* headers for context awareness
    base_headers = {key: value for key, value in request.headers.items() if key.lower() not in ['host']}
    forwarded_headers = _header_builder.build_forwarded_headers(request)
    headers = {**base_headers, **forwarded_headers}
    if user and user.token:
        headers["X-Forwarded-User-Token"] = user.token

    target_url = f"{ORCHESTRATION_SERVICE_URL}{request.url.path}"
    
    logger.info(f"[GATEWAY_PROXY] User '{user.username if user else 'anonymous'}' requesting {request.method} {request.url.path}")
    logger.debug(f"[GATEWAY_PROXY] Forwarding request to: {target_url}")

    async with httpx.AsyncClient(timeout=300.0) as client:  # 5 minutes for agent execution
        try:
            fwd_request = client.build_request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=await request.body(),
                params=request.query_params
            )
            response = await client.send(fwd_request)
            logger.debug(f"[GATEWAY_PROXY] Received response: {response.status_code} from {target_url}")
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"[GATEWAY_PROXY] HTTP Status Error proxying to {target_url}: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except Exception as e:
            logger.error(f"[GATEWAY_PROXY] Unexpected error proxying to {target_url}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

@router.post("", response_model=AssistantModel)
async def create_assistant(
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info("[AGENT_GATEWAY] Handling POST /v1/assistants/")
    return await proxy_request(request, user)

@router.get("/{assistant_id}", response_model=AssistantModel)
async def get_assistant(
    assistant_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling GET /v1/assistants/{assistant_id}/")
    return await proxy_request(request, user)

@router.post("/{assistant_id}", response_model=AssistantModel)
async def update_assistant(
    assistant_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling POST /v1/assistants/{assistant_id}/")
    return await proxy_request(request, user)

@router.get("")
async def list_assistants(
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info("[AGENT_GATEWAY] Handling GET /v1/assistants/")
    return await proxy_request(request, user)

@router.delete("/{assistant_id}")
async def delete_assistant(
    assistant_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling DELETE /v1/assistants/{assistant_id}/")
    return await proxy_request(request, user)
