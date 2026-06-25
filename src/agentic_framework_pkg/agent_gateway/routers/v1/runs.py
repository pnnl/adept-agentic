"""
This module provides the OpenAI-compatible `/v1/threads/{thread_id}/runs` API endpoints.
It acts as a stateless proxy, forwarding requests to the orchestration_service.

DEPRECATED: The Runs API is deprecated as part of the Assistants API deprecation.
Please use /v1/responses/completions for new implementations.
This API is maintained for backward compatibility only.
"""
from fastapi import APIRouter, Depends, Request
from typing import Optional

from ...auth import AuthCredentials, get_current_user
from ....logger_config import get_logger
from .assistants import proxy_request

router = APIRouter()
logger = get_logger(__name__)

@router.post("")
async def create_run(
    thread_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling POST /v1/threads/{thread_id}/runs/")
    return await proxy_request(request, user)

@router.get("")
async def list_runs(
    thread_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling GET /v1/threads/{thread_id}/runs/")
    return await proxy_request(request, user)


@router.get("/{run_id}/steps")
async def list_run_steps(
    thread_id: str,
    run_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling GET /v1/threads/{thread_id}/runs/{run_id}/steps/")
    return await proxy_request(request, user)

@router.get("/{run_id}/steps/{step_id}")
async def retrieve_run_step(
    thread_id: str,
    run_id: str,
    step_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling GET /v1/threads/{thread_id}/runs/{run_id}/steps/{step_id}")
    return await proxy_request(request, user)

@router.get("/{run_id}")
async def retrieve_run(
    thread_id: str,
    run_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling GET /v1/threads/{thread_id}/runs/{run_id}/")
    return await proxy_request(request, user)


@router.post("/{run_id}/submit_tool_outputs")
async def submit_tool_outputs(
    thread_id: str,
    run_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling POST /v1/threads/{thread_id}/runs/{run_id}/submit_tool_outputs/")
    return await proxy_request(request, user)

@router.post("/{run_id}/cancel")
async def cancel_run(
    thread_id: str,
    run_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    logger.info(f"[AGENT_GATEWAY] Handling POST /v1/threads/{thread_id}/runs/{run_id}/cancel/")
    return await proxy_request(request, user)