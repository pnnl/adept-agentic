"""ADEPT Connector Core — shared library for all ADEPT platform connectors.

Public API:
    ConnectorProfile     — minimal config (url + api_key + model) for zero-code IDE tools
    AdeptConnectorConfig — full config with Keycloak, sessions, workspace
    AuthManager          — token lifecycle (API key, JWT, ROPC)
    SessionManager       — multi-tier session mapping with persistence
    AdeptFacade          — high-level chat/agui/files/tools API
    ImageData            — protocol-agnostic image representation
    ImageRenderer        — protocol for connector-specific image rendering
    MarkdownRenderer     — default renderer for markdown-based tools
"""

from .config import AdeptConnectorConfig, AdminConfig, AuthMethod, ConnectorProfile
from .auth import AuthManager
from .session import SessionInfo, SessionManager
from .rendering import ImageData, ImageRenderer, MarkdownRenderer, extract_image_urls, extract_artifact_urls
from .facade import AdeptFacade, AGUIChatResult, ArtifactData, ChatResult

__all__ = [
    # Config
    "ConnectorProfile",
    "AdeptConnectorConfig",
    "AdminConfig",
    "AuthMethod",
    # Auth
    "AuthManager",
    # Session
    "SessionInfo",
    "SessionManager",
    # Rendering
    "ImageData",
    "ImageRenderer",
    "MarkdownRenderer",
    "extract_image_urls",
    "extract_artifact_urls",
    # Facade
    "AdeptFacade",
    "ArtifactData",
    "ChatResult",
    "AGUIChatResult",
]
