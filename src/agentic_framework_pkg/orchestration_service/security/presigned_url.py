"""Presigned URL Security Module

HMAC-SHA256 token generation and validation for time-limited file downloads.
"""

import hashlib
import hmac
import os
import secrets
import time
from typing import Optional, Tuple

from agentic_framework_pkg.logger_config import get_logger

logger = get_logger(__name__)


class PresignedURLManager:
    """Manages generation and validation of presigned file download URLs."""

    def __init__(self, secret_key: Optional[str] = None):
        """Initialize with HMAC secret key.

        Args:
            secret_key: Base64-encoded secret key (min 32 bytes).
                       Falls back to PRESIGNED_URL_SECRET env var.
        """
        self.secret_key = (
            secret_key
            or os.getenv("PRESIGNED_URL_SECRET")
            or self._generate_default_secret()
        )

        if len(self.secret_key) < 32:
            raise ValueError("PRESIGNED_URL_SECRET must be at least 32 characters")

        self.default_ttl_seconds = int(
            os.getenv("PRESIGNED_URL_DEFAULT_TTL", "3600")
        )  # 1 hour
        self.max_ttl_seconds = int(
            os.getenv("PRESIGNED_URL_MAX_TTL", "86400")
        )  # 24 hours

    def _generate_default_secret(self) -> str:
        """Generate secure random secret if none provided."""
        logger.warning(
            "PRESIGNED_URL_SECRET not set - generating random secret. "
            "URLs will be invalidated on service restart."
        )
        return secrets.token_urlsafe(32)

    def generate_token(
        self,
        file_id: str,
        user_id: str,
        expiry_seconds: Optional[int] = None,
        nonce: Optional[str] = None,
    ) -> Tuple[str, int]:
        """Generate HMAC-signed token for file download.

        Args:
            file_id: File UUID
            user_id: User UUID (for audit trail)
            expiry_seconds: TTL in seconds (default: 1 hour, max: 24 hours)
            nonce: Optional nonce for single-use tokens

        Returns:
            Tuple of (token, expires_timestamp)
        """
        expiry_seconds = expiry_seconds or self.default_ttl_seconds
        if expiry_seconds > self.max_ttl_seconds:
            raise ValueError(
                f"expiry_seconds exceeds max TTL of {self.max_ttl_seconds}"
            )

        expires_ts = int(time.time()) + expiry_seconds
        nonce = nonce or secrets.token_hex(8)  # 16-char hex string

        # HMAC-SHA256(secret, file_id || user_id || expires_ts || nonce)
        message = f"{file_id}:{user_id}:{expires_ts}:{nonce}"
        signature = hmac.new(
            self.secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # Token format: {signature}:{nonce}
        token = f"{signature}:{nonce}"

        logger.info(
            f"Generated presigned URL token for file_id={file_id}, user_id={user_id}, "
            f"expires_at={expires_ts} ({expiry_seconds}s TTL)"
        )
        logger.debug(
            f"[PRESIGNED_DEBUG] Generated token: signature={signature[:16]}..., "
            f"nonce={nonce}, full_token_length={len(token)}, has_colon={':' in token}"
        )

        return token, expires_ts

    def validate_token(
        self, file_id: str, user_id: str, token: str, expires_ts: int
    ) -> Tuple[bool, Optional[str]]:
        """Validate HMAC-signed token with constant-time comparison.

        Args:
            file_id: File UUID from URL path
            user_id: User UUID from file metadata
            token: Token from URL query parameter (format: {signature}:{nonce})
            expires_ts: Expiration timestamp from URL query parameter

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check expiration first (fast rejection)
        current_ts = int(time.time())
        if current_ts > expires_ts:
            time_diff = current_ts - expires_ts
            logger.warning(
                f"Presigned URL expired: file_id={file_id}, expired {time_diff}s ago"
            )
            return False, f"Token expired {time_diff} seconds ago"

        # Parse token
        logger.debug(
            f"[PRESIGNED_DEBUG] Validating token: file_id={file_id}, "
            f"token_length={len(token)}, has_colon={':' in token}, token_preview={token[:80]}..."
        )
        try:
            signature, nonce = token.split(":", 1)
        except ValueError:
            logger.warning(
                f"Invalid token format: file_id={file_id}, token={token[:100]}..., "
                f"has_colon={':' in token}"
            )
            return False, "Invalid token format"

        # Recompute expected signature
        message = f"{file_id}:{user_id}:{expires_ts}:{nonce}"
        expected_signature = hmac.new(
            self.secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # Constant-time comparison (prevent timing attacks)
        is_valid = hmac.compare_digest(signature, expected_signature)

        if not is_valid:
            logger.warning(
                f"Invalid HMAC signature: file_id={file_id}, user_id={user_id}"
            )
            return False, "Invalid or tampered token"

        logger.info(
            f"Validated presigned URL token: file_id={file_id}, user_id={user_id}, "
            f"expires_in={(expires_ts - current_ts)}s"
        )
        return True, None


# Global singleton (initialized at service startup)
_presigned_url_manager: Optional[PresignedURLManager] = None


def get_presigned_url_manager() -> PresignedURLManager:
    """Get or create global PresignedURLManager singleton."""
    global _presigned_url_manager
    if _presigned_url_manager is None:
        _presigned_url_manager = PresignedURLManager()
    return _presigned_url_manager
