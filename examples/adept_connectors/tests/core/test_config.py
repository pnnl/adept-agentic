"""Tests for ConnectorProfile, AdeptConnectorConfig, and AdminConfig."""

import pytest

from adept_connectors.core.config import (
    AdminConfig,
    AdeptConnectorConfig,
    AuthMethod,
    ConnectorProfile,
)


class TestConnectorProfile:
    """Minimal config for zero-code IDE tools."""

    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("ADEPT_API_KEY", raising=False)
        monkeypatch.delenv("ADEPT_AUTH_METHOD", raising=False)
        cfg = ConnectorProfile()
        assert cfg.base_url == "http://localhost:8083/v1"
        assert cfg.api_key is None
        assert cfg.model == "agentic-framework:scientific-agent-v1"
        assert cfg.request_timeout == 300
        assert cfg.verify_ssl is True

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("ADEPT_BASE_URL", "https://your-adept-host.example.com:8083/v1")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-profile-key")
        monkeypatch.setenv("ADEPT_MODEL", "custom-model")
        cfg = ConnectorProfile()
        assert cfg.base_url == "https://your-adept-host.example.com:8083/v1"
        assert cfg.api_key == "sk-profile-key"
        assert cfg.model == "custom-model"


class TestAdeptConnectorConfig:
    """Full config with Keycloak auth."""

    def test_api_key_method_requires_key(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.delenv("ADEPT_API_KEY", raising=False)
        with pytest.raises(ValueError, match="ADEPT_API_KEY required"):
            AdeptConnectorConfig()

    def test_api_key_method_accepts_key(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test-key")
        cfg = AdeptConnectorConfig()
        assert cfg.auth_method == AuthMethod.API_KEY
        assert cfg.api_key == "sk-test-key"

    def test_jwt_method_requires_token(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "jwt")
        monkeypatch.delenv("ADEPT_JWT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="ADEPT_JWT_TOKEN required"):
            AdeptConnectorConfig()

    def test_jwt_method_accepts_token(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "jwt")
        monkeypatch.setenv("ADEPT_JWT_TOKEN", "eyJhbGci...")
        cfg = AdeptConnectorConfig()
        assert cfg.auth_method == AuthMethod.JWT

    def test_password_method_requires_credentials(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "password")
        monkeypatch.delenv("ADEPT_USERNAME", raising=False)
        monkeypatch.delenv("ADEPT_PASSWORD", raising=False)
        with pytest.raises(ValueError, match="ADEPT_USERNAME and ADEPT_PASSWORD"):
            AdeptConnectorConfig()

    def test_password_method_accepts_credentials(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "password")
        monkeypatch.setenv("ADEPT_USERNAME", "alice@pnnl.gov")
        monkeypatch.setenv("ADEPT_PASSWORD", "secret123")
        cfg = AdeptConnectorConfig()
        assert cfg.auth_method == AuthMethod.PASSWORD
        assert cfg.username == "alice@pnnl.gov"

    def test_keycloak_url_derived_from_base_url(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_BASE_URL", "https://your-adept-host.example.com:8083/v1")
        monkeypatch.delenv("ADEPT_KEYCLOAK_URL", raising=False)
        cfg = AdeptConnectorConfig()
        assert cfg.keycloak_url == "https://your-adept-host.example.com"

    def test_keycloak_url_explicit_override(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        monkeypatch.setenv("ADEPT_KEYCLOAK_URL", "http://custom:9999")
        cfg = AdeptConnectorConfig()
        assert cfg.keycloak_url == "http://custom:9999"

    def test_defaults(self, monkeypatch):
        monkeypatch.setenv("ADEPT_AUTH_METHOD", "api_key")
        monkeypatch.setenv("ADEPT_API_KEY", "sk-test")
        cfg = AdeptConnectorConfig()
        assert cfg.base_url == "http://localhost:8083/v1"
        assert cfg.request_timeout == 300
        assert cfg.verify_ssl is True
        assert cfg.default_model == "agentic-framework:scientific-agent-v1"
        assert cfg.session_persistence is True
        assert cfg.keycloak_realm == "master"
        assert cfg.keycloak_client_id == "login-client"


class TestAdminConfig:

    def test_defaults(self):
        cfg = AdminConfig()
        assert cfg.keycloak_url == "http://localhost:8180"
        assert cfg.username == "admin"
        assert cfg.default_group == "notebook-users"
