"""
OpenAI-compatible Chat Completions Translation Layer

This module provides the `/v1/chat/completions` endpoint that translates
ADEPT's native Response API format into standard OpenAI Chat Completions format.

Architectural Role (Dual Endpoint Architecture):
-   **Translation Layer**: Proxies requests to the orchestration service's
    Response API endpoint and rewrites the response format:
    - `response.completion` → `chat.completion`
    - `response.completion.chunk` → `chat.completion.chunk`
    - Strips ADEPT-specific extensions (`session_fork`) from responses
-   **Target Clients**: OpenWebUI, standard OpenAI SDK, any client expecting
    the Chat Completions format.
-   **Counterpart**: `/v1/responses/completions` (responses.py) serves the
    native ADEPT format with extensions for ADEPT SDK, Streamlit, notebooks.

Session 79 Fix: Resolves "Model not found" error in OpenWebUI caused by
non-standard `object` field values in chat completion responses.
"""

import json
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ...auth import AuthCredentials, get_current_user
from ...forwarded_headers import HeaderBuilder
from ....logger_config import get_logger

router = APIRouter()
logger = get_logger(__name__)

_header_builder = HeaderBuilder()

ORCHESTRATION_SERVICE_URL = os.getenv(
    "ORCHESTRATION_SERVICE_URL", "http://orchestration_service:8084"
)


@router.post("/completions", summary="OpenAI Chat Completions")
async def chat_completions(
    request: Request,
    current_user: AuthCredentials = Depends(get_current_user),
):
    """
    OpenAI-compatible chat completions endpoint.

    Proxies to the ADEPT Responses API and translates the response format
    from response.completion -> chat.completion for standard OpenAI clients.
    """
    body = await request.json()
    logger.info(
        f"[AGENT_GATEWAY] Chat Completions request from user: "
        f"{current_user.username if current_user else 'anonymous'}"
    )

    # Build headers matching the responses.py pattern
    base_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in ["host", "content-length"]
    }
    forwarded_headers = _header_builder.build_forwarded_headers(request)
    headers = {**base_headers, **forwarded_headers}
    if current_user and current_user.token:
        headers["X-Forwarded-User-Token"] = current_user.token

    # Extract extra_body session parameters (Streamlit v2 compatibility)
    extra_body = body.get("extra_body", {})
    if extra_body and isinstance(extra_body, dict):
        for key in [
            "session_id",
            "mcp_session_id",
            "multi_agent_session_id",
            "gateway_session_id",
        ]:
            if key in extra_body and key not in body:
                body[key] = extra_body[key]

    is_streaming = body.get("stream", False)

    try:
        if is_streaming:
            return await _handle_streaming_chat(body, headers)
        else:
            return await _handle_non_streaming_chat(body, headers)
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Orchestration service error: {e.response.status_code} - "
            f"{e.response.text}"
        )
        raise HTTPException(
            status_code=e.response.status_code, detail=e.response.text
        )
    except Exception as e:
        logger.error(
            f"Error processing chat completion: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error processing chat completion",
        )


async def _handle_non_streaming_chat(
    payload: dict,
    headers: dict,
) -> JSONResponse:
    """Proxy non-streaming request and translate response format."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{ORCHESTRATION_SERVICE_URL}/v1/responses/completions",
            json=payload,
            headers=headers,
        )
    resp.raise_for_status()
    data = resp.json()

    # Translate: response.completion -> chat.completion
    if data.get("object") == "response.completion":
        data["object"] = "chat.completion"
    # Strip ADEPT-specific extensions
    data.pop("session_fork", None)

    return JSONResponse(content=data)


async def _handle_streaming_chat(
    payload: dict,
    headers: dict,
) -> StreamingResponse:
    """Proxy streaming request, rewriting each SSE chunk."""

    async def generate_stream():
        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{ORCHESTRATION_SERVICE_URL}/v1/responses/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_text():
                        if not chunk.strip():
                            continue
                        yield _rewrite_sse_chunk(chunk)
            except Exception as e:
                logger.error(f"Chat streaming error: {e}", exc_info=True)
                error_payload = json.dumps(
                    {"error": f"Stream interrupted: {str(e)}"}
                )
                yield f"data: {error_payload}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _rewrite_sse_chunk(raw_chunk: str) -> str:
    """Rewrite SSE chunk(s) from Response API to Chat Completions format.

    Handles raw text that may contain one or more SSE data lines.
    Translates object types and strips ADEPT-specific fields.
    """
    lines = raw_chunk.strip().split("\n")
    rewritten = []

    for line in lines:
        if line.startswith("data: "):
            payload = line[6:]

            # Pass [DONE] sentinel through unchanged
            if payload.strip() == "[DONE]":
                rewritten.append("data: [DONE]")
                continue

            try:
                data = json.loads(payload)

                # Translate object type
                obj = data.get("object", "")
                if obj == "response.completion.chunk":
                    data["object"] = "chat.completion.chunk"
                elif obj == "response.completion":
                    data["object"] = "chat.completion"

                # Strip ADEPT-specific extensions
                data.pop("session_fork", None)

                rewritten.append(f"data: {json.dumps(data)}")
            except (json.JSONDecodeError, TypeError):
                # Pass through unparseable lines unchanged
                rewritten.append(line)
        else:
            # Pass through non-data lines (comments, empty, etc.)
            rewritten.append(line)

    return "\n".join(rewritten) + "\n\n"
