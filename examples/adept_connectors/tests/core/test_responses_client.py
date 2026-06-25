"""Tests for ResponsesAPIClient — SSE streaming."""

import json

import httpx
import pytest
import respx

from adept_connectors.core.auth import AuthManager
from adept_connectors.core.clients.base import BaseAdeptClient
from adept_connectors.core.clients.responses_api import ResponsesAPIClient
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
    return ResponsesAPIClient(base_client)


def _sse_body(*chunks: str) -> str:
    """Build an SSE response body from data lines."""
    lines = []
    for c in chunks:
        lines.append(f"data: {c}\n\n")
    return "".join(lines)


def _content_chunk(text: str, finish: str = None) -> str:
    chunk = {
        "id": "cmp-1",
        "object": "response.completion.chunk",
        "model": "test-model",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}],
    }
    return json.dumps(chunk)


def _final_chunk(fork: dict = None) -> str:
    chunk = {
        "id": "cmp-1",
        "object": "response.completion.chunk",
        "model": "test-model",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    if fork:
        chunk["session_fork"] = fork
    return json.dumps(chunk)


class TestResponsesAPIClient:

    @pytest.mark.asyncio
    @respx.mock
    async def test_basic_streaming(self, client, config):
        body = _sse_body(
            _content_chunk("Hello"),
            _content_chunk(" world"),
            _final_chunk(),
            "[DONE]",
        )
        respx.post(f"{config.base_url}/responses/chat/completions").mock(
            return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        )

        result = await client.chat(
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert result.content == "Hello world"
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    @respx.mock
    async def test_session_fork_metadata(self, client, config):
        fork_data = {
            "forked_session_id": "new-sess",
            "parent_session_id": "old-sess",
            "generation": 1,
        }
        body = _sse_body(
            _content_chunk("response"),
            _final_chunk(fork=fork_data),
            "[DONE]",
        )
        respx.post(f"{config.base_url}/responses/chat/completions").mock(
            return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        )

        result = await client.chat(messages=[{"role": "user", "content": "test"}])
        assert result.session_fork is not None
        assert result.session_fork["forked_session_id"] == "new-sess"

    @pytest.mark.asyncio
    @respx.mock
    async def test_error_chunk_raises(self, client, config):
        body = _sse_body(
            json.dumps({"error": {"message": "Internal error", "type": "internal_error"}}),
            "[DONE]",
        )
        respx.post(f"{config.base_url}/responses/chat/completions").mock(
            return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        )

        with pytest.raises(RuntimeError, match="Internal error"):
            await client.chat(messages=[{"role": "user", "content": "fail"}])

    @pytest.mark.asyncio
    @respx.mock
    async def test_session_id_in_payload(self, client, config):
        body = _sse_body(_content_chunk("ok"), _final_chunk(), "[DONE]")
        route = respx.post(f"{config.base_url}/responses/chat/completions").mock(
            return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        )

        await client.chat(
            messages=[{"role": "user", "content": "test"}],
            session_id="sess-1",
            mcp_session_id="mcp-1",
        )
        sent_body = json.loads(route.calls[0].request.content)
        assert sent_body["session_id"] == "sess-1"
        assert sent_body["mcp_session_id"] == "mcp-1"
        assert sent_body["stream"] is True
