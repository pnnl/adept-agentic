"""Shared fixtures for Claude connector tests."""

import pytest

from adept_connectors.core.auth import AuthManager
from adept_connectors.core.clients.base import BaseAdeptClient
from adept_connectors.core.config import AdeptConnectorConfig
from adept_connectors.core.session import SessionManager


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
    monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
    monkeypatch.setenv("ADEPT_BASE_URL", "http://adept-test:8083/v1")
    monkeypatch.setenv("ADEPT_MCP_SERVER_URL", "http://adept-test:8080/mcp")
    return AdeptConnectorConfig()


@pytest.fixture
def mock_ctx(config):
    """Create a mock AppContext and patch it into the server module."""
    import adept_connectors.connectors.claude.server as srv

    auth = AuthManager(config)
    session_mgr = SessionManager(persist=False)
    client = BaseAdeptClient(config, auth, client_source="claude-connector")

    ctx = srv.AppContext(
        config=config,
        auth=auth,
        session_mgr=session_mgr,
        client=client,
    )
    old_ctx = srv._ctx
    srv._ctx = ctx
    yield ctx
    srv._ctx = old_ctx
