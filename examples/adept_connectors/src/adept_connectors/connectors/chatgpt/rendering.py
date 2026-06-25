"""ChatGPT-specific image rendering.

Stores fetched image bytes in a short-lived in-memory cache and returns
proxy URLs that ChatGPT can embed as markdown ``![plot](url)``. The
``/v1/images/{token}`` route in ``routes/images.py`` serves the bytes.

This avoids exposing ADEPT-internal presigned URLs to ChatGPT's servers
and works around the fact that ChatGPT cannot reach ADEPT endpoints directly.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from ...core.rendering import ImageData

logger = logging.getLogger(__name__)


@dataclass
class _CachedImage:
    """In-memory cached image with expiration."""

    image: ImageData
    created_at: float = field(default_factory=time.time)
    access_count: int = 0


class ImageCache:
    """Thread-safe, TTL-bounded, LRU image cache.

    Used by ChatGPTImageRenderer to store fetched image bytes and
    by the ``/v1/images/{token}`` route to serve them.
    """

    def __init__(self, max_size: int = 200, ttl_seconds: int = 600) -> None:
        self._cache: OrderedDict[str, _CachedImage] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def store(self, image: ImageData) -> str:
        """Store an image and return a cache token.

        Token is a hex digest of the image content + source URL,
        ensuring identical images get the same token (dedup).
        """
        hasher = hashlib.sha256()
        hasher.update(image.data[:4096])  # First 4KB for speed
        hasher.update(image.source_url.encode())
        token = hasher.hexdigest()[:24]

        with self._lock:
            # Move to end if already exists (LRU refresh)
            if token in self._cache:
                self._cache.move_to_end(token)
                return token

            # Evict oldest if at capacity
            while len(self._cache) >= self._max_size:
                evicted_token, _ = self._cache.popitem(last=False)
                logger.debug("Evicted image cache entry: %s", evicted_token)

            self._cache[token] = _CachedImage(image=image)

        return token

    def get(self, token: str) -> Optional[ImageData]:
        """Retrieve an image by token, or None if expired/missing."""
        with self._lock:
            entry = self._cache.get(token)
            if entry is None:
                return None

            # Check TTL
            if time.time() - entry.created_at > self._ttl:
                del self._cache[token]
                logger.debug("Image cache entry expired: %s", token)
                return None

            entry.access_count += 1
            self._cache.move_to_end(token)
            return entry.image

    def purge_expired(self) -> int:
        """Remove all expired entries. Returns count of purged entries."""
        now = time.time()
        purged = 0
        with self._lock:
            expired = [
                t for t, e in self._cache.items()
                if now - e.created_at > self._ttl
            ]
            for t in expired:
                del self._cache[t]
                purged += 1
        return purged

    @property
    def size(self) -> int:
        return len(self._cache)


class ChatGPTImageRenderer:
    """Renders images as proxy URLs for ChatGPT markdown embedding.

    ChatGPT custom GPTs render markdown images: ``![alt](url)``.
    This renderer stores image bytes in an ``ImageCache`` and returns
    a URL like ``http://host:8090/v1/images/abc123def456`` that the
    ``/v1/images/{token}`` route serves with the correct Content-Type.

    Args:
        cache: Shared ImageCache instance.
        base_url: Public base URL of the connector (e.g. ``http://host:8090``).
    """

    def __init__(self, cache: ImageCache, base_url: str) -> None:
        self._cache = cache
        self._base_url = base_url.rstrip("/")

    def render(self, image: ImageData) -> str:
        """Store image and return proxy URL."""
        token = self._cache.store(image)
        return f"{self._base_url}/v1/images/{token}"

    def render_with_text(self, text: str, images: list[ImageData]) -> str:
        """Render text with inline markdown image links."""
        if not images:
            return text
        parts = [text]
        for img in images:
            url = self.render(img)
            parts.append(f"![plot]({url})")
        return "\n\n".join(parts)
