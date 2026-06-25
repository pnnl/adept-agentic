"""
This module provides the OpenAI-compatible `/v1/files` API endpoints.
It acts as a stateless proxy, forwarding all file-related requests to the orchestration_service.
"""

from fastapi import (
    APIRouter,
    Depends,
    Request,
    UploadFile,
    File,
    Form,
    HTTPException,
    Path,
    Query,
)
from fastapi.responses import Response, StreamingResponse
from typing import Optional
import httpx
import os
import json

from ...auth import AuthCredentials, get_current_user
from ....logger_config import get_logger
from ...forwarded_headers import HeaderBuilder

router = APIRouter()
logger = get_logger(__name__)

ORCHESTRATION_SERVICE_URL = os.getenv(
    "ORCHESTRATION_SERVICE_URL", "http://orchestration_service:8084"
)

# Module-level singleton for header building (reads env vars once at import)
_header_builder = HeaderBuilder()


@router.post("")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    purpose: str = Form(...),
    session_id: Optional[str] = Form(None),
    user: AuthCredentials = Depends(get_current_user),
):
    """Proxies the file upload request to the orchestration service."""
    logger.info(
        f"[AGENT_GATEWAY] Proxying file upload for user: {user.username if user else 'anonymous'}"
    )

    # Try to extract session_id from form data first, then from other sources
    extracted_session_id = session_id

    # If no session_id in form data, try to extract from request
    if not extracted_session_id:
        try:
            # Check if there are any additional form fields that might contain session info
            form_data = await request.form()
            for key, value in form_data.items():
                if key == "session_id":
                    extracted_session_id = str(value)
                    logger.info(
                        f"[AGENT_GATEWAY] Extracted session_id from form: {extracted_session_id}"
                    )
                    break
        except Exception as e:
            logger.debug(f"Could not extract additional form data: {e}")

    # Build headers with X-Forwarded-* security validation
    forwarded_headers = _header_builder.build_forwarded_headers(request)
    headers = {**forwarded_headers}
    if user and user.token:
        headers["X-Forwarded-User-Token"] = user.token

    files_data = {"file": (file.filename, await file.read(), file.content_type)}
    data = {"purpose": purpose}
    if extracted_session_id:
        data["session_id"] = extracted_session_id
        logger.info(
            f"[AGENT_GATEWAY] Including session_id in file upload: {extracted_session_id}"
        )

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{ORCHESTRATION_SERVICE_URL}/v1/files/",
                headers=headers,
                files=files_data,
                data=data,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Error proxying file upload: {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code, detail=e.response.text
            )
        except Exception as e:
            logger.error(
                f"Unexpected error during file upload proxy: {e}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))


from .assistants import proxy_request


@router.get("")
async def list_files(
    request: Request, user: AuthCredentials = Depends(get_current_user)
):
    """Proxies the list files request to the orchestration service."""
    logger.info("[AGENT_GATEWAY] Proxying GET /v1/files/")
    return await proxy_request(request, user)


@router.get("/{file_id}")
async def retrieve_file(
    file_id: str, request: Request, user: AuthCredentials = Depends(get_current_user)
):
    """Proxies the retrieve file metadata request to the orchestration service."""
    logger.info(f"[AGENT_GATEWAY] Proxying GET /v1/files/{file_id}")
    return await proxy_request(request, user)


@router.get("/{file_id}/content")
async def retrieve_file_content(
    file_id: str, request: Request, user: AuthCredentials = Depends(get_current_user)
):
    """Proxies the retrieve file content request to the orchestration service.

    This endpoint returns binary file content, so it needs special handling
    instead of the standard JSON proxy_request.
    """
    logger.info(f"[AGENT_GATEWAY] Proxying GET /v1/files/{file_id}/content")

    # Build headers for forwarding with X-Forwarded-* security validation
    base_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in ["host", "content-length"]
    }
    forwarded_headers = _header_builder.build_forwarded_headers(request)
    headers = {**base_headers, **forwarded_headers}
    if user and user.token:
        headers["X-Forwarded-User-Token"] = user.token

    target_url = f"{ORCHESTRATION_SERVICE_URL}/v1/files/{file_id}/content"

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            # Stream the file content directly without parsing as JSON
            response = await client.get(target_url, headers=headers)
            response.raise_for_status()

            # Return a streaming response with the same headers as the orchestration service
            from fastapi.responses import StreamingResponse

            return StreamingResponse(
                content=response.iter_bytes(),
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/octet-stream"
                    ),
                    "Content-Disposition": response.headers.get(
                        "Content-Disposition", f'attachment; filename="{file_id}"'
                    ),
                },
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"Error proxying file content: {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code, detail=e.response.text
            )
        except Exception as e:
            logger.error(
                f"Unexpected error during file content proxy: {e}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{file_id}")
async def delete_file(
    file_id: str, request: Request, user: AuthCredentials = Depends(get_current_user)
):
    """Proxies the delete file request to the orchestration service."""
    logger.info(f"[AGENT_GATEWAY] Proxying DELETE /v1/files/{file_id}")
    return await proxy_request(request, user)


@router.post("/register-local")
async def register_local_file(
    request: Request, user: AuthCredentials = Depends(get_current_user)
):
    """
    Proxies the register-local file request to the orchestration service.

    This allows users to register existing files from the filesystem with their session.
    """
    logger.info(
        f"[AGENT_GATEWAY] Proxying POST /v1/files/register-local for user: {user.username if user else 'anonymous'}"
    )

    # Get the request body
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse request body: {e}")
        raise HTTPException(status_code=400, detail="Invalid request body")

    # Build headers with X-Forwarded-* security validation
    forwarded_headers = _header_builder.build_forwarded_headers(request)
    headers = {**forwarded_headers}
    if user and user.token:
        headers["X-Forwarded-User-Token"] = user.token

    # Extract session_id from body if present, or from headers
    session_id = body.get("session_id")
    if session_id:
        headers["X-Session-ID"] = session_id

    async with httpx.AsyncClient() as client:
        try:
            target_url = f"{ORCHESTRATION_SERVICE_URL}/v1/files/register-local"
            response = await client.post(
                target_url, json=body, headers=headers, timeout=30
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Error proxying register-local request: {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code, detail=e.response.text
            )
        except Exception as e:
            logger.error(
                f"Unexpected error during register-local proxy: {e}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{file_id}/signed",
    summary="Generate Presigned URL (Proxy)",
    description="Proxy to orchestration service for presigned URL generation",
)
async def generate_presigned_url_proxy(
    file_id: str = Path(..., description="File UUID"),
    request: Request = None,
    user: AuthCredentials = Depends(get_current_user),
):
    """Proxy presigned URL generation to orchestration service.

    Requires JWT authentication (normal flow).
    """
    logger.info(
        f"[AGENT_GATEWAY] Proxying POST /v1/files/{file_id}/signed for user: {user.username if user else 'anonymous'}"
    )

    # Get request body
    try:
        body = await request.body()
    except Exception as e:
        logger.error(f"Failed to read request body: {e}")
        raise HTTPException(status_code=400, detail="Invalid request body")

    # Build X-Forwarded-* headers with security validation
    forwarded_headers = _header_builder.build_forwarded_headers(request)

    # Build headers for forwarding
    headers = {
        "Content-Type": "application/json",
        **forwarded_headers,  # Include X-Forwarded-Host, X-Forwarded-Proto, X-Forwarded-Port
    }

    if user:
        # Forward JWT token if available
        if user.token:
            headers["X-Forwarded-User-Token"] = user.token

        # CRITICAL: Orchestration service expects X-User-ID and X-User-Username headers
        # Validate required user fields before forwarding
        if not user.user_id:
            logger.error("User object missing user_id field")
            raise HTTPException(
                status_code=500,
                detail="Invalid user context: missing user_id"
            )
        if not user.username:
            logger.error(f"User {user.user_id} missing username field")
            raise HTTPException(
                status_code=500,
                detail="Invalid user context: missing username"
            )

        headers["X-User-ID"] = user.user_id
        headers["X-User-Username"] = user.username

        # Groups are optional but should be validated if present
        if user.groups:
            headers["X-User-Groups"] = ",".join(user.groups)
        else:
            logger.warning(
                f"User {user.username} ({user.user_id}) has no groups assigned"
            )

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            target_url = f"{ORCHESTRATION_SERVICE_URL}/v1/files/{file_id}/signed"
            response = await client.post(target_url, headers=headers, content=body)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Error proxying presigned URL generation: {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=e.response.json().get(
                    "detail", "Failed to generate presigned URL"
                ),
            )
        except Exception as e:
            logger.error(
                f"Unexpected error during presigned URL proxy: {e}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{file_id}/download",
    summary="Download File (Presigned URL - Proxy)",
    description="Proxy presigned URL download to orchestration service (NO JWT required)",
)
async def download_file_with_presigned_url_proxy(
    file_id: str = Path(..., description="File UUID"),
    token: str = Query(..., description="HMAC-signed token"),
    expires: int = Query(..., description="Expiration timestamp"),
    request: Request = None,
):
    """Proxy presigned URL download to orchestration service.

    CRITICAL: NO JWT authentication required (token validation in orchestration service).

    Special handling:
    - This endpoint bypasses normal JWT authentication middleware
    - Token validation happens in orchestration service via HMAC
    - X-Forwarded-Host header passed for X-Accel-Redirect detection
    """
    logger.info(
        f"[AGENT_GATEWAY] Proxying GET /v1/files/{file_id}/download (presigned URL)"
    )

    # Build X-Forwarded-* headers with security validation
    forwarded_headers = _header_builder.build_forwarded_headers(request)

    # Proxy to orchestration service with presigned URL parameters
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            target_url = f"{ORCHESTRATION_SERVICE_URL}/v1/files/{file_id}/download"
            response = await client.get(
                target_url,
                params={"token": token, "expires": expires},
                headers=forwarded_headers,  # Use validated headers
            )
            response.raise_for_status()

            # Check if orchestration service returned X-Accel-Redirect header
            x_accel_redirect = response.headers.get("X-Accel-Redirect")
            if x_accel_redirect:
                # Return X-Accel-Redirect response (Nginx will handle file serving)
                return Response(
                    content=b"",
                    headers={
                        "X-Accel-Redirect": x_accel_redirect,
                        "Content-Disposition": response.headers.get(
                            "Content-Disposition", ""
                        ),
                        "Content-Type": response.headers.get(
                            "Content-Type", "application/octet-stream"
                        ),
                    },
                    status_code=200,
                )
            else:
                # Stream file content directly (direct port access)
                return StreamingResponse(
                    response.iter_bytes(chunk_size=8192),
                    media_type=response.headers.get(
                        "Content-Type", "application/octet-stream"
                    ),
                    headers={
                        "Content-Disposition": response.headers.get(
                            "Content-Disposition", ""
                        )
                    },
                )
        except httpx.HTTPStatusError as e:
            logger.error(f"Error proxying presigned URL download: {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=e.response.json().get("detail", "Failed to download file"),
            )
        except Exception as e:
            logger.error(
                f"Unexpected error during presigned URL download proxy: {e}",
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail=str(e))
