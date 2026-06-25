"""File upload/list/download client for ADEPT Files API."""

from __future__ import annotations

import logging
import mimetypes as _mimetypes
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from .base import BaseAdeptClient

logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 50 * 1024 * 1024  # 50 MB

_MIME_TO_FORMAT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg+xml",
}

# MIME types that represent human-readable text content.
_TEXT_MIME_TYPES: frozenset[str] = frozenset({
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
})


def _detect_mime_type(url: str, content_type_header: Optional[str]) -> Optional[str]:
    """Detect MIME type from Content-Type header or URL extension.

    Returns the MIME type string if detected, or None if the content type
    cannot be determined.  Callers that only want images should check
    ``mime.startswith("image/")``.
    """
    if content_type_header:
        mime = content_type_header.split(";")[0].strip().lower()
        # Return the actual MIME type — let callers decide if it's acceptable
        if mime and mime != "application/octet-stream":
            return mime
    path = urlparse(url).path
    guessed, _ = _mimetypes.guess_type(path, strict=False)
    if guessed:
        return guessed
    return None


class FilesClient:
    """Client for ADEPT file operations."""

    def __init__(self, base_client: BaseAdeptClient) -> None:
        self._client = base_client

    async def upload(
        self,
        file_path: Optional[str] = None,
        purpose: str = "assistants",
        session_id: Optional[str] = None,
        *,
        file_data: Optional[str] = None,
        file_name: Optional[str] = None,
        file_uri: Optional[str] = None,
    ) -> dict[str, Any]:
        """Upload a file to ADEPT.

        Three input modes (exactly one required):
          1. file_path — read from local filesystem
          2. file_data — base64-encoded content (with file_name)
          3. file_uri  — file:// URI to resolve and read

        Args:
            file_path: Local path to the file.
            purpose: Upload purpose (default: assistants).
            session_id: Optional session ID for scoping.
            file_data: Base64-encoded file content (alternative to file_path).
            file_name: Filename when using file_data (required with file_data).
            file_uri: file:// URI to resolve (e.g. from MCP ResourceLink).

        Returns:
            Dict with file_id, filename, bytes, purpose, etc.
        """
        import base64

        # Resolve input to (filename, raw_bytes)
        sources = sum(1 for s in (file_path, file_data, file_uri) if s)
        if sources == 0:
            raise ValueError(
                "Provide exactly one of: file_path, file_data, or file_uri"
            )
        if sources > 1:
            raise ValueError(
                "Provide only one of: file_path, file_data, or file_uri"
            )

        if file_path:
            path = Path(file_path).resolve()
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            name = path.name
            content = path.read_bytes()
        elif file_data:
            if not file_name:
                raise ValueError("file_name is required when using file_data")
            name = file_name
            try:
                content = base64.b64decode(file_data)
            except Exception:
                raise ValueError(
                    "file_data is not valid base64. If the file is large "
                    "(>10KB), it may have been truncated by the tool call "
                    "layer. Use file_path or file_uri instead."
                )
        elif file_uri:
            parsed = urlparse(file_uri)
            if parsed.scheme != "file":
                raise ValueError(
                    f"Only file:// URIs supported, got: {parsed.scheme}://"
                )
            path = Path(parsed.path).resolve()
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            name = path.name
            content = path.read_bytes()

        # Build multipart form data
        files = {"file": (name, content)}
        data: dict[str, str] = {"purpose": purpose}
        if session_id:
            data["session_id"] = session_id

        # Override Content-Type for multipart (base sets application/json)
        client = await self._client._ensure_client()
        headers = await self._client._auth.get_auth_headers()

        resp = await client.post("/files", files=files, data=data, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def download_bytes(
        self,
        url: str,
        max_bytes: int = _MAX_IMAGE_BYTES,
    ) -> tuple[bytes, Optional[str]]:
        """Download raw bytes from a URL.

        For presigned URLs (self-authenticating) or plot_urls.
        Auth headers are included but harmless on presigned endpoints.

        Args:
            url: Absolute URL or path relative to base_url.
            max_bytes: Maximum response size (default 50 MB).

        Returns:
            Tuple of (raw_bytes, mime_type).  mime_type is None if
            the content type could not be determined.
        """
        if url.startswith(("http://", "https://")):
            # Absolute URL — use raw httpx client to avoid base_url joining
            client = await self._client._ensure_client()
            headers = await self._client._auth.get_auth_headers()
            resp = await client.get(url, headers=headers, follow_redirects=True)
        else:
            resp = await self._client.get(url, follow_redirects=True)

        resp.raise_for_status()

        content_length = resp.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError(
                f"Image too large: {int(content_length)} bytes (limit: {max_bytes})"
            )
        data = resp.content
        if len(data) > max_bytes:
            raise ValueError(
                f"Image too large: {len(data)} bytes (limit: {max_bytes})"
            )

        mime_type = _detect_mime_type(url, resp.headers.get("content-type"))
        return data, mime_type

    async def fetch_artifact(
        self,
        url: str,
        max_bytes: int = _MAX_IMAGE_BYTES,
    ) -> tuple[bytes, Optional[str], str]:
        """Download an artifact and classify by MIME type.

        Higher-level wrapper around :meth:`download_bytes` that categorises
        the downloaded content so callers can route to the correct
        renderer/embedder.

        Returns:
            Tuple of ``(raw_bytes, mime_type, category)`` where *category*
            is one of ``"image"``, ``"text"``, or ``"binary"``.
        """
        data, mime_type = await self.download_bytes(url, max_bytes)
        if mime_type and mime_type.startswith("image/"):
            category = "image"
        elif mime_type and (
            mime_type.startswith("text/") or mime_type in _TEXT_MIME_TYPES
        ):
            category = "text"
        else:
            category = "binary"
        return data, mime_type, category

    async def list_files(
        self, session_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """List files, optionally filtered by session."""
        params = {}
        if session_id:
            params["session_id"] = session_id
        resp = await self._client.get("/files", params=params)
        resp.raise_for_status()
        result = resp.json()
        # Handle both {"data": [...]} and direct list responses
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        if isinstance(result, list):
            return result
        return []
