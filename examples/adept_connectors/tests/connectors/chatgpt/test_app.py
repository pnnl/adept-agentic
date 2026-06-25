"""Tests for the ChatGPT connector FastAPI application."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from adept_connectors.connectors.chatgpt.config import ChatGPTConnectorConfig
from adept_connectors.connectors.chatgpt.rendering import ImageCache


class TestCreateApp:
    """Tests for the app factory and configuration."""

    def test_create_app_returns_fastapi(self):
        """create_app returns a FastAPI instance with correct metadata."""
        from adept_connectors.connectors.chatgpt.app import create_app

        config = ChatGPTConnectorConfig()
        app = create_app(config)

        assert app.title == "ADEPT ChatGPT Connector"
        assert app.version == "0.1.0"

    def test_create_app_has_routes(self):
        """App includes all expected routes."""
        from adept_connectors.connectors.chatgpt.app import create_app

        config = ChatGPTConnectorConfig()
        app = create_app(config)

        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/health" in route_paths
        assert "/v1/chat" in route_paths
        assert "/v1/sessions" in route_paths
        assert "/v1/files" in route_paths
        assert "/v1/files/upload" in route_paths
        assert "/v1/tools" in route_paths
        assert "/v1/tools/{tool_name}" in route_paths
        assert "/v1/images/{token}" in route_paths
        assert "/auth/authorize" in route_paths
        assert "/auth/callback" in route_paths
        assert "/auth/token" in route_paths

    def test_create_app_stores_config(self):
        """Config is stored on app.state."""
        from adept_connectors.connectors.chatgpt.app import create_app

        config = ChatGPTConnectorConfig()
        app = create_app(config)
        assert app.state.config is config


class TestChatGPTConnectorConfig:
    """Tests for ChatGPT-specific configuration."""

    def test_default_values(self):
        config = ChatGPTConnectorConfig()
        assert config.chatgpt_host == "0.0.0.0"
        assert config.chatgpt_port == 8090
        assert config.chatgpt_client_id == "chatgpt-connector"
        assert config.chatgpt_image_ttl == 600
        assert config.chatgpt_max_cached_images == 200

    def test_public_base_url_default(self):
        config = ChatGPTConnectorConfig()
        assert config.public_base_url == "http://0.0.0.0:8090"

    def test_public_base_url_override(self, monkeypatch):
        monkeypatch.setenv("ADEPT_CHATGPT_PUBLIC_URL", "https://chatgpt.example.com")
        config = ChatGPTConnectorConfig()
        assert config.public_base_url == "https://chatgpt.example.com"

    def test_effective_redirect_uri_default(self):
        config = ChatGPTConnectorConfig()
        assert config.effective_redirect_uri == "http://0.0.0.0:8090/auth/callback"

    def test_effective_redirect_uri_override(self, monkeypatch):
        monkeypatch.setenv("ADEPT_CHATGPT_REDIRECT_URI", "https://example.com/callback")
        config = ChatGPTConnectorConfig()
        assert config.effective_redirect_uri == "https://example.com/callback"

    def test_inherits_adept_config(self):
        """ChatGPTConnectorConfig inherits all ADEPT_ env var fields."""
        config = ChatGPTConnectorConfig()
        assert hasattr(config, "base_url")
        assert hasattr(config, "auth_method")
        assert hasattr(config, "keycloak_url")
        assert hasattr(config, "default_model")
