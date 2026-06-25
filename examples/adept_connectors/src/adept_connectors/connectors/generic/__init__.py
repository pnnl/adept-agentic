"""Generic auth proxy connector for zero-code IDE tools.

Provides a transparent OpenAI-compatible proxy that handles ADEPT
authentication (API key, JWT, or Keycloak ROPC) so that any tool
supporting the OpenAI API can connect to ADEPT with zero code changes.

Supported tools: Roo Code, Continue.dev, Cursor, OBot.ai, AG-UI clients.
"""

from __future__ import annotations

from .proxy import create_proxy_app

__all__ = ["create_proxy_app"]
