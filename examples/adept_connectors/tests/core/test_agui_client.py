"""Tests for AGUIClient — JSONL streaming."""

import json

import httpx
import pytest
import respx

from adept_connectors.core.auth import AuthManager
from adept_connectors.core.clients.agui_client import AGUIClient
from adept_connectors.core.clients.base import BaseAdeptClient
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
    return AGUIClient(base_client)


def _jsonl(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


class TestAGUIClient:

    @pytest.mark.asyncio
    @respx.mock
    async def test_basic_text_accumulation(self, client, config):
        body = _jsonl(
            {"type": "RUN_STARTED", "threadId": "t-1", "runId": "r-1"},
            {"type": "TEXT_MESSAGE_START", "messageId": "m-1", "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m-1", "delta": "Hello"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m-1", "delta": " world"},
            {"type": "TEXT_MESSAGE_END", "messageId": "m-1"},
            {"type": "RUN_FINISHED", "threadId": "t-1", "runId": "r-1"},
        )
        respx.post(f"{config.base_url}/ag-ui/run").mock(
            return_value=httpx.Response(200, text=body)
        )

        result = await client.run(messages=[{"role": "user", "content": "Hi"}])
        assert result.content == "Hello world"
        assert result.thread_id == "t-1"
        assert result.run_id == "r-1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_tool_call_sequence(self, client, config):
        body = _jsonl(
            {"type": "RUN_STARTED", "threadId": "t-1", "runId": "r-1"},
            {"type": "TOOL_CALL_START", "toolCallId": "tc-1", "toolCallName": "websearch"},
            {"type": "TOOL_CALL_ARGS", "toolCallId": "tc-1", "delta": '{"query":'},
            {"type": "TOOL_CALL_ARGS", "toolCallId": "tc-1", "delta": '"protein"}'},
            {"type": "TOOL_CALL_END", "toolCallId": "tc-1"},
            {"type": "TOOL_CALL_RESULT", "toolCallId": "tc-1", "messageId": "m-2", "content": "Found 5 results"},
            {"type": "TEXT_MESSAGE_START", "messageId": "m-3", "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m-3", "delta": "Based on search..."},
            {"type": "TEXT_MESSAGE_END", "messageId": "m-3"},
            {"type": "RUN_FINISHED", "threadId": "t-1", "runId": "r-1"},
        )
        respx.post(f"{config.base_url}/ag-ui/run").mock(
            return_value=httpx.Response(200, text=body)
        )

        result = await client.run(messages=[{"role": "user", "content": "search"}])
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.name == "websearch"
        assert tc.arguments == '{"query":"protein"}'
        assert tc.result == "Found 5 results"
        assert result.content == "Based on search..."

    @pytest.mark.asyncio
    @respx.mock
    async def test_session_fork_via_meta_event(self, client, config):
        body = _jsonl(
            {"type": "RUN_STARTED", "threadId": "t-1", "runId": "r-1"},
            {"type": "TEXT_MESSAGE_START", "messageId": "m-1", "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m-1", "delta": "ok"},
            {"type": "TEXT_MESSAGE_END", "messageId": "m-1"},
            {"type": "META_EVENT", "key": "session_fork", "value": {"new_thread_id": "t-2", "generation": 1}},
            {"type": "RUN_FINISHED", "threadId": "t-1", "runId": "r-1"},
        )
        respx.post(f"{config.base_url}/ag-ui/run").mock(
            return_value=httpx.Response(200, text=body)
        )

        result = await client.run(messages=[{"role": "user", "content": "test"}])
        assert result.session_fork is not None
        assert result.session_fork["new_thread_id"] == "t-2"

    @pytest.mark.asyncio
    @respx.mock
    async def test_run_error_raises(self, client, config):
        body = _jsonl(
            {"type": "RUN_STARTED", "threadId": "t-1", "runId": "r-1"},
            {"type": "RUN_ERROR", "message": "Agent crashed", "code": "INTERNAL"},
        )
        respx.post(f"{config.base_url}/ag-ui/run").mock(
            return_value=httpx.Response(200, text=body)
        )

        with pytest.raises(RuntimeError, match="Agent crashed"):
            await client.run(messages=[{"role": "user", "content": "boom"}])

    @pytest.mark.asyncio
    @respx.mock
    async def test_thread_id_in_payload(self, client, config):
        body = _jsonl(
            {"type": "RUN_STARTED", "threadId": "t-1", "runId": "r-1"},
            {"type": "RUN_FINISHED", "threadId": "t-1", "runId": "r-1"},
        )
        route = respx.post(f"{config.base_url}/ag-ui/run").mock(
            return_value=httpx.Response(200, text=body)
        )

        await client.run(
            messages=[{"role": "user", "content": "test"}],
            thread_id="my-thread",
        )
        sent = json.loads(route.calls[0].request.content)
        assert sent["thread_id"] == "my-thread"
