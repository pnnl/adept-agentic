"""
Unit Tests: Globus Token Exchange
==================================

Tests for globus_token_exchange.py — RFC 8693 token exchange and client credentials.
All tests run offline (mocked HTTP calls).
"""

import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add core package to path (only available when ADEPT src is mounted)
CORE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "src"
)
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

try:
    from agentic_framework_pkg.core.globus_token_exchange import (
        GlobusTokenResult,
        exchange_for_globus_token,
    )
except ImportError:
    pytest.skip(
        "agentic_framework_pkg not available (run via 'make test-globus' with ADEPT src mounted)",
        allow_module_level=True,
    )


class TestGlobusTokenResult:
    """Validate GlobusTokenResult dataclass."""

    def test_basic_construction(self):
        """Constructs with required fields."""
        result = GlobusTokenResult(
            access_token="abc123",
            expires_in=3600,
            token_type="Bearer",
            scope="openid",
        )
        assert result.access_token == "abc123"
        assert result.token_type == "Bearer"

    def test_expires_at_computed(self):
        """expires_at is auto-computed from expires_in."""
        before = time.time()
        result = GlobusTokenResult(
            access_token="x", expires_in=3600, token_type="Bearer", scope="openid"
        )
        after = time.time()
        assert before + 3600 <= result.expires_at <= after + 3600

    def test_is_expired_false_for_fresh(self):
        """Fresh token is not expired."""
        result = GlobusTokenResult(
            access_token="x", expires_in=3600, token_type="Bearer", scope="openid"
        )
        assert result.is_expired is False

    def test_is_expired_true_for_old(self):
        """Token with past expiry is expired."""
        result = GlobusTokenResult(
            access_token="x",
            expires_in=0,
            token_type="Bearer",
            scope="openid",
            expires_at=time.time() - 100,
        )
        assert result.is_expired is True


class TestExchangeForGlobusToken:
    """Validate exchange_for_globus_token behavior."""

    def test_returns_none_when_disabled(self, monkeypatch):
        """Returns None when GLOBUS_ENABLED=false."""
        monkeypatch.setenv("GLOBUS_ENABLED", "false")
        # Force reimport
        for mod in list(sys.modules.keys()):
            if "globus_token_exchange" in mod:
                del sys.modules[mod]
        from agentic_framework_pkg.core.globus_token_exchange import (
            exchange_for_globus_token,
        )
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            exchange_for_globus_token("fake-jwt")
        )
        assert result is None

    def test_returns_none_when_no_credentials(self, monkeypatch):
        """Returns None when GLOBUS_CLIENT_ID/SECRET not set."""
        monkeypatch.setenv("GLOBUS_ENABLED", "true")
        monkeypatch.setenv("GLOBUS_CLIENT_ID", "")
        monkeypatch.setenv("GLOBUS_CLIENT_SECRET", "")
        for mod in list(sys.modules.keys()):
            if "globus_token_exchange" in mod:
                del sys.modules[mod]
        from agentic_framework_pkg.core.globus_token_exchange import (
            exchange_for_globus_token,
        )
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            exchange_for_globus_token("fake-jwt")
        )
        assert result is None
