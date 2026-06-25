"""Tool registration, tool execution, resource access, and endpoint URL derivation tests.

Tests use direct function calls with a mock AppContext to avoid needing
a running ADEPT stack. Server registration is verified via the mcp instance.

Note: FastMCP v2 wraps @mcp.tool()/@mcp.resource() decorated functions in
FunctionTool/FunctionResource objects. The original function is at `.fn`.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from adept_connectors.core.auth import AuthManager
from adept_connectors.core.clients.base import BaseAdeptClient
from adept_connectors.core.config import AdeptConnectorConfig
from adept_connectors.core.session import SessionManager


# -- Tool Registration Tests ---------------------------------------------------


class TestToolRegistration:

    def test_all_tools_registered(self):
        from adept_connectors.connectors.claude.server import mcp

        tools = {t.name for t in mcp._tool_manager._tools.values()}
        expected = {
            "adept_chat",
            "adept_agui_run",
            "adept_upload_file",
            "adept_list_files",
            "adept_list_mcp_resources",
            "adept_get_image",
            "adept_download_artifact",
            "adept_create_session",
            "adept_list_sessions",
            "adept_list_tools",
            "adept_call_tool",
            "adept_list_models",
        }
        assert expected == tools

    def test_all_resources_registered(self):
        from adept_connectors.connectors.claude.server import mcp

        resources = set(mcp._resource_manager._resources.keys())
        templates = set(mcp._resource_manager._templates.keys())
        assert "adept://models" in resources
        assert "adept://sessions" in resources
        assert "adept://files/{file_id}" in templates


# -- Chat Tool Tests -----------------------------------------------------------


class TestChatTools:

    @pytest.mark.asyncio
    @respx.mock
    async def test_adept_chat(self, mock_ctx, config):
        from adept_connectors.connectors.claude.tools.chat import adept_chat

        body = (
            'data: {"choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        respx.post(f"{config.base_url}/responses/chat/completions").mock(
            return_value=httpx.Response(
                200, text=body, headers={"content-type": "text/event-stream"}
            )
        )

        result = await adept_chat.fn("Hi there")
        assert result == "Hello"

    @pytest.mark.asyncio
    @respx.mock
    async def test_adept_chat_creates_session(self, mock_ctx, config):
        from adept_connectors.connectors.claude.tools.chat import adept_chat

        body = (
            'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        respx.post(f"{config.base_url}/responses/chat/completions").mock(
            return_value=httpx.Response(
                200, text=body, headers={"content-type": "text/event-stream"}
            )
        )

        await adept_chat.fn("test")
        sessions = mock_ctx.session_mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["message_count"] == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_adept_agui_run(self, mock_ctx, config):
        from adept_connectors.connectors.claude.tools.chat import adept_agui_run

        body = "\n".join([
            json.dumps({"type": "RUN_STARTED", "threadId": "t-1", "runId": "r-1"}),
            json.dumps({"type": "TEXT_MESSAGE_CONTENT", "messageId": "m-1", "delta": "World"}),
            json.dumps({"type": "RUN_FINISHED", "threadId": "t-1", "runId": "r-1"}),
        ]) + "\n"
        respx.post(f"{config.base_url}/ag-ui/run").mock(
            return_value=httpx.Response(200, text=body)
        )

        result = await adept_agui_run.fn("Hello")
        assert result == "World"

    @pytest.mark.asyncio
    @respx.mock
    async def test_adept_agui_run_with_tool_details(self, mock_ctx, config):
        from adept_connectors.connectors.claude.tools.chat import adept_agui_run

        body = "\n".join([
            json.dumps({"type": "RUN_STARTED", "threadId": "t-1", "runId": "r-1"}),
            json.dumps({"type": "TOOL_CALL_START", "toolCallId": "tc-1", "toolCallName": "websearch"}),
            json.dumps({"type": "TOOL_CALL_ARGS", "toolCallId": "tc-1", "delta": '{"q":"test"}'}),
            json.dumps({"type": "TOOL_CALL_END", "toolCallId": "tc-1"}),
            json.dumps({"type": "TOOL_CALL_RESULT", "toolCallId": "tc-1", "messageId": "m-2", "content": "3 results"}),
            json.dumps({"type": "TEXT_MESSAGE_CONTENT", "messageId": "m-3", "delta": "Found it"}),
            json.dumps({"type": "RUN_FINISHED", "threadId": "t-1", "runId": "r-1"}),
        ]) + "\n"
        respx.post(f"{config.base_url}/ag-ui/run").mock(
            return_value=httpx.Response(200, text=body)
        )

        result = await adept_agui_run.fn("search", include_tool_details=True)
        assert "Found it" in result
        assert "websearch" in result
        assert "3 results" in result


# -- Session Tool Tests --------------------------------------------------------


class TestSessionTools:

    @pytest.mark.asyncio
    async def test_create_session(self, mock_ctx):
        from adept_connectors.connectors.claude.tools.sessions import adept_create_session

        result = json.loads(await adept_create_session.fn("my-session"))
        assert result["thread_id"] == "my-session"
        assert result["session_id"] == "my-session"

    @pytest.mark.asyncio
    async def test_create_session_auto_id(self, mock_ctx):
        from adept_connectors.connectors.claude.tools.sessions import adept_create_session

        result = json.loads(await adept_create_session.fn())
        assert len(result["thread_id"]) > 0

    @pytest.mark.asyncio
    async def test_list_sessions(self, mock_ctx):
        from adept_connectors.connectors.claude.tools.sessions import (
            adept_create_session,
            adept_list_sessions,
        )

        await adept_create_session.fn("s-1")
        await adept_create_session.fn("s-2")
        result = json.loads(await adept_list_sessions.fn())
        assert len(result) == 2


# -- File Tool Tests -----------------------------------------------------------


class TestFileTools:

    @pytest.mark.asyncio
    @respx.mock
    async def test_upload_file(self, mock_ctx, config, tmp_path):
        from adept_connectors.connectors.claude.tools.files import adept_upload_file

        f = tmp_path / "test.csv"
        f.write_text("a,b\n1,2\n")

        respx.post(f"{config.base_url}/files").mock(
            return_value=httpx.Response(
                200, json={"id": "f-1", "filename": "test.csv", "bytes": 8}
            )
        )

        result = json.loads(await adept_upload_file.fn(str(f)))
        assert result["id"] == "f-1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_upload_file_with_session_id(self, mock_ctx, config, tmp_path):
        """Verify session_id is forwarded as form data in the upload request."""
        from adept_connectors.connectors.claude.tools.files import adept_upload_file

        f = tmp_path / "data.csv"
        f.write_text("x,y\n1,2\n")

        route = respx.post(f"{config.base_url}/files").mock(
            return_value=httpx.Response(
                200, json={"id": "f-2", "filename": "data.csv", "bytes": 8}
            )
        )

        result = json.loads(
            await adept_upload_file.fn(str(f), session_id="sess-abc")
        )
        assert result["id"] == "f-2"
        request = route.calls[0].request
        body = request.content.decode("utf-8", errors="replace")
        assert "sess-abc" in body

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_files(self, mock_ctx, config):
        from adept_connectors.connectors.claude.tools.files import adept_list_files

        respx.get(f"{config.base_url}/files").mock(
            return_value=httpx.Response(
                200, json={"data": [{"id": "f-1"}, {"id": "f-2"}]}
            )
        )

        result = json.loads(await adept_list_files.fn())
        assert len(result) == 2


# -- Workflow Tests (session -> upload -> chat) --------------------------------


class TestFileUploadWorkflow:
    """Test the recommended workflow: create session -> upload file -> chat."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_session_upload_chat_workflow(self, mock_ctx, config, tmp_path):
        """Full workflow: create session, upload file, chat referencing file_id."""
        from adept_connectors.connectors.claude.tools.chat import adept_chat
        from adept_connectors.connectors.claude.tools.files import adept_upload_file
        from adept_connectors.connectors.claude.tools.sessions import adept_create_session

        # Step 1: Create session
        session = json.loads(await adept_create_session.fn())
        session_id = session["session_id"]
        assert session_id

        # Step 2: Upload file with session_id
        f = tmp_path / "report.csv"
        f.write_text("metric,value\naccuracy,0.95\n")

        respx.post(f"{config.base_url}/files").mock(
            return_value=httpx.Response(
                200,
                json={"id": "file-abc", "filename": "report.csv", "bytes": 30},
            )
        )

        upload_result = json.loads(
            await adept_upload_file.fn(str(f), session_id=session_id)
        )
        assert upload_result["id"] == "file-abc"

        # Step 3: Chat referencing file_id, same session
        body = (
            'data: {"choices":[{"index":0,"delta":{"content":"Analysis complete"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        respx.post(f"{config.base_url}/responses/chat/completions").mock(
            return_value=httpx.Response(
                200, text=body, headers={"content-type": "text/event-stream"}
            )
        )

        chat_result = await adept_chat.fn(
            f"Analyze file_id: {upload_result['id']}", session_id=session_id
        )
        assert "Analysis complete" in chat_result

        # Verify session has correct message count
        sessions = mock_ctx.session_mgr.list_sessions()
        matched = [s for s in sessions if s["session_id"] == session_id]
        assert len(matched) == 1
        assert matched[0]["message_count"] == 1  # Only chat increments count

    @pytest.mark.asyncio
    @respx.mock
    async def test_upload_without_session_still_works(self, mock_ctx, config, tmp_path):
        """Upload without session_id should still succeed (backward compat)."""
        from adept_connectors.connectors.claude.tools.files import adept_upload_file

        f = tmp_path / "data.txt"
        f.write_text("hello")

        respx.post(f"{config.base_url}/files").mock(
            return_value=httpx.Response(
                200, json={"id": "file-no-sess", "filename": "data.txt", "bytes": 5}
            )
        )

        result = json.loads(await adept_upload_file.fn(str(f)))
        assert result["id"] == "file-no-sess"


# -- Discovery Tool Tests -----------------------------------------------------


class TestDiscoveryTools:

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_tools(self, mock_ctx, config):
        from adept_connectors.connectors.claude.tools.discovery import adept_list_tools

        respx.post(config.mcp_server_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "tools": [{"name": "websearch", "description": "Search"}]
                    },
                },
            )
        )

        result = json.loads(await adept_list_tools.fn())
        assert len(result) == 1
        assert result[0]["name"] == "websearch"

    @pytest.mark.asyncio
    @respx.mock
    async def test_call_tool(self, mock_ctx, config):
        from adept_connectors.connectors.claude.tools.discovery import adept_call_tool

        respx.post(config.mcp_server_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"content": [{"type": "text", "text": "42 results"}]},
                },
            )
        )

        result = await adept_call_tool.fn("websearch", '{"query": "protein"}')
        assert result == "42 results"

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_models(self, mock_ctx, config):
        from adept_connectors.connectors.claude.tools.discovery import adept_list_models

        respx.get(f"{config.base_url}/responses/models").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "scientific-agent-v1", "object": "model", "owned_by": "adept"}
                    ]
                },
            )
        )

        result = json.loads(await adept_list_models.fn())
        assert len(result) == 1
        assert result[0]["id"] == "scientific-agent-v1"


# -- Resource Tests ------------------------------------------------------------


class TestResources:

    @pytest.mark.asyncio
    async def test_sessions_resource(self, mock_ctx):
        from adept_connectors.connectors.claude.resources.adept_resources import get_sessions

        mock_ctx.session_mgr.get_or_create("r-1")
        result = json.loads(await get_sessions.fn())
        assert len(result) == 1
        assert result[0]["thread_id"] == "r-1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_models_resource(self, mock_ctx, config):
        from adept_connectors.connectors.claude.resources.adept_resources import get_models

        respx.get(f"{config.base_url}/responses/models").mock(
            return_value=httpx.Response(
                200, json={"data": [{"id": "model-1"}]}
            )
        )

        result = json.loads(await get_models.fn())
        assert "data" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_file_metadata_resource(self, mock_ctx, config):
        from adept_connectors.connectors.claude.resources.adept_resources import get_file_metadata

        respx.get(f"{config.base_url}/files/f-123").mock(
            return_value=httpx.Response(
                200, json={"id": "f-123", "filename": "data.csv"}
            )
        )

        result = json.loads(await get_file_metadata.fn("f-123"))
        assert result["id"] == "f-123"


# -- Endpoint URL Derivation Tests --------------------------------------------


class TestEndpointURLDerivation:
    """Verify correct URL derivation for local and remote deployments."""

    def test_gateway_url_https_no_port(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "https://your-adept-host.example.com/v1")
        cfg = AdeptConnectorConfig()
        assert cfg.base_url == "https://your-adept-host.example.com/v1"

    def test_keycloak_url_https_no_port(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "https://your-adept-host.example.com/v1")
        monkeypatch.delenv("ADEPT_KEYCLOAK_URL", raising=False)
        cfg = AdeptConnectorConfig()
        assert cfg.keycloak_url == "https://your-adept-host.example.com"
        assert ":8180" not in cfg.keycloak_url

    def test_mcp_url_https_no_port(self):
        from adept_connectors.core.clients.mcp_proxy import MCPProxyClient
        url = MCPProxyClient._derive_mcp_url("https://your-adept-host.example.com/v1")
        assert url == "https://your-adept-host.example.com/mcp"
        assert ":80" not in url

    def test_gateway_url_localhost_port(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "http://localhost:8083/v1")
        cfg = AdeptConnectorConfig()
        assert cfg.base_url == "http://localhost:8083/v1"

    def test_keycloak_url_localhost_derived(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "http://localhost:8083/v1")
        monkeypatch.delenv("ADEPT_KEYCLOAK_URL", raising=False)
        cfg = AdeptConnectorConfig()
        assert cfg.keycloak_url == "http://localhost"

    def test_mcp_url_localhost_port(self):
        from adept_connectors.core.clients.mcp_proxy import MCPProxyClient
        url = MCPProxyClient._derive_mcp_url("http://localhost:8083/v1")
        assert url == "http://localhost:8083/mcp"

    def test_keycloak_url_explicit_override(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "https://your-adept-host.example.com/v1")
        monkeypatch.setenv("ADEPT_KEYCLOAK_URL", "http://localhost:8180")
        cfg = AdeptConnectorConfig()
        assert cfg.keycloak_url == "http://localhost:8180"

    def test_mcp_url_explicit_override(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "https://your-adept-host.example.com/v1")
        monkeypatch.setenv("ADEPT_MCP_SERVER_URL", "http://mcp-server:8080/mcp")

        from adept_connectors.core.clients.mcp_proxy import MCPProxyClient
        cfg = AdeptConnectorConfig()
        proxy = MCPProxyClient(cfg, AuthManager(cfg))
        assert proxy._base_url == "http://mcp-server:8080/mcp"

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_endpoints_use_correct_urls_https(self, monkeypatch):
        """Verify all tools target correct HTTPS URLs with no port injection."""
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "https://your-adept-host.example.com/v1")
        monkeypatch.setenv("ADEPT_VERIFY_SSL", "false")
        monkeypatch.delenv("ADEPT_KEYCLOAK_URL", raising=False)
        monkeypatch.delenv("ADEPT_MCP_SERVER_URL", raising=False)

        import adept_connectors.connectors.claude.server as srv

        cfg = AdeptConnectorConfig()
        auth = AuthManager(cfg)
        session_mgr = SessionManager(persist=False)
        client = BaseAdeptClient(cfg, auth, client_source="claude-connector")

        ctx = srv.AppContext(config=cfg, auth=auth, session_mgr=session_mgr, client=client)
        old_ctx = srv._ctx
        srv._ctx = ctx

        try:
            # 1. Models
            respx.get("https://your-adept-host.example.com/v1/responses/models").mock(
                return_value=httpx.Response(200, json={"data": [{"id": "model-1"}]})
            )
            from adept_connectors.connectors.claude.tools.discovery import adept_list_models
            result = json.loads(await adept_list_models.fn())
            assert len(result) == 1

            # 2. Files
            respx.get("https://your-adept-host.example.com/v1/files").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            from adept_connectors.connectors.claude.tools.files import adept_list_files
            result = json.loads(await adept_list_files.fn())
            assert isinstance(result, list)

            # 3. Chat
            body = (
                'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
                "data: [DONE]\n\n"
            )
            respx.post("https://your-adept-host.example.com/v1/responses/chat/completions").mock(
                return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
            )
            from adept_connectors.connectors.claude.tools.chat import adept_chat
            result = await adept_chat.fn("test")
            assert result == "ok"

            # 4. AG-UI
            agui_body = "\n".join([
                json.dumps({"type": "RUN_STARTED", "threadId": "t-1", "runId": "r-1"}),
                json.dumps({"type": "TEXT_MESSAGE_CONTENT", "messageId": "m-1", "delta": "hi"}),
                json.dumps({"type": "RUN_FINISHED", "threadId": "t-1", "runId": "r-1"}),
            ]) + "\n"
            respx.post("https://your-adept-host.example.com/v1/ag-ui/run").mock(
                return_value=httpx.Response(200, text=agui_body)
            )
            from adept_connectors.connectors.claude.tools.chat import adept_agui_run
            result = await adept_agui_run.fn("test")
            assert result == "hi"

            # 5. MCP proxy
            respx.post("https://your-adept-host.example.com/mcp").mock(
                return_value=httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"tools": [{"name": "websearch", "description": "Search"}]},
                })
            )
            from adept_connectors.connectors.claude.tools.discovery import adept_list_tools
            result = json.loads(await adept_list_tools.fn())
            assert len(result) == 1
            assert result[0]["name"] == "websearch"

        finally:
            srv._ctx = old_ctx
