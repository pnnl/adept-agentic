"""Tests for rendering module — ImageData, MarkdownRenderer, URL extraction."""

import pytest

from adept_connectors.core.rendering import (
    ImageData,
    MarkdownRenderer,
    extract_image_urls,
    IMAGE_URL_RE,
    MIME_TO_FORMAT,
)


class TestImageData:

    def test_basic_properties(self):
        img = ImageData(data=b"\x89PNG", mime_type="image/png", source_url="http://example.com/plot.png")
        assert img.format == "png"
        assert img.size_bytes == 4
        assert img.source_url == "http://example.com/plot.png"

    def test_jpeg_format(self):
        img = ImageData(data=b"jfif", mime_type="image/jpeg")
        assert img.format == "jpeg"

    def test_unknown_mime_defaults_to_png(self):
        img = ImageData(data=b"data", mime_type="image/tiff")
        assert img.format == "png"

    def test_empty_source_url(self):
        img = ImageData(data=b"data", mime_type="image/png")
        assert img.source_url == ""


class TestMarkdownRenderer:

    def test_small_image_as_data_uri(self):
        renderer = MarkdownRenderer()
        img = ImageData(data=b"\x89PNG\r\n", mime_type="image/png")
        result = renderer.render(img)
        assert result.startswith("![plot](data:image/png;base64,")

    def test_large_image_uses_source_url(self):
        renderer = MarkdownRenderer()
        large_data = b"x" * (2 * 1024 * 1024)  # 2MB
        img = ImageData(data=large_data, mime_type="image/png", source_url="http://example.com/big.png")
        result = renderer.render(img)
        assert result == "![plot](http://example.com/big.png)"

    def test_large_image_no_url_fallback(self):
        renderer = MarkdownRenderer()
        large_data = b"x" * (2 * 1024 * 1024)
        img = ImageData(data=large_data, mime_type="image/png")
        result = renderer.render(img)
        assert "2097152 bytes" in result

    def test_render_with_text_no_images(self):
        renderer = MarkdownRenderer()
        result = renderer.render_with_text("Hello world", [])
        assert result == "Hello world"

    def test_render_with_text_and_images(self):
        renderer = MarkdownRenderer()
        img = ImageData(data=b"\x89PNG", mime_type="image/png")
        result = renderer.render_with_text("Here is a plot:", [img])
        assert "Here is a plot:" in result
        assert "data:image/png;base64," in result


class TestExtractImageUrls:

    def test_presigned_download_url(self):
        text = "Here is the file: http://localhost:8083/v1/files/abc123/download?token=xyz&expires=99999"
        urls = extract_image_urls(text)
        assert len(urls) == 1
        assert "files/abc123/download" in urls[0]

    def test_plot_url(self):
        text = "Plot: http://gateway:8083/v1/plots/session123/chart.png"
        urls = extract_image_urls(text)
        assert len(urls) == 1
        assert "plots/session123/chart.png" in urls[0]

    def test_multiple_urls_deduped(self):
        url = "http://gw:8083/v1/plots/s1/plot.png"
        text = f"First: {url} and again: {url}"
        urls = extract_image_urls(text)
        assert len(urls) == 1

    def test_no_urls(self):
        text = "No images here, just text."
        urls = extract_image_urls(text)
        assert len(urls) == 0

    def test_https_url(self):
        text = "Plot: https://your-adept-host.example.com/v1/plots/sess/output.jpeg"
        urls = extract_image_urls(text)
        assert len(urls) == 1

    def test_various_extensions(self):
        for ext in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
            text = f"http://gw:8083/v1/plots/s1/chart.{ext}"
            urls = extract_image_urls(text)
            assert len(urls) == 1, f"Failed for extension: {ext}"
