"""
Session Navigator Component for Streamlit

Provides UI for browsing, summarizing, and loading previous conversation sessions
from the database. Integrates with Session Management Phase 1 schema.
"""

import asyncio
import uuid
from typing import List, Dict, Optional
import streamlit as st
from sqlalchemy import select, update, cast, TEXT
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from agentic_framework_pkg.orchestration_service.persistence.checkpointing import (
    get_async_session,
)
from agentic_framework_pkg.orchestration_service.models.session_models import (
    UserSession,
    SessionMessage,
)
from agentic_framework_pkg.core.llm_agnostic_layer import LLMAgnosticClient
from agentic_framework_pkg.logger_config import get_logger

logger = get_logger(__name__)


class SessionNavigator:
    """
    Streamlit component for browsing, summarizing, and loading previous sessions.

    Features:
    - Session list dropdown (most recent first)
    - AI-powered 5-word and 10-word summaries
    - Session loading with context injection
    - Summary caching in database metadata
    """

    def __init__(self, user_id: str, username: str):
        """
        Initialize SessionNavigator.

        Args:
            user_id: User identifier (extracted from JWT token or username)
            username: Username from Keycloak authentication
        """
        self.user_id = user_id
        self.username = username
        self.llm_layer: Optional[LLMAgnosticClient] = None  # Lazy initialization

    def render(self) -> None:
        """
        Render session navigation UI in Streamlit sidebar.

        This is the synchronous entry point for Streamlit. It wraps the async
        implementation with asyncio.run() to handle database queries.
        """
        try:
            asyncio.run(self._render_async())
        except Exception as e:
            logger.error(f"Failed to render session navigator: {e}", exc_info=True)
            st.error("Failed to load session navigator. Please try again.")

    async def _render_async(self) -> None:
        """
        Async implementation of session navigation UI rendering.

        Queries database for user sessions, displays dropdown with summaries,
        and handles session loading logic.
        """
        # Session filter controls
        col1, col2, col3 = st.columns(3)

        with col1:
            status_filter = st.selectbox(
                "Status:",
                options=["active", "all", "archived"],
                index=0,  # Default to "active"
                key="session_status_filter",
            )

        with col2:
            limit = st.slider(
                "Max sessions:",
                min_value=10,
                max_value=100,
                value=50,
                step=10,
                key="session_limit_slider",
            )

        with col3:
            show_count = st.checkbox(
                "Show count",
                value=True,
                key="session_show_count_checkbox",
            )

        # Query recent sessions with dynamic filters
        sessions = await self._get_user_sessions(
            limit=limit, status_filter=status_filter if status_filter != "all" else None
        )

        if not sessions:
            st.info("No previous sessions found. Start a new conversation!")
            return

        # Display session count if enabled
        if show_count:
            st.caption(f"📊 Found {len(sessions)} session(s)")

        # Prepare session options for dropdown with explicit deduplication
        session_options = {}
        seen_session_ids = set()

        for session in sessions:
            # Skip duplicates explicitly (defensive check)
            if session.session_id in seen_session_ids:
                logger.warning(f"Duplicate session_id detected: {session.session_id}")
                continue

            seen_session_ids.add(session.session_id)
            label = self._format_session_label(session)
            session_options[session.session_id] = label

        # Dropdown for session selection
        selected_session_id = st.selectbox(
            "Select a session:",
            options=list(session_options.keys()),
            format_func=lambda sid: session_options[sid],
            key="session_selector",
        )

        # Info box with 10-word summary
        if selected_session_id:
            selected_session = next(
                s for s in sessions if s.session_id == selected_session_id
            )
            summary_10w = await self._get_or_generate_summary(
                selected_session, word_count=10
            )
            st.info(f"**Summary**: {summary_10w}")

            # Display session metadata
            st.caption(
                f"Last active: {selected_session.last_active_at.strftime('%Y-%m-%d %H:%M')}"
            )
            st.caption(f"Created: {selected_session.created_at.strftime('%Y-%m-%d')}")

            # Load Session button
            if st.button("Load Session", key="load_session_btn"):
                with st.spinner("Loading session..."):
                    await self._load_session_into_state(selected_session_id)
                    st.success(
                        f"✅ Session loaded! {len(st.session_state.conversation_history)} messages restored."
                    )
                    st.rerun()

    async def _get_user_sessions(
        self, limit: int = 50, status_filter: Optional[str] = "active"
    ) -> List[UserSession]:
        """
        Query recent sessions for current user from database.

        Args:
            limit: Maximum number of sessions to retrieve (default: 50)
            status_filter: Filter by status ("active", "archived", or None for all)

        Returns:
            List of UserSession objects ordered by last_active_at DESC
        """
        try:
            async with get_async_session() as db_session:
                stmt = select(UserSession).where(UserSession.user_id == self.user_id)

                # Apply status filter if specified
                if status_filter:
                    stmt = stmt.where(UserSession.status == status_filter)

                stmt = stmt.order_by(UserSession.last_active_at.desc()).limit(limit)

                result = await db_session.execute(stmt)
                sessions = result.scalars().all()
                logger.info(
                    f"Retrieved {len(sessions)} sessions for user {self.user_id} (status: {status_filter or 'all'})"
                )
                return sessions
        except Exception as e:
            logger.error(f"Failed to load sessions for user {self.user_id}: {e}")
            st.error("Failed to load previous sessions. Please try again.")
            return []

    async def _load_session_messages(self, session_id: str) -> List[Dict]:
        """
        Load all messages for a session from database.

        Args:
            session_id: Session identifier

        Returns:
            List of message dictionaries with 'role' and 'content' keys,
            ordered by message_index ASC
        """
        try:
            async with get_async_session() as db_session:
                stmt = (
                    select(SessionMessage)
                    .where(SessionMessage.session_id == session_id)
                    .order_by(SessionMessage.message_index.asc())
                )
                result = await db_session.execute(stmt)
                messages = result.scalars().all()

                logger.info(f"Loaded {len(messages)} messages for session {session_id}")

                return [
                    {"role": msg.message_role, "content": msg.message_content or ""}
                    for msg in messages
                ]
        except Exception as e:
            logger.error(f"Failed to load messages for session {session_id}: {e}")
            return []

    async def _load_session_into_state(self, session_id: str):
        """
        Load session messages into Streamlit session state.

        Args:
            session_id: Session identifier to load

        Updates:
            - st.session_state.conversation_history: List of messages
            - st.session_state.response_session_id: Loaded session ID
        """
        try:
            messages = await self._load_session_messages(session_id)
            if not messages:
                st.warning("This session has no messages.")
                return

            # Update Streamlit session state
            st.session_state.conversation_history = messages
            st.session_state.response_session_id = session_id

            logger.info(
                f"Loaded session {session_id} into Streamlit state ({len(messages)} messages)"
            )
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            st.error("Failed to load session. Please try again.")

    async def _generate_summary(self, session_id: str, word_count: int = 5) -> str:
        """
        Generate AI-powered session summary using LLM.

        Args:
            session_id: Session identifier
            word_count: Target word count for summary (5 or 10)

        Returns:
            Generated summary string
        """
        try:
            # Get first 10 messages from session
            messages = await self._load_session_messages(session_id)
            if not messages:
                return f"Session {session_id[:8]}"

            messages = messages[:10]  # Limit to first 10 messages

            # Format conversation text
            conversation_text = "\n".join(
                [
                    f"{msg['role'].upper()}: {msg['content'][:200]}..."
                    for msg in messages
                ]
            )

            # Prepare prompt
            prompt = f"""Summarize the following conversation in exactly {word_count} words. Be concise and descriptive.

Conversation:
{conversation_text}

Summary ({word_count} words):"""

            # Initialize LLM layer lazily
            if self.llm_layer is None:
                self.llm_layer = LLMAgnosticClient()

            # Generate summary using agenerate_response with ISOLATED context
            # Each summarization gets a unique thread_id to prevent context pollution
            summary_thread_id = f"summary_{session_id}_{uuid.uuid4().hex[:8]}"

            messages = [{"role": "user", "content": prompt}]
            response = await self.llm_layer.agenerate_response(
                messages=messages,
                llm_purpose="session_summary",  # Dedicated purpose for summarization
                max_tokens=50,
                # Note: temperature omitted for o4-mini compatibility (o-series only support temperature=1)
                stream=False,
                thread_id=summary_thread_id,  # Isolated thread for token tracking
                # NOTE: NO session_id passed → No message persistence to database
            )

            # Extract content from LiteLLM response object
            if hasattr(response, "choices") and response.choices:
                summary = response.choices[0].message.content.strip().split("\n")[0]
            else:
                # Fallback if response format is unexpected
                summary = str(response).strip().split("\n")[0]
            logger.info(
                f"Generated {word_count}-word summary for session {session_id}: {summary}"
            )
            return summary

        except Exception as e:
            logger.warning(f"Summary generation failed for session {session_id}: {e}")
            # Fall back to first N words
            messages = await self._load_session_messages(session_id)
            if messages and messages[0]["content"]:
                first_content = messages[0]["content"]
                words = first_content.split()[:word_count]
                return " ".join(words)
            return f"Session {session_id[:8]}"

    async def _get_or_generate_summary(
        self, session: UserSession, word_count: int = 5
    ) -> str:
        """
        Get cached summary or generate new one.

        Args:
            session: UserSession object
            word_count: Target word count (5 or 10)

        Returns:
            Summary string (from cache or freshly generated)
        """
        cache_key = f"summary_{word_count}w"

        # Check cache
        if session.session_metadata and cache_key in session.session_metadata:
            cached_summary = session.session_metadata[cache_key]
            logger.debug(
                f"Using cached {word_count}-word summary for session {session.session_id}"
            )
            return cached_summary

        # Generate summary
        summary = await self._generate_summary(session.session_id, word_count)

        # Cache it
        await self._cache_summary(session.session_id, cache_key, summary)

        return summary

    async def _cache_summary(self, session_id: str, cache_key: str, summary: str):
        """
        Cache summary in session metadata JSONB field.

        Args:
            session_id: Session identifier
            cache_key: Cache key (e.g., "summary_5w" or "summary_10w")
            summary: Summary string to cache
        """
        try:
            async with get_async_session() as db_session:
                # Update session metadata using PostgreSQL JSONB concatenation
                # Note: jsonb_set requires proper type casting:
                #   - path must be text[] (array of text)
                #   - value must be jsonb
                stmt = (
                    update(UserSession)
                    .where(UserSession.session_id == session_id)
                    .values(
                        session_metadata=func.jsonb_set(
                            UserSession.session_metadata,
                            cast(
                                f"{{{cache_key}}}", ARRAY(TEXT)
                            ),  # Cast path to text[]
                            cast(f'"{summary}"', JSONB),  # Cast value to jsonb
                            True,  # create_missing
                        )
                    )
                )
                await db_session.execute(stmt)
                await db_session.commit()

                logger.info(
                    f"Cached summary for session {session_id}: {cache_key} = {summary}"
                )
        except Exception as e:
            logger.warning(f"Failed to cache summary for session {session_id}: {e}")

    def _format_session_label(self, session: UserSession) -> str:
        """
        Format dropdown label from session metadata.

        Fallback hierarchy:
        1. Cached summary_5w from session_metadata
        2. User-defined title
        3. Enhanced session info (date, unique ID suffix, tokens, cost)

        Args:
            session: UserSession object

        Returns:
            Formatted label string for dropdown display
        """
        # Try cached summary with timestamp
        if session.session_metadata and "summary_5w" in session.session_metadata:
            summary = session.session_metadata["summary_5w"]
            date = session.last_active_at.strftime("%Y-%m-%d %H:%M")
            session_id_short = session.session_id[-8:]  # Last 8 chars (unique part)
            return f"{summary} | {date} | ...{session_id_short}"

        # Try user-defined title with metadata
        if session.title:
            date = session.last_active_at.strftime("%Y-%m-%d %H:%M")
            session_id_short = session.session_id[-8:]
            tokens = f"{session.total_tokens:,}" if session.total_tokens else "0"
            return f"{session.title[:30]} | {date} | ...{session_id_short} | {tokens} tokens"

        # Enhanced fallback with distinguishing information
        date = session.last_active_at.strftime("%Y-%m-%d %H:%M")
        session_id_short = session.session_id[-8:]  # Last 8 chars for uniqueness

        # Add token count and cost for additional context
        tokens = f"{session.total_tokens:,}" if session.total_tokens else "0"
        cost = f"${session.estimated_cost_usd:.4f}" if session.estimated_cost_usd else "$0.00"

        return f"{date} | ...{session_id_short} | {tokens} tokens | {cost}"
