"""
NGINX File Proxy - Embedded Python ASGI Application

Responsibilities:
1. Validate HMAC presigned URL tokens
2. Serve files via NGINX Unit sendfile
3. Redis lookup for file metadata and ownership validation
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional, Tuple

import redis.asyncio as redis
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

# Environment configuration
PRESIGNED_URL_SECRET = os.getenv("PRESIGNED_URL_SECRET", "")
# CRITICAL: Use database /2 for file metadata (consistent with orchestration_service and mcp_server)
# Database /0 is for tool configurations, Database /2 is for file metadata
base_redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0").rsplit("/", 1)[0]
REDIS_URL = f"{base_redis_url}/2"  # Force database /2
UPLOADED_FILES_DIR = Path("/app/data/uploaded_files")

# Redis connection pool
redis_pool = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)


class HMACValidator:
    """HMAC token validator for presigned URLs."""

    def __init__(self, secret: str):
        self.secret = secret.encode() if isinstance(secret, str) else secret

    def validate_token(
        self, file_id: str, user_id: str, token: str, expires_ts: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate HMAC token for presigned URL.

        Token format: {signature}:{nonce}
        Message: {file_id}:{user_id}:{expires_ts}:{nonce}

        Returns:
            (is_valid, error_message)
        """
        # Parse token
        try:
            signature, nonce = token.split(":", 1)
        except ValueError:
            return False, "Invalid token format"

        # Check expiration
        current_ts = int(time.time())
        if current_ts > expires_ts:
            return False, "Token expired"

        # Reconstruct message
        message = f"{file_id}:{user_id}:{expires_ts}:{nonce}"

        # Compute expected signature
        expected_signature = hmac.new(
            self.secret, message.encode(), hashlib.sha256
        ).hexdigest()

        # Constant-time comparison (prevent timing attacks)
        if not secrets.compare_digest(signature, expected_signature):
            return False, "Invalid signature"

        return True, None


validator = HMACValidator(PRESIGNED_URL_SECRET)


async def download_file(request):
    """
    Presigned URL download endpoint.

    GET /v1/files/{file_id}/download?token={token}&expires={expires}
    """
    file_id = request.path_params["file_id"]
    token = request.query_params.get("token")
    expires = request.query_params.get("expires")

    # Validate query parameters
    if not token or not expires:
        return JSONResponse(
            {"detail": "Missing token or expires parameter"}, status_code=400
        )

    try:
        expires_ts = int(expires)
    except ValueError:
        return JSONResponse({"detail": "Invalid expires parameter"}, status_code=400)

    # Get file metadata from Redis
    file_key = f"file_metadata:{file_id}"
    try:
        file_metadata_json = await redis_pool.get(file_key)
    except Exception as e:
        return JSONResponse(
            {"detail": f"Redis error: {str(e)}"}, status_code=500
        )

    if not file_metadata_json:
        return JSONResponse({"detail": "File not found"}, status_code=404)

    try:
        file_metadata = json.loads(file_metadata_json)
    except json.JSONDecodeError:
        return JSONResponse(
            {"detail": "File metadata is corrupted"}, status_code=500
        )

    # Get user_id from metadata
    user_id = file_metadata.get("owner_id")
    if not user_id:
        return JSONResponse(
            {"detail": "File metadata missing ownership information"}, status_code=500
        )

    # Validate HMAC token
    is_valid, error_msg = validator.validate_token(file_id, user_id, token, expires_ts)
    if not is_valid:
        return JSONResponse({"detail": error_msg}, status_code=401)

    # Check if file exists on disk
    # CRITICAL: Use current_path from metadata if available (e.g., from RegisterLocalFile)
    # Fall back to session_id/file_id reconstruction for backward compatibility
    current_path = file_metadata.get("current_path")
    if current_path:
        file_path = Path(current_path)
    else:
        # Legacy path reconstruction
        session_id = file_metadata.get("session_id")
        if session_id:
            file_path = UPLOADED_FILES_DIR / session_id / file_id
        else:
            file_path = UPLOADED_FILES_DIR / file_id

    if not file_path.exists():
        return JSONResponse(
            {"detail": f"File not found on disk: {file_path}"}, status_code=404
        )

    # Get file metadata for content type
    filename = file_metadata.get("filename", file_id)
    content_type = file_metadata.get("content_type", "application/octet-stream")

    # Determine disposition (inline for viewable types, attachment for others)
    disposition = request.query_params.get("disposition")
    if not disposition:
        # Auto-detect based on content type
        if content_type.startswith(("image/", "text/", "application/pdf")):
            disposition = "inline"
        else:
            disposition = "attachment"

    # Serve file with NGINX Unit sendfile optimization
    return FileResponse(
        file_path,
        media_type=content_type,
        filename=filename,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
        },
    )


async def health_check(request):
    """Health check endpoint."""
    try:
        await redis_pool.ping()
        redis_status = "ok"
    except Exception as e:
        redis_status = f"error: {str(e)}"

    return JSONResponse(
        {
            "status": "healthy" if redis_status == "ok" else "degraded",
            "redis": redis_status,
            "service": "nginx_file_proxy",
        }
    )


# Starlette ASGI application
app = Starlette(
    debug=False,
    routes=[
        Route("/v1/files/{file_id}/download", download_file),
        Route("/health", health_check),
    ],
)
