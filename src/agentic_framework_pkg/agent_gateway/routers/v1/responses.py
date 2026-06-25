"""
OpenAI Response API Router - Agent Gateway

This module provides OpenAI-compatible Response API endpoints that run parallel 
to the Assistant API. The Response API is designed for simpler, stateless interactions
and provides an alternative to the more complex Assistant API workflow.

Key Features:
- Single-shot completions with optional conversation context
- Streaming support for real-time responses  
- Function calling capabilities
- Compatible with existing OpenAI client libraries
- Simpler than Assistant API for basic use cases

Architectural Role:
- **Tier 1 (Ingress):** Entry point for Response API requests
- **Stateless Proxy:** Forwards requests to orchestration service
- **Authentication:** Validates user tokens and forwards user context
"""
import os
import httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Union
from ...auth import AuthCredentials, get_current_user
from ....logger_config import get_logger
from ...forwarded_headers import HeaderBuilder

router = APIRouter()
logger = get_logger(__name__)

# Initialize header builder for X-Forwarded-* header management
_header_builder = HeaderBuilder()

ORCHESTRATION_SERVICE_URL = os.getenv("ORCHESTRATION_SERVICE_URL", "http://orchestration_service:8084")

class ResponseRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stream: Optional[bool] = False
    functions: Optional[List[Dict[str, Any]]] = None
    function_call: Optional[Union[str, Dict[str, Any]]] = None
    user: Optional[str] = None
    
    # OpenAI API Parity - Complete Parameter Set (Phase 3)
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None  
    logit_bias: Optional[Dict[str, int]] = None
    n: Optional[int] = None
    response_format: Optional[Dict[str, Any]] = None
    seed: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    
    # Multi-Tier Session Management (Phase 2)
    session_id: Optional[str] = None
    mcp_session_id: Optional[str] = None
    multi_agent_session_id: Optional[str] = None
    gateway_session_id: Optional[str] = None

async def _handle_streaming_response(payload: Dict[str, Any], headers: Dict[str, str]):
    """Handle streaming response for Response API."""
    
    async def generate_stream():
        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{ORCHESTRATION_SERVICE_URL}/v1/responses/completions",
                    json=payload,
                    headers=headers
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_text():
                        if chunk.strip():
                            # Pass through SSE chunks as-is from orchestration service
                            # (already formatted with "data:" prefix)
                            yield chunk
            except Exception as e:
                logger.error(f"Streaming error: {e}", exc_info=True)
                yield f"data: {{'error': 'Stream interrupted: {str(e)}'}}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.post("/completions")
async def create_response_completion(
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    """
    Creates a response completion using the OpenAI Response API format.
    Forwards all OpenAI parameters including multi-tier session management.
    """
    body = await request.json()
    logger.info(f"[AGENT_GATEWAY] Processing Response API completion for user: {user.username if user else 'anonymous'}")
    
    # Extract session parameters from extra_body (Streamlit v2 compatibility)
    extra_body = body.get("extra_body", {})
    if extra_body and isinstance(extra_body, dict):
        # Merge extra_body session parameters into main body
        for key in ["session_id", "mcp_session_id", "multi_agent_session_id", "gateway_session_id"]:
            if key in extra_body and key not in body:
                body[key] = extra_body[key]
    
    # Log multi-tier session parameters if present
    session_info = []
    if body.get("session_id"):
        session_info.append(f"session_id={body.get('session_id')}")
    if body.get("mcp_session_id"):
        session_info.append(f"mcp_session_id={body.get('mcp_session_id')}")
    if body.get("multi_agent_session_id"):
        session_info.append(f"multi_agent_session_id={body.get('multi_agent_session_id')}")
    if body.get("gateway_session_id"):
        session_info.append(f"gateway_session_id={body.get('gateway_session_id')}")
    
    if session_info:
        logger.info(f"[AGENT_GATEWAY] Multi-tier sessions: {', '.join(session_info)}")

    # Build headers with X-Forwarded-* headers for context awareness
    base_headers = {key: value for key, value in request.headers.items() if key.lower() not in ['host', 'content-length']}
    forwarded_headers = _header_builder.build_forwarded_headers(request)
    headers = {**base_headers, **forwarded_headers}
    if user and user.token:
        headers["X-Forwarded-User-Token"] = user.token

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            if body.get("stream"):
                return await _handle_streaming_response(body, headers)
            else:
                response = await client.post(
                    f"{ORCHESTRATION_SERVICE_URL}/v1/responses/completions",
                    json=body,
                    headers=headers
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Orchestration service error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except Exception as e:
            logger.error(f"Error processing Response API request: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal error processing response completion")

@router.post("/chat/completions")
async def create_chat_completion(
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    """
    OpenAI-compatible chat completions endpoint.
    """
    return await create_response_completion(request, user)

@router.post("/invoke")
async def invoke_agent(
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    """
    Enhanced agent invocation endpoint compatible with unified execution architecture.
    Forwards requests to the orchestration service's /invoke endpoint.
    """
    body = await request.json()
    logger.info(f"[AGENT_GATEWAY] Processing /invoke for user: {user.username if user else 'anonymous'}, thread_id: {body.get('thread_id')}")

    # Build headers with X-Forwarded-* headers for context awareness
    base_headers = {key: value for key, value in request.headers.items() if key.lower() not in ['host', 'content-length']}
    forwarded_headers = _header_builder.build_forwarded_headers(request)
    headers = {**base_headers, **forwarded_headers}
    if user and user.token:
        headers["X-Forwarded-User-Token"] = user.token

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.post(
                f"{ORCHESTRATION_SERVICE_URL}/invoke",
                json=body,
                headers=headers
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Orchestration service error for /invoke: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except Exception as e:
            logger.error(f"Error processing /invoke request: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal error processing agent invocation")

@router.get("/models")
async def list_response_models(
    request: Request,
    user: AuthCredentials = Depends(get_current_user)
):
    """
    List available models for the Response API.
    """
    logger.info(f"[AGENT_GATEWAY] Listing Response API models for user: {user.username if user else 'anonymous'}")

    # Build headers with X-Forwarded-* headers for context awareness
    base_headers = {key: value for key, value in request.headers.items() if key.lower() not in ['host']}
    forwarded_headers = _header_builder.build_forwarded_headers(request)
    headers = {**base_headers, **forwarded_headers}
    if user and user.token:
        headers["X-Forwarded-User-Token"] = user.token

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{ORCHESTRATION_SERVICE_URL}/v1/responses/models",
                headers=headers
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Error fetching Response API models: {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except Exception as e:
            logger.error(f"Error communicating with orchestration service: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Error fetching models")
