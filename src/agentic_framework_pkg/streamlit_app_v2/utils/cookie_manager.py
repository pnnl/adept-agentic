import os
import warnings
from typing import Optional

import streamlit as st

# Suppress st.cache deprecation warning from streamlit-cookies-manager library
warnings.filterwarnings("ignore", category=DeprecationWarning, module="streamlit.legacy_caching.caching")
warnings.filterwarnings("ignore", message=".*st\\.cache.*")

from streamlit_cookies_manager import EncryptedCookieManager

# Cookie configuration
COOKIE_NAME = "agentic_framework_auth"
COOKIE_EXPIRY_DAYS = 7
COOKIE_ENCRYPTION_KEY = os.getenv(
    "COOKIE_ENCRYPTION_KEY", "change-this-in-production-minimum-32-chars"
)


def get_cookie_manager() -> EncryptedCookieManager:
    """Get or initialize cookie manager in session state."""
    if "cookie_manager" not in st.session_state:
        st.session_state.cookie_manager = EncryptedCookieManager(
            prefix="agentic_framework_", password=COOKIE_ENCRYPTION_KEY
        )

    # Always check if cookies are ready before returning
    if not st.session_state.cookie_manager.ready():
        st.stop()

    return st.session_state.cookie_manager


def store_auth_cookie(username: str, token: str) -> None:
    """Store authentication data in encrypted cookie."""
    try:
        cookie_mgr = get_cookie_manager()
        cookie_mgr[COOKIE_NAME] = f"{username}::{token}"
        cookie_mgr.save()
    except Exception as e:
        # Cookies not ready yet or other error - log but don't crash
        import logging
        logging.warning(f"Failed to store auth cookie: {e}")


def retrieve_auth_cookie() -> Optional[tuple[str, str]]:
    """Retrieve authentication data from cookie."""
    try:
        cookie_mgr = get_cookie_manager()
        auth_data = cookie_mgr.get(COOKIE_NAME)

        if auth_data and "::" in auth_data:
            username, token = auth_data.split("::", 1)
            return (username, token)
        return None
    except Exception:
        # Cookies not ready yet or other error - return None
        return None


def clear_auth_cookie() -> None:
    """Clear authentication cookie."""
    try:
        cookie_mgr = get_cookie_manager()
        if COOKIE_NAME in cookie_mgr:
            del cookie_mgr[COOKIE_NAME]
            cookie_mgr.save()
    except Exception as e:
        # Cookies not ready yet or other error - log but don't crash
        import logging
        logging.warning(f"Failed to clear auth cookie: {e}")
