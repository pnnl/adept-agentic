"""
This module provides a proxy for the /v1/tools endpoints, forwarding them
securely to the orchestration_service.
"""
from fastapi import APIRouter, Request, Depends
from ...auth import AuthCredentials, get_current_user
from .assistants import proxy_request # Re-use the generic proxy function

router = APIRouter()

@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_tool_requests(
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    """Proxies all tool management requests to the orchestration service."""
    return await proxy_request(request, user)
