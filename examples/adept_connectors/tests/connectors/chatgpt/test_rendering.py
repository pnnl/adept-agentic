"""Tests for ChatGPT image rendering and caching."""

from __future__ import annotations

import time

import pytest

from adept_connectors.connectors.chatgpt.rendering import (
    ChatGPTImageRenderer,
    ImageCache,
)
from adept_connectors.core.rendering import ImageData


# ── ImageCache tests ────────────────────────────────────────────────


class TestImageCache:
    """Tests for the in-memory image cache."""

    def test_store_and_retrieve(self, image_cache, sample_image_data):
        token = image_cache.store(sample_image_data)
        assert len(token) == 24
        retrieved = image_cache.get(token)
        assert retrieved is not None
        assert retrieved.data == sample_image_data.data
        assert retrieved.mime_type == "image/png"

    def test_store_returns_deterministic_token(self, image_cache, sample_image_data):
        """Same image content + URL → same token (dedup)."""
        token1 = image_cache.store(sample_image_data)
        token2 = image_cache.store(sample_image_data)
        assert token1 == token2

    def test_store_different_images_get_different_tokens(self, image_cache):
        img1 = ImageData(data=b"image1", mime_type="image/png", source_url="url1")
        img2 = ImageData(data=b"image2", mime_type="image/png", source_url="url2")
        t1 = image_cache.store(img1)
        t2 = image_cache.store(img2)
        assert t1 != t2

    def test_get_missing_returns_none(self, image_cache):
        assert image_cache.get("nonexistent") is None

    def test_ttl_expiration(self):
        cache = ImageCache(max_size=10, ttl_seconds=1)
        img = ImageData(data=b"expiring", mime_type="image/png")
        token = cache.store(img)
        assert cache.get(token) is not None

        # Wait for TTL expiry
        time.sleep(1.1)
        assert cache.get(token) is None

    def test_max_size_eviction(self):
        cache = ImageCache(max_size=3, ttl_seconds=300)
        tokens = []
        for i in range(5):
            img = ImageData(data=f"img{i}".encode(), mime_type="image/png", source_url=f"url{i}")
            tokens.append(cache.store(img))

        # First 2 should be evicted
        assert cache.get(tokens[0]) is None
        assert cache.get(tokens[1]) is None
        # Last 3 should be present
        assert cache.get(tokens[2]) is not None
        assert cache.get(tokens[3]) is not None
        assert cache.get(tokens[4]) is not None

    def test_lru_refresh_on_access(self):
        cache = ImageCache(max_size=3, ttl_seconds=300)
        img0 = ImageData(data=b"img0", mime_type="image/png", source_url="url0")
        img1 = ImageData(data=b"img1", mime_type="image/png", source_url="url1")
        img2 = ImageData(data=b"img2", mime_type="image/png", source_url="url2")
        img3 = ImageData(data=b"img3", mime_type="image/png", source_url="url3")

        t0 = cache.store(img0)
        t1 = cache.store(img1)
        t2 = cache.store(img2)

        # Access t0 to refresh its LRU position
        cache.get(t0)

        # Store t3 — should evict t1 (oldest un-accessed), not t0
        cache.store(img3)
        assert cache.get(t0) is not None  # refreshed, still present
        assert cache.get(t1) is None  # evicted

    def test_purge_expired(self):
        cache = ImageCache(max_size=10, ttl_seconds=1)
        for i in range(5):
            cache.store(ImageData(data=f"img{i}".encode(), mime_type="image/png", source_url=f"url{i}"))

        assert cache.size == 5
        time.sleep(1.1)
        purged = cache.purge_expired()
        assert purged == 5
        assert cache.size == 0

    def test_size_property(self, image_cache, sample_image_data):
        assert image_cache.size == 0
        image_cache.store(sample_image_data)
        assert image_cache.size == 1


# ── ChatGPTImageRenderer tests ──────────────────────────────────────


class TestChatGPTImageRenderer:
    """Tests for the ChatGPT-specific image renderer."""

    def test_render_returns_proxy_url(self, image_cache, sample_image_data):
        renderer = ChatGPTImageRenderer(
            cache=image_cache, base_url="http://localhost:8090"
        )
        url = renderer.render(sample_image_data)
        assert url.startswith("http://localhost:8090/v1/images/")
        assert len(url.split("/")[-1]) == 24  # token length

    def test_render_stores_in_cache(self, image_cache, sample_image_data):
        renderer = ChatGPTImageRenderer(
            cache=image_cache, base_url="http://localhost:8090"
        )
        url = renderer.render(sample_image_data)
        token = url.split("/")[-1]
        assert image_cache.get(token) is not None

    def test_render_with_text_no_images(self, image_cache):
        renderer = ChatGPTImageRenderer(
            cache=image_cache, base_url="http://localhost:8090"
        )
        result = renderer.render_with_text("Hello", [])
        assert result == "Hello"

    def test_render_with_text_and_images(self, image_cache, sample_image_data):
        renderer = ChatGPTImageRenderer(
            cache=image_cache, base_url="http://localhost:8090"
        )
        result = renderer.render_with_text("Analysis complete.", [sample_image_data])
        assert "Analysis complete." in result
        assert "![plot](http://localhost:8090/v1/images/" in result

    def test_render_with_text_multiple_images(self, image_cache):
        renderer = ChatGPTImageRenderer(
            cache=image_cache, base_url="http://localhost:8090"
        )
        images = [
            ImageData(data=f"img{i}".encode(), mime_type="image/png", source_url=f"url{i}")
            for i in range(3)
        ]
        result = renderer.render_with_text("Results:", images)
        assert result.count("![plot]") == 3

    def test_render_strips_trailing_slash(self, image_cache, sample_image_data):
        renderer = ChatGPTImageRenderer(
            cache=image_cache, base_url="http://localhost:8090/"
        )
        url = renderer.render(sample_image_data)
        assert "//v1/" not in url  # No double slash

    def test_render_deterministic(self, image_cache, sample_image_data):
        renderer = ChatGPTImageRenderer(
            cache=image_cache, base_url="http://localhost:8090"
        )
        url1 = renderer.render(sample_image_data)
        url2 = renderer.render(sample_image_data)
        assert url1 == url2  # Same image → same token → same URL
