"""AG-UI Protocol Router - Agent Gateway

Streaming proxy that forwards AG-UI requests to the orchestration service
and passes through the JSONL event stream.
"""

import os
import time
import httpx
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse

from ...auth import AuthCredentials, get_current_user
from ....logger_config import get_logger
from ...forwarded_headers import HeaderBuilder

router = APIRouter()
logger = get_logger(__name__)

_header_builder = HeaderBuilder()

ORCHESTRATION_SERVICE_URL = os.getenv(
    "ORCHESTRATION_SERVICE_URL", "http://orchestration_service:8084"
)


@router.post("/run")
async def agui_run_proxy(
    request: Request,
    user: AuthCredentials = Depends(get_current_user),
):
    """Proxy AG-UI run requests to the orchestration service.

    Streams the JSONL response back to the client line-by-line.
    """
    body = await request.json()
    logger.info(
        f"[AG-UI-GW] Proxying AG-UI run for user={user.username}, "
        f"thread_id={body.get('thread_id')}"
    )

    # Build forwarded headers (same pattern as responses.py)
    base_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in ("host", "content-length")
    }
    forwarded_headers = _header_builder.build_forwarded_headers(request)
    headers = {**base_headers, **forwarded_headers}
    if user and user.token:
        headers["X-Forwarded-User-Token"] = user.token

    async def generate_stream():
        start_time = time.monotonic()
        line_count = 0
        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{ORCHESTRATION_SERVICE_URL}/v1/ag-ui/run",
                    json=body,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            line_count += 1
                            yield line + "\n"
            except Exception as e:
                logger.error(f"[AG-UI-GW] Proxy stream error: {e}", exc_info=True)
                import json as _json
                yield _json.dumps({
                    "type": "RunError",
                    "message": f"Gateway proxy error: {e}",
                    "code": "gateway_proxy_error",
                }) + "\n"
            finally:
                elapsed = time.monotonic() - start_time
                logger.info(
                    f"[AG-UI-GW] Proxy stream completed: "
                    f"thread_id={body.get('thread_id')}, "
                    f"lines={line_count}, elapsed={elapsed:.2f}s, "
                    f"user={user.username}"
                )

    return StreamingResponse(
        generate_stream(),
        media_type="text/plain",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )
