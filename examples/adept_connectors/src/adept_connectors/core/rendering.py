"""Image rendering abstractions for ADEPT Connectors.

Provides a protocol-agnostic way to handle images across different
connector UIs (Claude Desktop, ChatGPT, markdown-based tools, etc.).

Each connector implements its own ImageRenderer:
- Claude Desktop: wraps ImageData → fastmcp.Image (MCP image content blocks)
- ChatGPT: stores bytes in a cache, returns proxy URL for markdown embedding
- Markdown/generic: returns markdown image syntax with data URIs or URLs
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

# Matches presigned download URLs and plot URLs from ADEPT responses.
# Captures: /v1/files/{id}/download?token=...&expires=... and /v1/plots/...
IMAGE_URL_RE = re.compile(
    r"(https?://[^\s\"'<>]+/v1/(?:files/[^\s\"'<>]+/download\?[^\s\"'<>]+|plots/[^\s\"'<>]+\.(?:png|jpg|jpeg|gif|webp|svg)))",
    re.IGNORECASE,
)

MAX_AUTO_IMAGES = 5

MIME_TO_FORMAT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg+xml",
}


@dataclass
class ImageData:
    """Protocol-agnostic image representation.

    Holds raw bytes + metadata. Each connector's ImageRenderer converts
    this to the appropriate output format.
    """

    data: bytes
    mime_type: str
    source_url: str = ""

    @property
    def format(self) -> str:
        """Short format name (png, jpeg, etc.) for renderers that need it."""
        return MIME_TO_FORMAT.get(self.mime_type, "png")

    @property
    def size_bytes(self) -> int:
        return len(self.data)


class ImageRenderer(Protocol):
    """Protocol for rendering ImageData to connector-specific output.

    Each connector implements this to convert ImageData to the format
    its UI expects (MCP Image blocks, markdown syntax, proxy URLs, etc.).
    """

    def render(self, image: ImageData) -> Any:
        """Convert ImageData to connector-specific output."""
        ...

    def render_with_text(self, text: str, images: list[ImageData]) -> Any:
        """Render text + images together in the connector's format.

        The default implementation appends rendered images after the text.
        Connectors may override for richer formatting.
        """
        ...


class MarkdownRenderer:
    """Default renderer: inline images as markdown with base64 data URIs.

    Suitable for tools that render markdown (Roo Code, Continue.dev, etc.).
    Falls back to URL references when data URI would be too large (>1MB).
    """

    MAX_DATA_URI_BYTES = 1 * 1024 * 1024  # 1 MB

    def render(self, image: ImageData) -> str:
        """Render a single image as markdown."""
        if image.size_bytes <= self.MAX_DATA_URI_BYTES:
            b64 = base64.b64encode(image.data).decode("ascii")
            return f"![plot](data:{image.mime_type};base64,{b64})"
        # Too large for data URI — use source URL if available
        if image.source_url:
            return f"![plot]({image.source_url})"
        return f"[Image: {image.size_bytes} bytes, {image.mime_type}]"

    def render_with_text(self, text: str, images: list[ImageData]) -> str:
        """Render text followed by markdown image blocks."""
        if not images:
            return text
        parts = [text]
        for img in images:
            parts.append(self.render(img))
        return "\n\n".join(parts)


def extract_image_urls(text: str) -> list[str]:
    """Extract unique artifact/image URLs from response text, preserving order."""
    return list(dict.fromkeys(IMAGE_URL_RE.findall(text)))


# Alias — the regex matches all presigned download URLs, not only images.
extract_artifact_urls = extract_image_urls
