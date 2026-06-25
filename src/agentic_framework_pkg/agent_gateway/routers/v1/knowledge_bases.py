"""
Knowledge Bases proxy router for Agent Gateway.
Forwards all requests to the orchestration service with authentication.
"""

from fastapi import APIRouter, Depends, Request
from typing import Any

from ...auth import get_current_user
from .assistants import proxy_request  # Use the same proxy function as other routers

router = APIRouter()

# Proxy all knowledge base endpoints to orchestration service
@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_knowledge_bases(
    request: Request,
    path: str,
    current_user: Any = Depends(get_current_user)
):
    """Proxy all knowledge base requests to orchestration service"""
    # The proxy_request function will automatically construct the full URL
    # from request.url.path which includes /v1/knowledge_bases/{path}
    return await proxy_request(request, current_user)