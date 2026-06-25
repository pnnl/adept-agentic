"""Configuration for ADEPT Connectors.

Provides two config tiers:
- ConnectorProfile: Minimal config for zero-code IDE tools (url + api_key + model)
- AdeptConnectorConfig: Full config for rich connectors (+ Keycloak, sessions, workspace)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class AuthMethod(str, Enum):
    API_KEY = "api_key"
    JWT = "jwt"
    PASSWORD = "password"


class ConnectorProfile(BaseSettings):
    """Minimal config for any desktop connector — just endpoint + auth + model.

    Sufficient for Roo Code, Continue.dev, Cursor, OBot.ai, and other
    OpenAI-compatible tools that only need a base URL and API key.
    """

    model_config = {"env_prefix": "ADEPT_", "env_file": ".env", "extra": "ignore"}

    # Connection (required)
    base_url: str = Field(
        default="http://localhost:8083/v1",
        description="ADEPT Agent Gateway base URL",
    )

    # Authentication (just API key for simple tools)
    api_key: Optional[str] = Field(default=None, description="ADEPT API key or JWT")

    # Model selection
    model: str = Field(
        default="agentic-framework:scientific-agent-v1",
        description="Default model name",
    )

    # Timeouts
    request_timeout: int = Field(default=300, description="HTTP timeout in seconds")
    verify_ssl: bool = Field(default=True, description="Verify TLS certificates")


class AdeptConnectorConfig(BaseSettings):
    """Full configuration for rich connectors (Claude, ChatGPT, etc.).

    Extends ConnectorProfile with Keycloak auth, session persistence,
    workspace management, and admin provisioning support.
    """

    model_config = {"env_prefix": "ADEPT_", "env_file": ".env", "extra": "ignore"}

    # Connection
    base_url: str = Field(
        default="http://localhost:8083/v1",
        description="ADEPT Agent Gateway base URL",
    )
    request_timeout: int = Field(default=300, description="HTTP timeout in seconds")
    verify_ssl: bool = Field(default=True, description="Verify TLS certificates")

    # Authentication
    auth_method: AuthMethod = Field(
        default=AuthMethod.API_KEY,
        description="Authentication method: api_key, jwt, or password",
    )
    api_key: Optional[str] = Field(default=None, description="Service or personal API key")
    jwt_token: Optional[str] = Field(default=None, description="Pre-obtained JWT token")
    username: Optional[str] = Field(default=None, description="Keycloak username (for password auth)")
    password: Optional[str] = Field(default=None, description="Keycloak password (for password auth)")

    # Keycloak (for password/ROPC auth)
    keycloak_url: Optional[str] = Field(
        default=None,
        description="Keycloak URL. If unset, derived from base_url.",
    )
    keycloak_realm: str = Field(default="master", description="Keycloak realm")
    keycloak_client_id: str = Field(
        default="login-client", description="OIDC client ID for ROPC flow (public client)"
    )

    # Defaults
    default_model: str = Field(
        default="agentic-framework:scientific-agent-v1",
        description="Default model for chat requests",
    )
    mcp_server_url: Optional[str] = Field(
        default=None, description="Direct MCP server URL (bypasses gateway)"
    )

    # Workspace
    workspace_dir: Optional[str] = Field(
        default=None,
        description=(
            "Host directory for downloaded artifacts and working files. "
            "Used as default save_dir for artifact downloads. "
            "Defaults to ~/Downloads if unset."
        ),
    )

    # Session persistence
    session_persistence: bool = Field(
        default=True, description="Persist sessions to disk"
    )

    @model_validator(mode="after")
    def _derive_keycloak_url(self) -> "AdeptConnectorConfig":
        if self.keycloak_url is None and self.base_url:
            from urllib.parse import urlparse

            parsed = urlparse(self.base_url)
            self.keycloak_url = f"{parsed.scheme}://{parsed.hostname}"
        return self

    @model_validator(mode="after")
    def _validate_auth_credentials(self) -> "AdeptConnectorConfig":
        if self.auth_method == AuthMethod.API_KEY and not self.api_key:
            raise ValueError("ADEPT_API_KEY required when auth_method=api_key")
        if self.auth_method == AuthMethod.JWT and not self.jwt_token:
            raise ValueError("ADEPT_JWT_TOKEN required when auth_method=jwt")
        if self.auth_method == AuthMethod.PASSWORD:
            if not self.username or not self.password:
                raise ValueError(
                    "ADEPT_USERNAME and ADEPT_PASSWORD required when auth_method=password"
                )
        return self


class AdminConfig(BaseSettings):
    """Admin-only configuration for user provisioning (RC server side)."""

    model_config = {"env_prefix": "ADEPT_ADMIN_", "env_file": ".env", "extra": "ignore"}

    keycloak_url: str = Field(
        default="http://localhost:8180", description="Keycloak admin URL"
    )
    username: str = Field(default="admin", description="Keycloak admin username")
    password: str = Field(default="", description="Keycloak admin password")
    default_group: str = Field(
        default="notebook-users", description="Default group for provisioned users"
    )
