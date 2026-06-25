"""Tests for FilesClient — file upload and list operations."""

import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from adept_connectors.core.auth import AuthManager
from adept_connectors.core.clients.base import BaseAdeptClient
from adept_connectors.core.clients.files_client import (
    FilesClient,
    _detect_mime_type,
)
from adept_connectors.core.config import AdeptConnectorConfig


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


class TestFilesClient:

    @pytest.mark.asyncio
    @respx.mock
    async def test_upload_file(self, client, config, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("col1,col2\n1,2\n")

        upload_resp = {
            "id": "file-abc123",
            "object": "file",
            "filename": "data.csv",
            "bytes": 15,
            "purpose": "assistants",
        }
        respx.post(f"{config.base_url}/files").mock(
            return_value=httpx.Response(200, json=upload_resp)
        )

        result = await client.upload(str(test_file), purpose="assistants")
        assert result["id"] == "file-abc123"
        assert result["filename"] == "data.csv"

    @pytest.mark.asyncio
    async def test_upload_missing_file(self, client):
        with pytest.raises(FileNotFoundError, match="File not found"):
            await client.upload(file_path="/nonexistent/file.txt")

    @pytest.mark.asyncio
    @respx.mock
    async def test_upload_base64_file_data(self, client, config):
        content = b"hello world"
        b64 = base64.b64encode(content).decode()

        upload_resp = {
            "id": "file-b64",
            "object": "file",
            "filename": "hello.txt",
            "bytes": len(content),
            "purpose": "assistants",
        }
        respx.post(f"{config.base_url}/files").mock(
            return_value=httpx.Response(200, json=upload_resp)
        )

        result = await client.upload(
            file_data=b64, file_name="hello.txt"
        )
        assert result["id"] == "file-b64"
        assert result["filename"] == "hello.txt"

    @pytest.mark.asyncio
    async def test_upload_base64_requires_filename(self, client):
        with pytest.raises(ValueError, match="file_name is required"):
            await client.upload(file_data="aGVsbG8=")

    @pytest.mark.asyncio
    @respx.mock
    async def test_upload_file_uri(self, client, config, tmp_path):
        test_file = tmp_path / "report.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        upload_resp = {
            "id": "file-uri",
            "object": "file",
            "filename": "report.pdf",
            "bytes": 13,
            "purpose": "assistants",
        }
        respx.post(f"{config.base_url}/files").mock(
            return_value=httpx.Response(200, json=upload_resp)
        )

        result = await client.upload(
            file_uri=f"file://{test_file}"
        )
        assert result["id"] == "file-uri"
        assert result["filename"] == "report.pdf"

    @pytest.mark.asyncio
    async def test_upload_file_uri_missing(self, client):
        with pytest.raises(FileNotFoundError, match="File not found"):
            await client.upload(file_uri="file:///nonexistent/file.txt")

    @pytest.mark.asyncio
    async def test_upload_non_file_uri_rejected(self, client):
        with pytest.raises(ValueError, match="Only file:// URIs supported"):
            await client.upload(file_uri="https://example.com/file.txt")

    @pytest.mark.asyncio
    async def test_upload_no_source_raises(self, client):
        with pytest.raises(ValueError, match="Provide exactly one"):
            await client.upload()

    @pytest.mark.asyncio
    async def test_upload_multiple_sources_raises(self, client, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="Provide only one"):
            await client.upload(file_path=str(f), file_data="aGVsbG8=")

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_files_data_wrapper(self, client, config):
        respx.get(f"{config.base_url}/files").mock(
            return_value=httpx.Response(200, json={"data": [
                {"id": "f-1", "filename": "a.csv"},
                {"id": "f-2", "filename": "b.csv"},
            ]})
        )

        files = await client.list_files()
        assert len(files) == 2
        assert files[0]["id"] == "f-1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_files_direct_list(self, client, config):
        respx.get(f"{config.base_url}/files").mock(
            return_value=httpx.Response(200, json=[
                {"id": "f-1", "filename": "a.csv"},
            ])
        )

        files = await client.list_files()
        assert len(files) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_files_with_session(self, client, config):
        route = respx.get(f"{config.base_url}/files").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        await client.list_files(session_id="sess-1")
        assert "session_id=sess-1" in str(route.calls[0].request.url)

    @pytest.mark.asyncio
    async def test_upload_truncated_base64_errors(self, client):
        """Invalid base64 in file_data raises descriptive ValueError."""
        with pytest.raises(ValueError, match="not valid base64"):
            await client.upload(
                file_data="not-valid-base64!!!", file_name="broken.txt"
            )


class TestDetectMimeType:
    """Tests for _detect_mime_type — returns Optional[str]."""

    def test_image_content_type(self):
        assert _detect_mime_type("http://x/img", "image/png") == "image/png"

    def test_text_content_type(self):
        assert _detect_mime_type("http://x/file", "text/plain") == "text/plain"

    def test_json_content_type(self):
        assert _detect_mime_type("http://x/data", "application/json") == "application/json"

    def test_octet_stream_falls_back_to_url(self):
        assert _detect_mime_type("http://x/plot.jpeg", "application/octet-stream") == "image/jpeg"

    def test_url_extension_csv(self):
        assert _detect_mime_type("http://x/data.csv", None) == "text/csv"

    def test_unknown_returns_none(self):
        assert _detect_mime_type("http://x/blob", None) is None

    def test_presigned_url_no_extension_returns_none(self):
        result = _detect_mime_type(
            "http://x/v1/files/abc/download?token=xyz&expires=123", None
        )
        assert result is None


class TestFetchArtifact:
    """Tests for FilesClient.fetch_artifact — MIME-based classification."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_image_category(self, client, config):
        url = f"{config.base_url}/files/abc/download?token=xyz"
        respx.get(url).mock(
            return_value=httpx.Response(
                200, content=b"\x89PNG",
                headers={"content-type": "image/png"},
            )
        )
        data, mime, category = await client.fetch_artifact(url)
        assert category == "image"
        assert mime == "image/png"

    @pytest.mark.asyncio
    @respx.mock
    async def test_text_category(self, client, config):
        url = f"{config.base_url}/files/abc/download?token=xyz"
        respx.get(url).mock(
            return_value=httpx.Response(
                200, content=b"prediction: 0.95",
                headers={"content-type": "text/plain"},
            )
        )
        data, mime, category = await client.fetch_artifact(url)
        assert category == "text"
        assert mime == "text/plain"
        assert data == b"prediction: 0.95"

    @pytest.mark.asyncio
    @respx.mock
    async def test_json_category(self, client, config):
        url = f"{config.base_url}/files/abc/download?token=xyz"
        respx.get(url).mock(
            return_value=httpx.Response(
                200, content=b'{"result": 42}',
                headers={"content-type": "application/json"},
            )
        )
        _, mime, category = await client.fetch_artifact(url)
        assert category == "text"
        assert mime == "application/json"

    @pytest.mark.asyncio
    @respx.mock
    async def test_binary_category_unknown(self, client, config):
        url = f"{config.base_url}/files/abc/download?token=xyz"
        respx.get(url).mock(
            return_value=httpx.Response(200, content=b"\x00\x01\x02")
        )
        _, mime, category = await client.fetch_artifact(url)
        assert category == "binary"
        assert mime is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_binary_category_parquet(self, client, config):
        url = f"{config.base_url}/files/abc/download?token=xyz"
        respx.get(url).mock(
            return_value=httpx.Response(
                200, content=b"PAR1\x00\x00",
                headers={"content-type": "application/x-parquet"},
            )
        )
        _, mime, category = await client.fetch_artifact(url)
        assert category == "binary"
        assert mime == "application/x-parquet"
