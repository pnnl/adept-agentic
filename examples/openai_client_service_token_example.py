#!/usr/bin/env python3
"""
OpenAI Client with Service API Token Example (Standalone)

OVERVIEW:
This example demonstrates how to use ADEPT's OpenAI-compatible API with service API tokens
instead of user JWT tokens. It works STANDALONE without requiring the ADEPT framework library.

KEY DIFFERENCES FROM STREAMLIT CHAT.PY:
┌──────────────────────┬───────────────────────────┬────────────────────────────┐
│ Aspect               │ Streamlit Chat.py (User)  │ This Example (Service)     │
├──────────────────────┼───────────────────────────┼────────────────────────────┤
│ Authentication       │ Keycloak OAuth2 (user)    │ Service API token          │
│ Token Source         │ get_user_token() login    │ Environment variable       │
│ Token Type           │ JWT (short-lived, 8h)     │ Bearer (long-lived, 90d)   │
│ Token Refresh        │ Required (refresh_token)  │ Not required               │
│ User Identity        │ Actual user (sub claim)   │ Service identity           │
│ Session Tracking     │ Streamlit session_id      │ Custom session_id          │
│ Use Case             │ Interactive UI            │ Automation/scripts         │
└──────────────────────┴───────────────────────────┴────────────────────────────┘

WHEN TO USE SERVICE TOKENS vs USER JWT:
Use Service Tokens When:
  ✅ Non-interactive automation (CI/CD, cron jobs)
  ✅ Long-running background processes
  ✅ External service integration (n8n, OpenWebUI)
  ✅ Testing and validation scripts
  ✅ No user login UI required

Use User JWT When:
  ✅ Interactive web applications (Streamlit, JupyterLab)
  ✅ User-initiated actions requiring attribution
  ✅ Need actual user identity for authorization
  ✅ Session management tied to user login/logout

STANDALONE INSTALLATION:
1. Install dependencies:
   pip install -r examples/requirements.txt
   # Or manually: pip install openai httpx

2. Create service API token (requires ADEPT framework access):
   make create-service-token NAME=my-service GROUPS=notebook-users TTL_DAYS=90

3. Set environment variable:
   export ADEPT_SERVICE_API_TOKEN="sk-service-..."

4. Run example:
   python examples/openai_client_service_token_example.py

OPTIONAL FEATURES:
- Session tracking (requires ADEPT framework libraries installed)
- Advanced logging (gracefully degrades to standard logging)
"""
import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime
from typing import Optional

import openai

# =============================================================================
# LOGGING CONFIGURATION (STANDALONE MODE)
# =============================================================================

# Try to import ADEPT logger, fall back to standard logging
try:
    sys.path.insert(
        0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
    )
    from agentic_framework_pkg.logger_config import get_logger

    logger = get_logger(__name__)
    ADEPT_LOGGING_AVAILABLE = True
except ImportError:
    # Standalone mode: use standard logging
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)
    ADEPT_LOGGING_AVAILABLE = False
    logger.info("Running in STANDALONE mode (ADEPT logging not available)")

# =============================================================================
# SESSION TRACKING (OPTIONAL - REQUIRES ADEPT FRAMEWORK)
# =============================================================================

# Try to import ADEPT session management, gracefully degrade if not available
try:
    from agentic_framework_pkg.orchestration_service.models.session_models import (
        UserSession,
    )
    from agentic_framework_pkg.orchestration_service.persistence.checkpointing import (
        get_async_session,
    )

    ADEPT_SESSION_TRACKING_AVAILABLE = True
except ImportError:
    ADEPT_SESSION_TRACKING_AVAILABLE = False
    logger.info(
        "ADEPT session tracking not available (framework libraries not installed)"
    )


# =============================================================================
# STEP 1: GET OPENAI CLIENT WITH SERVICE TOKEN (STANDALONE)
# =============================================================================


def get_openai_client_with_service_token() -> Optional[openai.OpenAI]:
    """
    Create OpenAI client using service API token.

    This is a STANDALONE function that works without ADEPT framework libraries.
    It only requires the openai package and an environment variable.

    Streamlit Pattern (Chat.py:172-178) - Requires ADEPT:
        def get_openai_client():
            if "api_key" in st.session_state and st.session_state.api_key:
                return openai.OpenAI(
                    base_url=f"{AGENT_GATEWAY_URL}/responses",
                    api_key=st.session_state.api_key  # User JWT
                )
            return None

    Service Pattern (This Function) - STANDALONE:
        - Uses ADEPT_SERVICE_API_TOKEN environment variable
        - Standard /v1 endpoint (not /responses)
        - Long-lived bearer token (90 days default)
        - No token refresh required

    Returns:
        OpenAI client configured for ADEPT API, or None if token not found
    """
    service_token = os.getenv("ADEPT_SERVICE_API_TOKEN")

    if not service_token:
        logger.error("ADEPT_SERVICE_API_TOKEN environment variable not set")
        logger.error("Create a token with:")
        logger.error(
            "  make create-service-token NAME=my-service GROUPS=notebook-users"
        )
        return None

    # Use standard OpenAI-compatible endpoint
    base_url = os.getenv("AGENT_GATEWAY_URL", "https://api.agentic.local/v1")

    logger.info(f"Creating OpenAI client with service token")
    logger.info(f"  Base URL: {base_url}")
    logger.info(f"  Token prefix: {service_token[:20]}...")

    return openai.OpenAI(
        base_url=base_url,
        api_key=service_token,  # Service API token (not JWT)
    )


# =============================================================================
# STEP 2: CREATE ADEPT SESSION FOR TRACKING (OPTIONAL)
# =============================================================================


async def create_adept_session(
    service_name: str,
    session_type: str = "service_automation",
) -> str:
    """
    Create ADEPT session for service tracking (OPTIONAL).

    This function mimics the pattern from session_utils.py:create_session_in_db()
    but is OPTIONAL - the OpenAI client works fine without it.

    REQUIRES: ADEPT framework libraries (gracefully degrades if not available)

    Streamlit Pattern (session_utils.py:56-85) - Requires ADEPT:
        async def create_session_in_db(session_id, user_id, username, session_type):
            async with get_async_session() as db_session:
                new_session = UserSession(
                    session_id=session_id,
                    user_id=user_id,        # From JWT sub claim
                    username=username,
                    session_type=session_type,
                    status="active",
                )
                db_session.add(new_session)
                await db_session.commit()

    Service Pattern (This Function) - Optional:
        - Generates unique session_id (UUID)
        - Uses service name as user_id and username
        - Session type indicates automation/service context
        - Tracked in same user_sessions table

    Args:
        service_name: Service identifier (e.g., "my-automation-service")
        session_type: Session type descriptor (default: "service_automation")

    Returns:
        Session ID (UUID string)
    """
    session_id = str(uuid.uuid4())

    if not ADEPT_SESSION_TRACKING_AVAILABLE:
        logger.warning(
            "ADEPT session tracking not available - continuing without session persistence"
        )
        logger.warning(
            "Session operations will still work, but won't be tracked in database"
        )
        return session_id

    try:
        async with get_async_session() as db_session:
            new_session = UserSession(
                session_id=session_id,
                user_id=f"service-{service_name}",  # Service identity (not user sub)
                username=f"{service_name}-service",
                session_type=session_type,
                status="active",
            )
            db_session.add(new_session)
            await db_session.commit()

            logger.info(
                f"Created ADEPT session for service: {service_name} (session_id={session_id})"
            )

    except Exception as e:
        logger.error(f"Failed to create ADEPT session: {e}", exc_info=True)
        logger.warning(
            "Continuing without session tracking (operations will still work)"
        )

    return session_id


# =============================================================================
# STEP 3: EXAMPLE USAGE - CHAT COMPLETION WITH SERVICE TOKEN
# =============================================================================


def example_chat_completion_with_service_token():
    """
    Demonstrate chat completion using service API token (STANDALONE).

    This shows the complete workflow:
    1. Get OpenAI client with service token (STANDALONE - no ADEPT required)
    2. [Optional] Create ADEPT session for tracking (requires ADEPT framework)
    3. Make chat completion call (STANDALONE - just OpenAI)
    4. Handle response (STANDALONE)
    """
    print("\n" + "=" * 80)
    print("OpenAI Client with Service API Token Example (STANDALONE)")
    print("=" * 80)

    # Step 1: Get OpenAI client with service token (STANDALONE)
    print("\n[Step 1] Creating OpenAI client with service API token...")
    print("  Mode: STANDALONE (no ADEPT framework required)")
    client = get_openai_client_with_service_token()

    if not client:
        print("\n❌ Failed to create OpenAI client. Check ADEPT_SERVICE_API_TOKEN.")
        return

    print("✅ OpenAI client created successfully")

    # Step 2: Create ADEPT session for tracking (OPTIONAL)
    print(
        "\n[Step 2] Creating ADEPT session for tracking (optional, requires ADEPT)..."
    )
    service_name = os.getenv("SERVICE_NAME", "example-automation-service")

    if ADEPT_SESSION_TRACKING_AVAILABLE:
        session_id = asyncio.run(
            create_adept_session(
                service_name=service_name, session_type="service_automation_example"
            )
        )
        print(f"✅ ADEPT session created: {session_id}")
    else:
        session_id = str(uuid.uuid4())
        print(
            f"⚠️  ADEPT session tracking unavailable, using local UUID: {session_id}"
        )
        print("   (Operations will still work, just won't be persisted to database)")

    # Step 3: Make chat completion call (STANDALONE)
    print("\n[Step 3] Making chat completion call (STANDALONE)...")
    print("  Query: 'What is the capital of France?'")

    try:
        response = client.chat.completions.create(
            model="agentic-framework:scientific-agent-v1",  # ADEPT implements own model
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant for the ADEPT framework.",
                },
                {"role": "user", "content": "What is the capital of France?"},
            ],
            temperature=0.7,
            max_tokens=150,
            extra_headers={
                "X-Thread-Id": session_id,  # Session tracking (optional)
            },
        )

        # Step 4: Handle response (STANDALONE)
        print("\n[Step 4] Response received:")
        print("-" * 80)
        print(response.choices[0].message.content)
        print("-" * 80)

        # Show token usage
        if response.usage:
            print(f"\nToken Usage:")
            print(f"  Prompt tokens: {response.usage.prompt_tokens}")
            print(f"  Completion tokens: {response.usage.completion_tokens}")
            print(f"  Total tokens: {response.usage.total_tokens}")

        print("\n✅ Example completed successfully!")

    except Exception as e:
        print(f"\n❌ Error during chat completion: {e}")
        logger.error(f"Chat completion failed: {e}", exc_info=True)

    print("\n" + "=" * 80)
    print("Service Token vs User JWT Summary")
    print("=" * 80)
    print("\n✅ Service Token Benefits:")
    print("  - No login UI required")
    print("  - No token refresh logic needed")
    print("  - Long-lived (90 days default)")
    print("  - Ideal for automation and scripts")
    print("  - STANDALONE (no ADEPT framework required)")
    print("\n⚠️  User JWT Benefits:")
    print("  - Actual user identity attribution")
    print("  - Interactive login/logout flow")
    print("  - Session tied to user authentication")
    print("  - Ideal for web applications")
    print("\n" + "=" * 80 + "\n")


# =============================================================================
# STEP 4: ADVANCED EXAMPLE - STREAMING RESPONSES (STANDALONE)
# =============================================================================


def example_streaming_with_service_token():
    """
    Demonstrate streaming chat completion with service API token (STANDALONE).
    """
    print("\n" + "=" * 80)
    print("Streaming Chat Completion Example (STANDALONE)")
    print("=" * 80)

    client = get_openai_client_with_service_token()
    if not client:
        return

    print("\n[Streaming] Query: 'Explain photosynthesis in 50 words'")
    print("-" * 80)

    try:
        stream = client.chat.completions.create(
            model="agentic-framework:scientific-agent-v1",
            messages=[
                {"role": "user", "content": "Explain photosynthesis in 50 words"}
            ],
            stream=True,
            max_tokens=100,
        )

        full_response = ""
        for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                print(content, end="", flush=True)
                full_response += content

        print("\n" + "-" * 80)
        print(f"\n✅ Streaming completed ({len(full_response)} characters received)")

    except Exception as e:
        print(f"\n❌ Streaming failed: {e}")
        logger.error(f"Streaming failed: {e}", exc_info=True)

    print("\n" + "=" * 80 + "\n")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main():
    """Main entry point for examples."""
    # Print runtime mode
    print("\n" + "=" * 80)
    print("Runtime Mode Detection")
    print("=" * 80)
    print(f"ADEPT Logging Available: {'✅ Yes' if ADEPT_LOGGING_AVAILABLE else '❌ No (using standard logging)'}")
    print(
        f"ADEPT Session Tracking: {'✅ Yes' if ADEPT_SESSION_TRACKING_AVAILABLE else '❌ No (optional feature disabled)'}"
    )
    print(
        "\n💡 This example works in STANDALONE mode without ADEPT framework libraries."
    )
    print("   Session tracking is optional and will gracefully degrade if unavailable.")
    print("=" * 80)

    # Check prerequisites
    if not os.getenv("ADEPT_SERVICE_API_TOKEN"):
        print("\n" + "=" * 80)
        print("❌ ADEPT_SERVICE_API_TOKEN Not Set")
        print("=" * 80)
        print("\nThis example requires a service API token.")
        print("\nSetup Instructions:")
        print(
            "  1. Create token: make create-service-token NAME=my-service GROUPS=notebook-users"
        )
        print('  2. Set env var: export ADEPT_SERVICE_API_TOKEN="sk-service-..."')
        print(
            "  3. Run example: python examples/openai_client_service_token_example.py"
        )
        print("\n" + "=" * 80 + "\n")
        sys.exit(1)

    # Run examples
    example_chat_completion_with_service_token()
    example_streaming_with_service_token()

    # Print next steps
    print("\n" + "=" * 80)
    print("Next Steps")
    print("=" * 80)

    if ADEPT_SESSION_TRACKING_AVAILABLE:
        print("\n1. View session in database:")
        print('   docker exec postgres psql -U admin -d postgres \\')
        print(
            '     -c "SELECT * FROM user_sessions WHERE session_type=\'service_automation_example\';"'
        )
    else:
        print("\n1. Enable session tracking (optional):")
        print("   Install ADEPT framework: pip install -e .")
        print("   Or run from within ADEPT container: docker exec orchestration_service ...")

    print("\n2. Compare with Streamlit Chat.py pattern:")
    print("   - File: src/agentic_framework_pkg/streamlit_app_v2/Chat.py")
    print("   - Line 172-178: get_openai_client() with user JWT")
    print("   - Line 56-85: create_session_in_db() with user identity")

    print("\n3. Integrate into your service:")
    print("   - Store ADEPT_SERVICE_API_TOKEN in secret manager")
    print("   - Use get_openai_client_with_service_token() pattern")
    print("   - Optionally create ADEPT sessions for tracking")

    print("\n4. Rotate token before expiration:")
    print("   - Check expiration: make list-service-tokens")
    print("   - Create new token: make create-service-token NAME=...")
    print("   - Update secret manager with new token")

    print("\n5. Install additional examples (optional):")
    print("   - LangGraph examples: pip install langgraph langchain-core litellm")
    print("   - See: examples/requirements.txt for full dependency list")

    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
