"""
This module provides the OpenAI-compatible `/v1/threads` API endpoints.
It acts as a stateless proxy, forwarding requests to the orchestration_service.

DEPRECATED: The Threads API is deprecated as part of the Assistants API deprecation.
Please use /v1/responses/completions for new implementations.
This API is maintained for backward compatibility only.
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import Dict, Optional

from ...auth import AuthCredentials, get_current_user
from ....logger_config import get_logger
from .assistants import proxy_request # Re-use the proxy function

router = APIRouter()
logger = get_logger(__name__)

class ThreadModel(BaseModel):
    id: str
    object: str = "thread"
    created_at: int
    metadata: Optional[Dict] = None

@router.post("", response_model=ThreadModel)
async def create_thread(
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info("[AGENT_GATEWAY] Handling POST /v1/threads/")
    return await proxy_request(request, user)

@router.get("/{thread_id}", response_model=ThreadModel)
async def get_thread(
    thread_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling GET /v1/threads/{thread_id}")
    return await proxy_request(request, user)


@router.post("/{thread_id}", response_model=ThreadModel)
async def update_thread(
    thread_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling POST /v1/threads/{thread_id}")
    return await proxy_request(request, user)

@router.delete("/{thread_id}")
async def delete_thread(
    thread_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling DELETE /v1/threads/{thread_id}")
    return await proxy_request(request, user)

@router.post("/{thread_id}/messages")
async def create_message(
    request: Request,
    thread_id: str,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling POST /v1/threads/{thread_id}/messages")
    return await proxy_request(request, user)

@router.get("/{thread_id}/messages")
async def list_messages(
    request: Request,
    thread_id: str,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling GET /v1/threads/{thread_id}/messages")
    return await proxy_request(request, user)

@router.get("/{thread_id}/messages/{message_id}")
async def retrieve_message(
    request: Request,
    thread_id: str,
    message_id: str,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling GET /v1/threads/{thread_id}/messages/{message_id}")
    return await proxy_request(request, user)

@router.post("/{thread_id}/messages/{message_id}")
async def update_message(
    request: Request,
    thread_id: str,
    message_id: str,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling POST /v1/threads/{thread_id}/messages/{message_id}")
    return await proxy_request(request, user)
