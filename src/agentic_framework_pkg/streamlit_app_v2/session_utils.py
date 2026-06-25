"""
Session utility functions for Streamlit v2 database operations.

This module provides reusable functions for session and message persistence,
extracted from Chat.py for testability and reusability across Streamlit v2 components.

Functions:
- get_user_id_from_token: Extract user_id from Keycloak JWT token
- create_session_in_db: Create user_sessions row for new Streamlit session
- save_message_to_db: Save message to session_messages table with last_active_at update

Module renamed from app.py to session_utils.py to avoid confusion with
Streamlit's common app.py naming convention (Session 36 Phase 11 Issue #4 fix).
"""

import jwt
import streamlit as st
from sqlalchemy import update
from sqlalchemy.sql import func

from agentic_framework_pkg.logger_config import get_logger
from agentic_framework_pkg.orchestration_service.models.session_models import (
    SessionMessage,
    UserSession,
)
from agentic_framework_pkg.orchestration_service.persistence.checkpointing import (
    get_async_session,
)

logger = get_logger(__name__)


def get_user_id_from_token(token: str) -> str:
    """
    Extract user_id from Keycloak JWT token.

    Args:
        token: Keycloak JWT token string

    Returns:
        User ID from token's 'sub' claim, or 'unknown' if decode fails
    """
    try:
        decoded = jwt.decode(token, options={"verify_signature": False})
        return decoded.get("sub")  # Subject claim is user ID
    except Exception as e:
        logger.warning(f"Failed to decode JWT: {e}")
        # Fallback to session state username if available (requires streamlit context)
        try:
            return st.session_state.get("username", "unknown")
        except RuntimeError:
            # No streamlit context (e.g., in tests)
            return "unknown"


async def create_session_in_db(
    session_id: str, user_id: str, username: str, session_type: str
):
    """
    Create user_sessions row for new Streamlit session.

    Args:
        session_id: Session identifier (UUID)
        user_id: User identifier from JWT token
        username: Username from Keycloak
        session_type: Session type ('response', 'multi_agent', etc.)

    Raises:
        Exception: If database operation fails (logged but not re-raised)
    """
    try:
        async with get_async_session() as db_session:
            new_session = UserSession(
                session_id=session_id,
                user_id=user_id,
                username=username,
                session_type=session_type,
                status="active",
            )
            db_session.add(new_session)
            await db_session.commit()
            logger.info(f"Created session in database: {session_id} for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to create session in database: {e}", exc_info=True)


async def save_message_to_db(
    session_id: str, role: str, content: str, message_index: int
):
    """
    Save message to session_messages table and update session last_active_at.

    Args:
        session_id: Session identifier
        role: Message role ('user', 'assistant', 'system', 'tool')
        content: Message content text
        message_index: Sequential message index within session

    Raises:
        Exception: If database operation fails (logged but not re-raised)
    """
    try:
        async with get_async_session() as db_session:
            message = SessionMessage(
                session_id=session_id,
                message_role=role,
                message_content=content,
                message_index=message_index,
            )
            db_session.add(message)

            # Also update last_active_at for session
            stmt = (
                update(UserSession)
                .where(UserSession.session_id == session_id)
                .values(last_active_at=func.now())
            )
            await db_session.execute(stmt)

            await db_session.commit()
            logger.debug(
                f"Saved message to database: session={session_id}, role={role}, index={message_index}"
            )
    except Exception as e:
        logger.error(f"Failed to save message to database: {e}", exc_info=True)


async def save_session_title(session_id: str, title: str) -> None:
    """
    Save session title to database.

    Args:
        session_id: Session identifier
        title: New title for the session

    Raises:
        Exception: If database operation fails
    """
    try:
        async with get_async_session() as db_session:
            from datetime import datetime

            stmt = (
                update(UserSession)
                .where(UserSession.session_id == session_id)
                .values(title=title, last_active_at=datetime.utcnow())
            )
            await db_session.execute(stmt)
            await db_session.commit()
            logger.info(f"Renamed session {session_id} to: {title}")
    except Exception as e:
        logger.error(f"Failed to save session title: {e}", exc_info=True)
        raise


async def get_session_from_db(session_id: str) -> UserSession:
    """
    Retrieve session from database by session ID.

    Args:
        session_id: Session identifier

    Returns:
        UserSession object

    Raises:
        Exception: If database operation fails
    """
    try:
        async with get_async_session() as db_session:
            from sqlalchemy import select

            stmt = select(UserSession).where(UserSession.session_id == session_id)
            result = await db_session.execute(stmt)
            session_obj = result.scalar_one_or_none()
            if not session_obj:
                raise ValueError(f"Session not found: {session_id}")
            return session_obj
    except Exception as e:
        logger.error(f"Failed to get session from database: {e}", exc_info=True)
        raise
