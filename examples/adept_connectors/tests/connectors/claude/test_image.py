"""Tests for MCP image content block support — download_bytes, MIME detection, adept_get_image, auto-fetch."""

import httpx
import pytest
import respx

from adept_connectors.core.auth import AuthManager
from adept_connectors.core.clients.base import BaseAdeptClient
from adept_connectors.core.clients.files_client import (
    FilesClient,
    _MIME_TO_FORMAT,
    _MAX_IMAGE_BYTES,
    _detect_mime_type,
)
from adept_connectors.core.config import AdeptConnectorConfig


# -- Fixtures ----------------------------------------------------------------

@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
    monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
    monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")
    return AdeptConnectorConfig()


@pytest.fixture
def base_client(config):
    return BaseAdeptClient(config, AuthManager(config))


@pytest.fixture
def client(base_client):
    return FilesClient(base_client)


# 1x1 red PNG pixel (67 bytes)
PNG_PIXEL = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


# -- TestMimeDetection -------------------------------------------------------

class TestMimeDetection:

    def test_content_type_header_png(self):
        assert _detect_mime_type("http://x/img", "image/png") == "image/png"

    def test_content_type_header_jpeg(self):
        assert _detect_mime_type("http://x/img", "image/jpeg") == "image/jpeg"

    def test_content_type_header_with_charset(self):
        assert _detect_mime_type("http://x/img", "image/png; charset=utf-8") == "image/png"

    def test_octet_stream_falls_back_to_url(self):
        result = _detect_mime_type("http://x/plot.jpeg", "application/octet-stream")
        assert result == "image/jpeg"

    def test_url_extension_png(self):
        assert _detect_mime_type("http://x/plot.png", None) == "image/png"

    def test_url_extension_gif(self):
        assert _detect_mime_type("http://x/anim.gif", None) == "image/gif"

    def test_url_extension_webp(self):
        assert _detect_mime_type("http://x/photo.webp", None) == "image/webp"

    def test_url_with_query_params(self):
        result = _detect_mime_type(
            "http://x/v1/files/abc/download?token=xyz&expires=123",
            None,
        )
        assert result is None

    def test_unknown_returns_none(self):
        assert _detect_mime_type("http://x/blob", None) is None

    def test_text_plain_content_type(self):
        assert _detect_mime_type("http://x/file", "text/plain") == "text/plain"

    def test_application_json_content_type(self):
        assert _detect_mime_type("http://x/data", "application/json") == "application/json"

    def test_csv_url_extension(self):
        assert _detect_mime_type("http://x/data.csv", None) == "text/csv"

    def test_svg_content_type(self):
        assert _detect_mime_type("http://x/img", "image/svg+xml") == "image/svg+xml"


# -- TestMimeToFormat --------------------------------------------------------

class TestMimeToFormat:

    def test_png_format(self):
        assert _MIME_TO_FORMAT["image/png"] == "png"

    def test_jpeg_format(self):
        assert _MIME_TO_FORMAT["image/jpeg"] == "jpeg"

    def test_gif_format(self):
        assert _MIME_TO_FORMAT["image/gif"] == "gif"

    def test_webp_format(self):
        assert _MIME_TO_FORMAT["image/webp"] == "webp"

    def test_svg_format(self):
        assert _MIME_TO_FORMAT["image/svg+xml"] == "svg+xml"

    def test_unknown_mime_fallback(self):
        assert "image/bmp" not in _MIME_TO_FORMAT


# -- TestDownloadBytes -------------------------------------------------------

class TestDownloadBytes:

    @pytest.mark.asyncio
    @respx.mock
    async def test_absolute_url(self, client):
        url = "https://adept.example.com/v1/files/abc/download?token=xyz"
        respx.get(url).mock(
            return_value=httpx.Response(
                200, content=PNG_PIXEL, headers={"content-type": "image/png"},
            )
        )
        data, mime = await client.download_bytes(url)
        assert data == PNG_PIXEL
        assert mime == "image/png"

    @pytest.mark.asyncio
    @respx.mock
    async def test_relative_path(self, client, config):
        respx.get(f"{config.base_url}/files/abc/download").mock(
            return_value=httpx.Response(
                200, content=PNG_PIXEL, headers={"content-type": "image/png"},
            )
        )
        data, mime = await client.download_bytes("/files/abc/download")
        assert data == PNG_PIXEL
        assert mime == "image/png"

    @pytest.mark.asyncio
    @respx.mock
    async def test_size_guard_content_length(self, client):
        url = "https://adept.example.com/huge.png"
        respx.get(url).mock(
            return_value=httpx.Response(
                200, content=b"x" * 100,
                headers={"content-type": "image/png", "content-length": str(_MAX_IMAGE_BYTES + 1)},
            )
        )
        with pytest.raises(ValueError, match="Image too large"):
            await client.download_bytes(url)

    @pytest.mark.asyncio
    @respx.mock
    async def test_size_guard_actual_bytes(self, client):
        url = "https://adept.example.com/huge.png"
        respx.get(url).mock(
            return_value=httpx.Response(200, content=b"x" * 101, headers={"content-type": "image/png"})
        )
        with pytest.raises(ValueError, match="Image too large"):
            await client.download_bytes(url, max_bytes=100)

    @pytest.mark.asyncio
    @respx.mock
    async def test_mime_from_url_extension(self, client):
        url = "https://adept.example.com/plot.jpeg"
        respx.get(url).mock(
            return_value=httpx.Response(200, content=b"\xff\xd8\xff", headers={"content-type": "application/octet-stream"})
        )
        _, mime = await client.download_bytes(url)
        assert mime == "image/jpeg"

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_mime_returns_none(self, client):
        url = "https://adept.example.com/v1/files/abc/download?token=xyz"
        respx.get(url).mock(return_value=httpx.Response(200, content=PNG_PIXEL))
        _, mime = await client.download_bytes(url)
        assert mime is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_http_error_raises(self, client):
        url = "https://adept.example.com/missing.png"
        respx.get(url).mock(return_value=httpx.Response(404))
        with pytest.raises(httpx.HTTPStatusError):
            await client.download_bytes(url)

    @pytest.mark.asyncio
    @respx.mock
    async def test_follow_redirects(self, client):
        url = "https://adept.example.com/redirect.png"
        final_url = "https://cdn.example.com/actual.png"
        respx.get(url).mock(return_value=httpx.Response(302, headers={"location": final_url}))
        respx.get(final_url).mock(
            return_value=httpx.Response(200, content=PNG_PIXEL, headers={"content-type": "image/png"})
        )
        data, mime = await client.download_bytes(url)
        assert data == PNG_PIXEL


# -- TestAdeptGetImage (tool-level) ------------------------------------------

class TestAdeptGetImage:

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_image_on_success(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        from fastmcp.utilities.types import Image

        url = "https://adept.example.com/v1/files/abc/download?token=xyz"
        respx.get(url).mock(
            return_value=httpx.Response(200, content=PNG_PIXEL, headers={"content-type": "image/png"})
        )

        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")

        cfg = AdeptConnectorConfig()
        auth = AuthManager(cfg)
        base_client = BaseAdeptClient(cfg, auth)
        mock_ctx = MagicMock()
        mock_ctx.client = base_client

        with patch("adept_connectors.connectors.claude.tools.files.get_context", return_value=mock_ctx):
            from adept_connectors.connectors.claude.tools.files import adept_get_image
            result = await adept_get_image.fn(url)

        assert isinstance(result, Image)
        assert result.data == PNG_PIXEL
        assert result._format == "png"

    @pytest.mark.asyncio
    async def test_returns_error_string_on_failure(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")

        cfg = AdeptConnectorConfig()
        auth = AuthManager(cfg)
        base_client = BaseAdeptClient(cfg, auth)
        mock_ctx = MagicMock()
        mock_ctx.client = base_client

        with patch("adept_connectors.connectors.claude.tools.files.get_context", return_value=mock_ctx), \
             patch.object(FilesClient, "download_bytes", side_effect=Exception("Connection refused")):
            from adept_connectors.connectors.claude.tools.files import adept_get_image
            result = await adept_get_image.fn("https://broken.example.com/img.png")

        assert isinstance(result, str)
        assert "Failed to fetch artifact" in result
        assert "Connection refused" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_jpeg_format(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        from fastmcp.utilities.types import Image

        url = "https://adept.example.com/photo.jpg"
        respx.get(url).mock(
            return_value=httpx.Response(200, content=b"\xff\xd8\xff\xe0", headers={"content-type": "image/jpeg"})
        )

        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")

        cfg = AdeptConnectorConfig()
        auth = AuthManager(cfg)
        base_client = BaseAdeptClient(cfg, auth)
        mock_ctx = MagicMock()
        mock_ctx.client = base_client

        with patch("adept_connectors.connectors.claude.tools.files.get_context", return_value=mock_ctx):
            from adept_connectors.connectors.claude.tools.files import adept_get_image
            result = await adept_get_image.fn(url)

        assert isinstance(result, Image)
        assert result._format == "jpeg"


# -- TestImageUrlRegex -------------------------------------------------------

class TestImageUrlRegex:

    def test_presigned_download_url(self):
        from adept_connectors.connectors.claude.tools.chat import _IMAGE_URL_RE
        text = "Here is your plot: https://your-adept-host.example.com/v1/files/abc123/download?token=xyz&expires=999"
        matches = _IMAGE_URL_RE.findall(text)
        assert len(matches) == 1
        assert "files/abc123/download" in matches[0]

    def test_plot_url_png(self):
        from adept_connectors.connectors.claude.tools.chat import _IMAGE_URL_RE
        text = "Plot saved: https://your-adept-host.example.com/v1/plots/session_abc/output.png"
        matches = _IMAGE_URL_RE.findall(text)
        assert len(matches) == 1

    def test_plot_url_jpeg(self):
        from adept_connectors.connectors.claude.tools.chat import _IMAGE_URL_RE
        text = "https://host.com/v1/plots/photo.jpeg"
        assert len(_IMAGE_URL_RE.findall(text)) == 1

    def test_no_match_plain_text(self):
        from adept_connectors.connectors.claude.tools.chat import _IMAGE_URL_RE
        assert _IMAGE_URL_RE.findall("The result is 42. No images here.") == []

    def test_no_match_non_image_url(self):
        from adept_connectors.connectors.claude.tools.chat import _IMAGE_URL_RE
        assert _IMAGE_URL_RE.findall("See https://your-adept-host.example.com/v1/threads/abc for details.") == []

    def test_multiple_urls(self):
        from adept_connectors.connectors.claude.tools.chat import _IMAGE_URL_RE
        text = (
            "Plot 1: https://host.com/v1/plots/a.png "
            "Plot 2: https://host.com/v1/plots/b.png "
            "Download: https://host.com/v1/files/x/download?token=t&expires=1"
        )
        assert len(_IMAGE_URL_RE.findall(text)) == 3

    def test_dedupe_in_auto_fetch_helper(self):
        from adept_connectors.connectors.claude.tools.chat import _IMAGE_URL_RE
        url = "https://host.com/v1/plots/a.png"
        text = f"Here: {url} and again: {url}"
        matches = list(dict.fromkeys(_IMAGE_URL_RE.findall(text)))
        assert len(matches) == 1


# -- TestAutoFetchArtifacts --------------------------------------------------

class TestAutoFetchArtifacts:

    @pytest.mark.asyncio
    async def test_no_urls_returns_text_only(self):
        from unittest.mock import MagicMock, patch

        mock_ctx = MagicMock()
        with patch("adept_connectors.connectors.claude.tools.chat.get_context", return_value=mock_ctx):
            from adept_connectors.connectors.claude.tools.chat import _auto_fetch_artifacts
            result = await _auto_fetch_artifacts("Hello, no images here.")

        assert result == ["Hello, no images here."]

    @pytest.mark.asyncio
    @respx.mock
    async def test_auto_fetches_image(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        from fastmcp.utilities.types import Image

        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")

        url = "https://host.com/v1/files/abc/download?token=xyz&expires=999"
        respx.get(url).mock(
            return_value=httpx.Response(200, content=PNG_PIXEL, headers={"content-type": "image/png"})
        )

        cfg = AdeptConnectorConfig()
        auth = AuthManager(cfg)
        base_client = BaseAdeptClient(cfg, auth)
        mock_ctx = MagicMock()
        mock_ctx.client = base_client

        with patch("adept_connectors.connectors.claude.tools.chat.get_context", return_value=mock_ctx):
            from adept_connectors.connectors.claude.tools.chat import _auto_fetch_artifacts
            result = await _auto_fetch_artifacts(f"Here is the plot: {url}")

        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], Image)
        assert result[1].data == PNG_PIXEL

    @pytest.mark.asyncio
    @respx.mock
    async def test_auto_fetches_text_artifact(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")

        url = "https://host.com/v1/files/abc/download?token=xyz&expires=999"
        respx.get(url).mock(
            return_value=httpx.Response(200, content=b"prediction: 0.95\nclass: lipid", headers={"content-type": "text/plain"})
        )

        cfg = AdeptConnectorConfig()
        auth = AuthManager(cfg)
        base_client = BaseAdeptClient(cfg, auth)
        mock_ctx = MagicMock()
        mock_ctx.client = base_client

        with patch("adept_connectors.connectors.claude.tools.chat.get_context", return_value=mock_ctx):
            from adept_connectors.connectors.claude.tools.chat import _auto_fetch_artifacts
            result = await _auto_fetch_artifacts(f"Results: {url}")

        assert len(result) == 2
        assert "prediction: 0.95" in result[1]

    @pytest.mark.asyncio
    @respx.mock
    async def test_binary_artifact_reference(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")

        url = "https://host.com/v1/files/abc/download?token=xyz&expires=999"
        respx.get(url).mock(return_value=httpx.Response(200, content=b"\x00\x01\x02" * 100))

        cfg = AdeptConnectorConfig()
        auth = AuthManager(cfg)
        base_client = BaseAdeptClient(cfg, auth)
        mock_ctx = MagicMock()
        mock_ctx.client = base_client

        with patch("adept_connectors.connectors.claude.tools.chat.get_context", return_value=mock_ctx):
            from adept_connectors.connectors.claude.tools.chat import _auto_fetch_artifacts
            result = await _auto_fetch_artifacts(f"Data: {url}")

        assert len(result) == 2
        assert "Binary artifact" in result[1]
        assert "adept_download_artifact" in result[1]

    @pytest.mark.asyncio
    async def test_failed_fetch_skipped_silently(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")

        cfg = AdeptConnectorConfig()
        auth = AuthManager(cfg)
        base_client = BaseAdeptClient(cfg, auth)
        mock_ctx = MagicMock()
        mock_ctx.client = base_client

        with patch("adept_connectors.connectors.claude.tools.chat.get_context", return_value=mock_ctx), \
             patch("adept_connectors.core.clients.files_client.FilesClient.fetch_artifact",
                   side_effect=Exception("network error")):
            from adept_connectors.connectors.claude.tools.chat import _auto_fetch_artifacts
            url = "https://host.com/v1/files/abc/download?token=xyz&expires=999"
            result = await _auto_fetch_artifacts(f"Plot: {url}")

        assert len(result) == 1
        assert isinstance(result[0], str)

    @pytest.mark.asyncio
    @respx.mock
    async def test_max_5_artifacts(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        from fastmcp.utilities.types import Image

        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")

        urls = [f"https://host.com/v1/plots/img{i}.png" for i in range(7)]
        for url in urls:
            respx.get(url).mock(
                return_value=httpx.Response(200, content=PNG_PIXEL, headers={"content-type": "image/png"})
            )

        cfg = AdeptConnectorConfig()
        auth = AuthManager(cfg)
        base_client = BaseAdeptClient(cfg, auth)
        mock_ctx = MagicMock()
        mock_ctx.client = base_client

        text = "Images: " + " ".join(urls)
        with patch("adept_connectors.connectors.claude.tools.chat.get_context", return_value=mock_ctx):
            from adept_connectors.connectors.claude.tools.chat import _auto_fetch_artifacts
            result = await _auto_fetch_artifacts(text)

        images = [r for r in result if isinstance(r, Image)]
        assert len(images) == 5
