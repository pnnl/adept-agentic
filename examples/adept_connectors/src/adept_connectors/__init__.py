"""ADEPT Connectors — unified connector library for all ADEPT platform clients.

Quick start::

    from adept_connectors import ConnectorProfile, AuthManager, AdeptFacade

See https://github.com/pnnl/adept-agentic/wiki/ADEPT-Connectors for full documentation.
"""

__version__ = "0.1.0"

from .core import (
    AdeptConnectorConfig,
    AdeptFacade,
    AGUIChatResult,
    AuthManager,
    AuthMethod,
    ChatResult,
    ConnectorProfile,
    ImageData,
    ImageRenderer,
    MarkdownRenderer,
    SessionInfo,
    SessionManager,
)

__all__ = [
    "__version__",
    "AdeptConnectorConfig",
    "AdeptFacade",
    "AGUIChatResult",
    "AuthManager",
    "AuthMethod",
    "ChatResult",
    "ConnectorProfile",
    "ImageData",
    "ImageRenderer",
    "MarkdownRenderer",
    "SessionInfo",
    "SessionManager",
]
