"""Shared fixtures for auth proxy tests."""

from __future__ import annotations

import os
import pytest

# Ensure env vars don't interfere with tests
os.environ.setdefault("ADEPT_API_KEY", "test-api-key-fixture")
os.environ.setdefault("ADEPT_AUTH_METHOD", "api_key")
