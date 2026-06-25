"""ChatGPT connector configuration.

Extends AdeptConnectorConfig with ChatGPT Actions-specific settings:
OAuth2 authorization code flow, image proxy, and server binding.
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings

from ...core.config import AdeptConnectorConfig


class ChatGPTConnectorConfig(AdeptConnectorConfig):
    """Configuration for the ChatGPT Actions connector.

    Inherits all ADEPT_ env vars from AdeptConnectorConfig, plus
    CHATGPT_-prefixed settings for the Actions server itself.
    """

    # --- Server ---
    chatgpt_host: str = Field(
        default="0.0.0.0",
        description="Host to bind the FastAPI server",
    )
    chatgpt_port: int = Field(
        default=8090,
        description="Port to bind the FastAPI server",
    )

    # --- OAuth2 (authorization code flow for ChatGPT Actions) ---
    chatgpt_client_id: str = Field(
        default="chatgpt-connector",
        description="Keycloak OIDC client ID for the ChatGPT connector",
    )
    chatgpt_client_secret: Optional[str] = Field(
        default=None,
        description="Keycloak OIDC client secret (confidential client)",
    )
    chatgpt_redirect_uri: Optional[str] = Field(
        default=None,
        description="OAuth2 redirect URI for ChatGPT callback. "
        "If unset, derived from chatgpt_host:chatgpt_port.",
    )

    # --- Image proxy ---
    chatgpt_image_ttl: int = Field(
        default=600,
        description="Image proxy cache TTL in seconds (default: 10 minutes)",
    )
    chatgpt_max_cached_images: int = Field(
        default=200,
        description="Maximum number of images in the proxy cache",
    )

    # --- Public URL ---
    chatgpt_public_url: Optional[str] = Field(
        default=None,
        description="Public URL of this connector for image proxy URLs. "
        "If unset, derived from chatgpt_host:chatgpt_port.",
    )

    @property
    def public_base_url(self) -> str:
        """Base URL for generating proxy image URLs."""
        if self.chatgpt_public_url:
            return self.chatgpt_public_url.rstrip("/")
        return f"http://{self.chatgpt_host}:{self.chatgpt_port}"

    @property
    def effective_redirect_uri(self) -> str:
        """OAuth2 redirect URI for Keycloak callback."""
        if self.chatgpt_redirect_uri:
            return self.chatgpt_redirect_uri
        return f"{self.public_base_url}/auth/callback"
