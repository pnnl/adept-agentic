"""Enhanced Session Manager Page

This page provides advanced session browsing, filtering, and management capabilities
through the Enhanced Session Navigator component.
"""

import os
import warnings

import jwt
import requests
import streamlit as st

# Suppress st.cache deprecation warning from streamlit-cookies-manager library
warnings.filterwarnings("ignore", category=DeprecationWarning, module="streamlit.legacy_caching.caching")
warnings.filterwarnings("ignore", message=".*st\\.cache.*")

from streamlit_cookies_manager import EncryptedCookieManager

from agentic_framework_pkg.logger_config import get_logger
from agentic_framework_pkg.streamlit_app_v2.components.session_navigator_enhanced import (
    EnhancedSessionNavigator,
)

logger = get_logger(__name__)

# --- CRITICAL: Initialize Cookie Manager FIRST (before st.set_page_config) ---
# This ensures the JavaScript component loads before any Streamlit content renders
COOKIE_ENCRYPTION_KEY = os.getenv(
    "COOKIE_ENCRYPTION_KEY", "change-this-in-production-minimum-32-chars"
)

# Initialize cookie manager (singleton pattern - created once per session)
if "cookie_manager" not in st.session_state:
    st.session_state.cookie_manager = EncryptedCookieManager(
        prefix="agentic_framework_",
        password=COOKIE_ENCRYPTION_KEY
    )

cookies = st.session_state.cookie_manager

# Check if cookies are ready - with timeout and graceful degradation
# Cookie manager may fail to initialize in dual access mode due to URL configuration
import time
cookie_ready_timeout = 3.0  # seconds

# Initialize timeout tracking in session state (persist across reruns)
if "cookie_check_start_time" not in st.session_state:
    st.session_state.cookie_check_start_time = time.time()
if "cookie_timeout_checked" not in st.session_state:
    st.session_state.cookie_timeout_checked = False

if not cookies.ready():
    elapsed_time = time.time() - st.session_state.cookie_check_start_time

    # Check if we've exceeded the timeout
    if elapsed_time > cookie_ready_timeout or st.session_state.cookie_timeout_checked:
        # Cookie manager failed - show warning but allow page to continue
        st.session_state.cookie_timeout_checked = True

        st.warning("⚠️ Session persistence unavailable - cookies may not persist across page refreshes.")

        with st.expander("🔍 Technical Details (Session 36 - Dual Access Mode Investigation)"):
            st.info("**Cookie Manager Status**: Initialization timeout")
            st.json({
                "STREAMLIT_BASE_URL_PATH": os.getenv("STREAMLIT_BASE_URL_PATH", "(not set)"),
                "STREAMLIT_EXTERNAL_URL": os.getenv("STREAMLIT_EXTERNAL_URL", "(not set)"),
                "cookies_ready": False,
                "timeout_seconds": cookie_ready_timeout,
                "elapsed_seconds": round(elapsed_time, 2)
            })
            st.markdown("""
            **Impact**: Session data may reset on page refresh.

            **Workaround**: Keep this browser tab open. Avoid refreshing the page.

            **For Developers**: See `docs/troubleshooting/SESSION_36_COOKIE_MANAGER_INVESTIGATION.md`
            """)

        # Continue with page execution (graceful degradation)
        logger.warning("Cookie manager initialization timeout - continuing without cookie persistence")
    else:
        # Still waiting for cookie manager - show loading message and rerun
        st.info(f"🔄 Initializing session management... ({round(elapsed_time, 1)}s / {cookie_ready_timeout}s)")
        time.sleep(0.5)  # Small delay before rerun
        st.rerun()

# Cookie name constant (matches cookie_manager.py)
COOKIE_NAME = "agentic_framework_auth"

# Check for existing cookie authentication (only if cookies are ready)
if "logged_in" not in st.session_state:
    auth_data = None
    try:
        if cookies.ready():
            auth_data = cookies.get(COOKIE_NAME)
    except Exception as e:
        logger.warning(f"Failed to retrieve cookie (cookie manager not ready): {e}")
        auth_data = None

    if auth_data and "::" in auth_data:
        username, token = auth_data.split("::", 1)
        # Verify token is still valid (optional: add Keycloak introspection check)
        st.session_state.logged_in = True
        st.session_state.api_key = token
        st.session_state.username = username
        st.session_state.stored_username = username
    else:
        st.session_state.logged_in = False


def get_user_id_from_token(token: str) -> str:
    """Extract user_id from Keycloak JWT token."""
    try:
        decoded = jwt.decode(token, options={"verify_signature": False})
        return decoded.get("sub")  # Subject claim is user ID
    except Exception as e:
        logger.warning(f"Failed to decode JWT: {e}")
        return st.session_state.get("username", "unknown")


def logout():
    """Perform full logout: revoke token, clear cookie, clear session state."""
    # Revoke Keycloak token (optional, for security best practice)
    if "api_key" in st.session_state:
        try:
            keycloak_url = os.getenv("KEYCLOAK_URL", "http://keycloak:8180")
            revoke_url = f"{keycloak_url}/realms/agentic-framework/protocol/openid-connect/revoke"

            requests.post(
                revoke_url,
                data={
                    "token": st.session_state.api_key,
                    "client_id": "agent-gateway-client",
                },
                timeout=5,
            )
        except Exception as e:
            # Log error but continue logout
            logger.warning(f"Token revocation failed: {e}")

    # Clear cookie using global cookies object (only if cookies are ready)
    try:
        if cookies.ready() and COOKIE_NAME in cookies:
            del cookies[COOKIE_NAME]
            cookies.save()
    except Exception as e:
        logger.warning(f"Failed to clear cookie (cookie manager not ready): {e}")

    # Clear session state
    st.session_state.logged_in = False
    st.session_state.api_key = None
    st.session_state.username = None
    st.session_state.clear()

    st.rerun()


# Page configuration
st.set_page_config(page_title="Session Manager", page_icon="📊", layout="wide")

# Check authentication
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.error("🔒 Please log in from the main page first")
    st.stop()

# Add logout button to sidebar (for logged-in users)
with st.sidebar:
    st.divider()
    if st.button("🚪 Log Out", use_container_width=True):
        logout()

# Page header
st.title("📊 Enhanced Session Manager")
st.markdown("""
Advanced session browsing, filtering, and management capabilities for your AI workflows.

**Features:**
- 🔍 Advanced filtering (status, tags, date ranges, cost/token thresholds)
- 🔎 Full-text search across session metadata
- 📄 Pagination with configurable page size
- 📊 Session details and statistics
- ✏️ Session management actions (rename, archive, delete)
- ☑️ Multi-select with bulk archive and delete operations
""")

st.divider()

# Get user context - extract user_id from JWT token (not fallback to username string)
# This ensures we always use the UUID from Keycloak, preventing user_id mismatch bugs
user_id = get_user_id_from_token(st.session_state.api_key)
username = st.session_state.username

logger.info(f"Session Manager: user_id={user_id}, username={username}")

# Render Enhanced Session Navigator
try:
    navigator = EnhancedSessionNavigator(user_id=user_id, username=username)
    navigator.render()
except Exception as e:
    logger.error(f"Failed to render Enhanced Session Navigator: {e}", exc_info=True)
    st.error("❌ Failed to load Enhanced Session Navigator. Please try again later.")
    st.exception(e)

    # Provide fallback information
    st.info("""
    **Troubleshooting:**
    - Check that the database is accessible
    - Verify your session is still valid
    - Try refreshing the page
    - Contact support if the issue persists
    """)
