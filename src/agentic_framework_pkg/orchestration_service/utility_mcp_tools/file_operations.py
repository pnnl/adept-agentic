"""File Operations Utility MCP Tools

Provides internal tools for file management operations including presigned URL generation.
"""
import json
import os
import time
from typing import Any, Dict, Optional

import redis.asyncio as redis
from pydantic import BaseModel, Field

from agentic_framework_pkg.logger_config import get_logger
from ..redis_client import get_files_redis_client

logger = get_logger(__name__)


def get_file_key(file_id: str) -> str:
    """Returns the Redis key for a given file ID."""
    return f"file_metadata:{file_id}"


class GeneratePresignedURL:
    """Generate time-limited presigned URL for file downloads.

    This tool enables the orchestration agent to help users generate HMAC-signed
    presigned URLs for files they have uploaded or registered. The URLs allow
    time-limited downloads without JWT authentication.

    Args:
        file_id: UUID of the file to generate presigned URL for
        expiry_seconds: Time-to-live in seconds (default: 3600 = 1 hour, max: 86400 = 24 hours)
        disposition: Content-Disposition type ("inline" for browser display, "attachment" for download)
        user_id: User UUID (automatically populated from context)
        username: Username (automatically populated from context)
        groups: User groups (automatically populated from context)

    Returns:
        Dict with keys:
        - success: bool - Whether operation succeeded
        - presigned_url: str - Full presigned download URL with embedded HMAC token
        - expires_at: int - Unix timestamp when URL expires
        - expires_in: int - Seconds until expiration
        - file_id: str - UUID of the file
        - error: str - Error message if success=False

    Example:
        >>> result = await GeneratePresignedURL.execute(
        ...     file_id="550e8400-e29b-41d4-a716-446655440000",
        ...     expiry_seconds=7200,  # 2 hours
        ...     disposition="inline",
        ...     user_id="user_123",
        ...     username="alice",
        ...     groups=["scientists", "data-uploaders"]
        ... )
        >>> print(result)
        {
            "success": true,
            "presigned_url": "https://api.agentic.local/v1/files/550e8400.../download?token=abc123...&expires=1738064400",
            "expires_at": 1738064400,
            "expires_in": 7200,
            "file_id": "550e8400-e29b-41d4-a716-446655440000"
        }

    Security:
        - Validates user owns the file before generating URL
        - HMAC-SHA256 signed token prevents tampering
        - Constant-time signature validation prevents timing attacks
        - Expiration enforcement (1 second to 24 hours)

    Use Cases:
        - Sharing files with external systems (no Keycloak account)
        - Email attachments with expiring links
        - Embedding images/SVG/PDF in Streamlit or OpenWebUI
        - Webhook callbacks with file downloads
    """

    name = "generate_presigned_url"
    description = """Generate a time-limited, HMAC-signed URL for downloading a file without authentication.

    Use this tool when users ask to:
    - "Create a shareable link for my file"
    - "Generate a download URL that expires in X hours"
    - "Make a presigned URL for data.csv"
    - "Create a temporary download link"

    The URL works without JWT authentication and expires after the specified time.
    Supports all three access patterns (External FQDN, Direct port, Port forwarding).
    """

    # Pydantic schema for LangChain tool arguments
    class ArgsSchema(BaseModel):
        file_id: str = Field(
            description="UUID of the file to generate presigned URL for. "
            "Use QueryUserSessions or list files to find file_id."
        )
        expiry_seconds: Optional[int] = Field(
            default=3600,
            ge=1,
            le=86400,
            description="Time-to-live in seconds (default: 3600 = 1 hour, max: 86400 = 24 hours)",
        )
        disposition: Optional[str] = Field(
            default=None,
            description='Content-Disposition type: "inline" (browser display) or "attachment" (download). '
            'Defaults to "inline" for images/SVG/PDF, "attachment" for other files.',
        )

    @staticmethod
    async def execute(
        file_id: str,
        expiry_seconds: Optional[int] = 3600,
        disposition: Optional[str] = None,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        groups: Optional[list] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute presigned URL generation.

        Args:
            file_id: UUID of the file
            expiry_seconds: Time-to-live in seconds (1-86400)
            disposition: Content-Disposition type ("inline" or "attachment")
            user_id: User UUID (from context)
            username: Username (from context)
            groups: User groups (from context)
            **kwargs: Additional context parameters

        Returns:
            Dict with success status and presigned URL or error message
        """
        from ..security.presigned_url import get_presigned_url_manager

        logger.info(
            f"GeneratePresignedURL.execute called: file_id={file_id}, "
            f"expiry_seconds={expiry_seconds}, disposition={disposition}, "
            f"user_id={user_id}, username={username}"
        )

        try:
            # Validate required user context
            if not user_id or not username:
                error_msg = "User context missing (user_id and username required)"
                logger.error(f"GeneratePresignedURL error: {error_msg}")
                return {"success": False, "error": error_msg}

            # Validate expiry_seconds range
            if expiry_seconds is not None:
                if expiry_seconds < 1 or expiry_seconds > 86400:
                    error_msg = f"expiry_seconds must be between 1 and 86400 (24 hours), got {expiry_seconds}"
                    logger.error(f"GeneratePresignedURL error: {error_msg}")
                    return {"success": False, "error": error_msg}

            # Validate file exists and retrieve metadata (using shared Redis pool)
            redis_pool = await get_files_redis_client()
            file_key = get_file_key(file_id)
            file_metadata_json = await redis_pool.get(file_key)

            if not file_metadata_json:
                error_msg = "File not found"
                logger.warning(f"GeneratePresignedURL error: file_id={file_id} - {error_msg}")
                return {"success": False, "error": error_msg}

            try:
                file_metadata = json.loads(file_metadata_json)
            except json.JSONDecodeError as e:
                error_msg = "File metadata is corrupted"
                logger.error(
                    f"GeneratePresignedURL error: file_id={file_id} - {error_msg}, error={e}"
                )
                return {"success": False, "error": error_msg}

            # Verify user owns the file
            file_owner_id = file_metadata.get("owner_id")

            if not file_owner_id:
                error_msg = "File metadata is missing ownership information"
                logger.error(
                    f"GeneratePresignedURL error: file_id={file_id} - {error_msg}, "
                    f"metadata_keys={list(file_metadata.keys())}"
                )
                return {"success": False, "error": error_msg}

            if file_owner_id != user_id:
                error_msg = "You do not have permission to access this file"
                logger.warning(
                    f"GeneratePresignedURL error: file_id={file_id} - {error_msg}, "
                    f"owner={file_owner_id}, requester={user_id}"
                )
                return {"success": False, "error": error_msg}

            # Generate HMAC token using PresignedURLManager
            manager = get_presigned_url_manager()
            token, expires_ts = manager.generate_token(
                file_id=file_id, user_id=user_id, expiry_seconds=expiry_seconds
            )

            # ENHANCED: Accept full base_url_override from request context
            base_url_override = kwargs.get("base_url_override")  # NEW: Full base URL with scheme/host/port

            if base_url_override:
                # Use provided base URL (includes scheme, host, port)
                base_url = base_url_override.rstrip("/")
                logger.debug(f"[PRESIGNED_URL] Using base_url_override: {base_url}")
            else:
                # Fallback to environment variable or default
                base_url = os.getenv("NGINX_EXTERNAL_URL", "https://api.agentic.local").rstrip("/")
                logger.debug(f"[PRESIGNED_URL] Using fallback base_url: {base_url}")

            # Parse to extract components
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            scheme = parsed.scheme or "https"
            host_with_port = parsed.netloc or "api.agentic.local"

            presigned_url = f"{scheme}://{host_with_port}/v1/files/{file_id}/download?token={token}&expires={expires_ts}"

            current_ts = int(time.time())
            expires_in = expires_ts - current_ts

            logger.info(
                f"GeneratePresignedURL success: file_id={file_id}, "
                f"expires_in={expires_in}s, "
                f"url={presigned_url[:80]}..."
            )

            return {
                "success": True,
                "presigned_url": presigned_url,
                "expires_at": expires_ts,
                "expires_in": expires_in,
                "file_id": file_id,
            }

        except Exception as e:
            error_msg = f"Unexpected error generating presigned URL: {str(e)}"
            logger.error(
                f"GeneratePresignedURL exception: {error_msg}", exc_info=True
            )
            return {"success": False, "error": error_msg}
