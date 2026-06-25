"""
This module provides the API endpoints for listing registered gateways.
It acts as a proxy to the gateway_registry service.
"""
import os
import httpx
from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Optional

from ...auth import AuthCredentials, get_current_user
from ....logger_config import get_logger

router = APIRouter()
logger = get_logger(__name__)

GATEWAY_REGISTRY_URL = os.getenv("GATEWAY_REGISTRY_URL", "http://gateway_registry:8086")

async def proxy_registry_request(request: Request, user: Optional[AuthCredentials]):
    """Proxies a request to the Gateway Registry, forwarding the user's token."""
    headers = {key: value for key, value in request.headers.items() if key.lower() not in ['host']}
    if user and user.token:
        headers["Authorization"] = f"Bearer {user.token}"

    # Ensure the path for a collection endpoint has a trailing slash.
    path = request.url.path
    if not path.endswith('/'):
        path += '/'
        
    target_url = f"{GATEWAY_REGISTRY_URL}{path}"
    
    logger.info(f"Proxying gateway registry request to: {target_url}") # VERBOSE DEBUGGING
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            fwd_request = client.build_request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=await request.body(),
                params=request.query_params
            )
            response = await client.send(fwd_request)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Status Error while proxying to {target_url}: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except Exception as e:
            logger.error(f"Unexpected error while proxying to {target_url}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

@router.get("")
async def list_gateways(
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    """
    Proxies the request to list all registered gateways from the Gateway Registry.
    """
    return await proxy_registry_request(request, user)
