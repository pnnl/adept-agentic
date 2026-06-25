"""
This module defines the administrative management endpoints for the Agent Gateway.

It provides functionality for administrators to manually trigger certain
lifecycle events, such as re-registering the gateway with the registry service.
All endpoints in this module are protected and require the 'admin' role.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import os

from ..auth import AuthCredentials, get_current_user, require_role
from ..lifespan import register_gateway_with_registry
from ...logger_config import get_logger

router = APIRouter()
logger = get_logger(__name__)
AUTH_ENABLED = os.getenv("AGENT_GATEWAY_AUTH_ENABLED", "false").lower() == "true"

@router.post(
    "/v1/management/registry/reregister",
    summary="Manually Re-register Gateway",
    dependencies=[Depends(require_role("admin"))]
)
async def reregister_gateway():
    """
    Manually triggers the gateway to re-register itself with the Gateway Registry.

    This is a privileged operation for administrators to force an update or
    recover from a failed initial registration without restarting the service.
    """
    logger.info("Manual re-registration triggered by an administrator.")
    try:
        await register_gateway_with_registry()
        return JSONResponse(
            content={"status": "success", "message": "Gateway has been successfully re-registered."}
        )
    except Exception as e:
        logger.error(f"Manual re-registration attempt failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to re-register gateway: {e}")