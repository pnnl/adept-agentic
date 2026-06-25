"""
Session persistence manager for CRUD operations on sessions and messages.

This module implements the persistence layer for the Session Management + Context
Window Management system. It provides database operations for:
- Session CRUD (create, read, update, archive, delete, restore, list)
- Message CRUD (save, retrieve, update)
- Tool output linking
- Cost tracking and token management

Architecture:
- Uses get_async_session() from checkpointing.py for database access
- Non-blocking error handling with try/except wrapping
- Feature flag controlled via SESSION_PERSISTENCE_ENABLED
- Message index synchronization for concurrent requests
"""

import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger_config import get_logger
from ..models.session_models import UserSession, SessionMessage, ToolOutput
from .checkpointing import get_async_session

logger = get_logger(__name__)


class SessionPersistenceError(Exception):
    """Base exception for session persistence operations."""
    pass


class SessionNotFoundError(SessionPersistenceError):
    """Raised when a session is not found in the database."""
    pass


class SessionAlreadyExistsError(SessionPersistenceError):
    """Raised when attempting to create a session that already exists."""
    pass


class MessageNotFoundError(SessionPersistenceError):
    """Raised when a message is not found in the database."""
    pass


class SessionPersistenceManager:
    """
    Manages session and message persistence operations.

    Provides CRUD operations for user_sessions, session_messages, and tool_outputs
    tables. All methods are async and use the shared database connection pool.

    Thread-Safety:
    - All methods use async context managers for proper session lifecycle
    - Message index synchronization via database-level UNIQUE constraint
    - No instance-level state (fully stateless)

    Error Handling:
    - All public methods log errors and raise SessionPersistenceError subclasses
    - Callers should wrap in try/except for non-blocking behavior
    """

    def __init__(self):
        """Initialize the session persistence manager."""
        logger.info("SessionPersistenceManager initialized")

    # =========================================================================
    # Session CRUD Operations
    # =========================================================================

    async def create_session(
        self,
        session_id: str,
        user_id: str,
        username: Optional[str] = None,
        session_type: str = "response",
        mcp_session_id: Optional[str] = None,
        multi_agent_session_id: Optional[str] = None,
        gateway_session_id: Optional[str] = None,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        retention_policy: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> UserSession:
        """
        Create a new session in the database.

        Args:
            session_id: Unique session identifier
            user_id: User who owns this session
            username: Optional username for display
            session_type: Type of session (response, multi_agent)
            mcp_session_id: Optional MCP session ID for tool execution
            multi_agent_session_id: Optional multi-agent coordination ID
            gateway_session_id: Optional gateway session ID for A2A
            title: Optional user-defined session title
            tags: Optional list of searchable tags
            retention_policy: Optional retention policy (default: indefinite)
            metadata: Optional JSONB metadata

        Returns:
            UserSession: Created session object

        Raises:
            SessionAlreadyExistsError: If session_id already exists
            SessionPersistenceError: For other database errors
        """
        try:
            async with get_async_session() as db_session:
                # Check for duplicate session_id
                existing = await db_session.execute(
                    select(UserSession).where(UserSession.session_id == session_id)
                )
                if existing.scalar_one_or_none() is not None:
                    raise SessionAlreadyExistsError(
                        f"Session with ID '{session_id}' already exists"
                    )

                # Create new session
                new_session = UserSession(
                    session_id=session_id,
                    user_id=user_id,
                    username=username,
                    session_type=session_type,
                    status="active",
                    mcp_session_id=mcp_session_id,
                    multi_agent_session_id=multi_agent_session_id,
                    gateway_session_id=gateway_session_id,
                    title=title,
                    tags=tags or [],
                    retention_policy=retention_policy or "indefinite",
                    session_metadata=metadata or {},
                    created_at=datetime.utcnow(),
                    last_active_at=datetime.utcnow()
                )

                db_session.add(new_session)
                await db_session.commit()
                await db_session.refresh(new_session)

                logger.info(
                    f"Created session: {session_id} (user={user_id}, type={session_type})"
                )

                return new_session

        except SessionAlreadyExistsError:
            raise
        except IntegrityError as e:
            logger.error(f"Integrity error creating session {session_id}: {e}")
            raise SessionPersistenceError(
                f"Database integrity error creating session: {e}"
            )
        except Exception as e:
            logger.error(f"Failed to create session {session_id}: {e}", exc_info=True)
            raise SessionPersistenceError(f"Failed to create session: {e}")

    async def get_session(self, session_id: str) -> UserSession:
        """
        Retrieve a session by ID.

        Args:
            session_id: Session identifier

        Returns:
            UserSession: Session object

        Raises:
            SessionNotFoundError: If session does not exist
            SessionPersistenceError: For other database errors
        """
        try:
            async with get_async_session() as db_session:
                result = await db_session.execute(
                    select(UserSession).where(UserSession.session_id == session_id)
                )
                session = result.scalar_one_or_none()

                if session is None:
                    raise SessionNotFoundError(f"Session '{session_id}' not found")

                return session

        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to retrieve session {session_id}: {e}", exc_info=True)
            raise SessionPersistenceError(f"Failed to retrieve session: {e}")

    async def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        retention_policy: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None
    ) -> UserSession:
        """
        Update session metadata.

        Args:
            session_id: Session identifier
            title: Optional new title
            tags: Optional new tags list
            retention_policy: Optional new retention policy
            metadata: Optional metadata to merge
            status: Optional new status (active, archived, etc.)

        Returns:
            UserSession: Updated session object

        Raises:
            SessionNotFoundError: If session does not exist
            SessionPersistenceError: For other database errors
        """
        try:
            async with get_async_session() as db_session:
                # Fetch existing session
                result = await db_session.execute(
                    select(UserSession).where(UserSession.session_id == session_id)
                )
                session = result.scalar_one_or_none()

                if session is None:
                    raise SessionNotFoundError(f"Session '{session_id}' not found")

                # Update fields if provided
                if title is not None:
                    session.title = title
                if tags is not None:
                    session.tags = tags
                if retention_policy is not None:
                    session.retention_policy = retention_policy
                if metadata is not None:
                    # Merge metadata
                    current_metadata = session.session_metadata or {}
                    current_metadata.update(metadata)
                    session.session_metadata = current_metadata
                if status is not None:
                    session.status = status

                # Always update last_active_at
                session.last_active_at = datetime.utcnow()

                await db_session.commit()
                await db_session.refresh(session)

                logger.info(f"Updated session: {session_id}")

                return session

        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to update session {session_id}: {e}", exc_info=True)
            raise SessionPersistenceError(f"Failed to update session: {e}")

    async def update_session_cost(
        self,
        session_id: str,
        tokens: int,
        cost: float
    ) -> UserSession:
        """
        Update session token count and estimated cost.

        Args:
            session_id: Session identifier
            tokens: Number of tokens to add
            cost: Cost in USD to add

        Returns:
            UserSession: Updated session object

        Raises:
            SessionNotFoundError: If session does not exist
            SessionPersistenceError: For other database errors
        """
        try:
            async with get_async_session() as db_session:
                # Fetch existing session
                result = await db_session.execute(
                    select(UserSession).where(UserSession.session_id == session_id)
                )
                session = result.scalar_one_or_none()

                if session is None:
                    raise SessionNotFoundError(f"Session '{session_id}' not found")

                # Update cost tracking
                session.total_tokens = (session.total_tokens or 0) + tokens
                session.estimated_cost_usd = float(session.estimated_cost_usd or 0) + cost
                session.last_active_at = datetime.utcnow()

                await db_session.commit()
                await db_session.refresh(session)

                logger.debug(
                    f"Updated session cost: {session_id} "
                    f"(+{tokens} tokens, +${cost:.4f})"
                )

                return session

        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(
                f"Failed to update session cost {session_id}: {e}",
                exc_info=True
            )
            raise SessionPersistenceError(f"Failed to update session cost: {e}")

    async def archive_session(self, session_id: str) -> UserSession:
        """
        Archive a session (mark as archived).

        Args:
            session_id: Session identifier

        Returns:
            UserSession: Archived session object

        Raises:
            SessionNotFoundError: If session does not exist
            SessionPersistenceError: For other database errors
        """
        try:
            async with get_async_session() as db_session:
                result = await db_session.execute(
                    select(UserSession).where(UserSession.session_id == session_id)
                )
                session = result.scalar_one_or_none()

                if session is None:
                    raise SessionNotFoundError(f"Session '{session_id}' not found")

                session.status = "archived"
                session.archived_at = datetime.utcnow()

                await db_session.commit()
                await db_session.refresh(session)

                logger.info(f"Archived session: {session_id}")

                return session

        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to archive session {session_id}: {e}", exc_info=True)
            raise SessionPersistenceError(f"Failed to archive session: {e}")

    async def delete_session(
        self,
        session_id: str,
        permanent: bool = False
    ) -> UserSession:
        """
        Delete a session (soft delete with grace period or hard delete).

        Args:
            session_id: Session identifier
            permanent: If True, hard delete immediately. If False, soft delete
                      with grace period (status=pending_deletion)

        Returns:
            UserSession: Deleted session object (if soft delete)

        Raises:
            SessionNotFoundError: If session does not exist
            SessionPersistenceError: For other database errors
        """
        try:
            async with get_async_session() as db_session:
                result = await db_session.execute(
                    select(UserSession).where(UserSession.session_id == session_id)
                )
                session = result.scalar_one_or_none()

                if session is None:
                    raise SessionNotFoundError(f"Session '{session_id}' not found")

                if permanent:
                    # Hard delete (cascades to messages and sets tool_outputs.message_id=NULL)
                    await db_session.delete(session)
                    await db_session.commit()
                    logger.info(f"Permanently deleted session: {session_id}")
                    return session
                else:
                    # Soft delete (mark as pending_deletion)
                    session.status = "pending_deletion"
                    session.deleted_at = datetime.utcnow()
                    await db_session.commit()
                    await db_session.refresh(session)
                    logger.info(f"Soft deleted session: {session_id} (grace period active)")
                    return session

        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}", exc_info=True)
            raise SessionPersistenceError(f"Failed to delete session: {e}")

    async def restore_session(self, session_id: str) -> UserSession:
        """
        Restore a session from archived or pending_deletion status.

        Args:
            session_id: Session identifier

        Returns:
            UserSession: Restored session object

        Raises:
            SessionNotFoundError: If session does not exist
            SessionPersistenceError: For other database errors
        """
        try:
            async with get_async_session() as db_session:
                result = await db_session.execute(
                    select(UserSession).where(
                        and_(
                            UserSession.session_id == session_id,
                            UserSession.status.in_(["archived", "pending_deletion"])
                        )
                    )
                )
                session = result.scalar_one_or_none()

                if session is None:
                    raise SessionNotFoundError(
                        f"Session '{session_id}' not found or cannot be restored"
                    )

                session.status = "active"
                session.archived_at = None
                session.deleted_at = None
                session.last_active_at = datetime.utcnow()

                await db_session.commit()
                await db_session.refresh(session)

                logger.info(f"Restored session: {session_id}")

                return session

        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to restore session {session_id}: {e}", exc_info=True)
            raise SessionPersistenceError(f"Failed to restore session: {e}")

    async def list_sessions(
        self,
        user_id: str,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[UserSession], int]:
        """
        List sessions with pagination and filtering.

        Args:
            user_id: User ID to filter by
            status: Optional status filter (active, archived, etc.)
            tags: Optional tags to filter by (ANY match)
            limit: Maximum number of results (default: 50)
            offset: Number of results to skip (default: 0)

        Returns:
            Tuple[List[UserSession], int]: List of sessions and total count

        Raises:
            SessionPersistenceError: For database errors
        """
        try:
            async with get_async_session() as db_session:
                # Build base query
                query = select(UserSession).where(UserSession.user_id == user_id)

                # Apply filters
                if status is not None:
                    query = query.where(UserSession.status == status)

                if tags is not None and len(tags) > 0:
                    # ANY match on tags (PostgreSQL array overlap)
                    query = query.where(UserSession.tags.overlap(tags))

                # Get total count before pagination
                count_query = select(func.count()).select_from(query.subquery())
                count_result = await db_session.execute(count_query)
                total_count = count_result.scalar() or 0

                # Apply pagination and ordering
                query = (
                    query
                    .order_by(UserSession.last_active_at.desc())
                    .limit(limit)
                    .offset(offset)
                )

                # Execute query
                result = await db_session.execute(query)
                sessions = result.scalars().all()

                logger.debug(
                    f"Listed sessions: user={user_id}, status={status}, "
                    f"count={len(sessions)}/{total_count}"
                )

                return list(sessions), total_count

        except Exception as e:
            logger.error(f"Failed to list sessions for user {user_id}: {e}", exc_info=True)
            raise SessionPersistenceError(f"Failed to list sessions: {e}")

    async def session_exists(self, session_id: str) -> bool:
        """
        Check if a session exists.

        Args:
            session_id: Session identifier

        Returns:
            bool: True if session exists, False otherwise

        Raises:
            SessionPersistenceError: For database errors
        """
        try:
            async with get_async_session() as db_session:
                result = await db_session.execute(
                    select(func.count()).where(UserSession.session_id == session_id)
                )
                count = result.scalar() or 0
                return count > 0

        except Exception as e:
            logger.error(
                f"Failed to check session existence {session_id}: {e}",
                exc_info=True
            )
            raise SessionPersistenceError(f"Failed to check session existence: {e}")

    async def get_session_token_count(self, session_id: str) -> int:
        """
        Get total token count for a session.

        Args:
            session_id: Session identifier

        Returns:
            int: Total tokens used in session

        Raises:
            SessionNotFoundError: If session does not exist
            SessionPersistenceError: For other database errors
        """
        try:
            session = await self.get_session(session_id)
            return session.total_tokens or 0

        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(
                f"Failed to get token count for session {session_id}: {e}",
                exc_info=True
            )
            raise SessionPersistenceError(f"Failed to get token count: {e}")

    # =========================================================================
    # Message CRUD Operations
    # =========================================================================

    async def save_message(
        self,
        session_id: str,
        message_role: str,
        message_content: str,
        message_index: int,
        message_metadata: Optional[Dict[str, Any]] = None,
        tool_call_ids: Optional[List[str]] = None,
        context_layer: str = "historical",
        classification_tier: Optional[str] = None,
        importance_score: Optional[float] = None,
        fidelity_level: Optional[str] = None
    ) -> SessionMessage:
        """
        Save a message to the session_messages table.

        Args:
            session_id: Session identifier
            message_role: Role of message sender (user, assistant, system, tool)
            message_content: Message content text
            message_index: Sequential message index in session
            message_metadata: Optional JSONB metadata
            tool_call_ids: Optional list of tool call IDs
            context_layer: Context layer (active, historical)
            classification_tier: Optional classification (retain, summarize, delete)
            importance_score: Optional importance score (0.0-1.0)
            fidelity_level: Optional fidelity level (high, medium, low)

        Returns:
            SessionMessage: Created message object

        Raises:
            SessionNotFoundError: If session does not exist
            IntegrityError: If message_index already exists for session
            SessionPersistenceError: For other database errors
        """
        try:
            async with get_async_session() as db_session:
                # Verify session exists
                session_exists_query = await db_session.execute(
                    select(func.count()).where(UserSession.session_id == session_id)
                )
                if session_exists_query.scalar() == 0:
                    raise SessionNotFoundError(f"Session '{session_id}' not found")

                # Create new message
                new_message = SessionMessage(
                    session_id=session_id,
                    message_role=message_role,
                    message_content=message_content,
                    message_index=message_index,
                    message_metadata=message_metadata or {},
                    tool_call_ids=tool_call_ids or [],
                    has_tool_outputs=bool(tool_call_ids and len(tool_call_ids) > 0),
                    context_layer=context_layer,
                    classification_tier=classification_tier,
                    importance_score=importance_score,
                    fidelity_level=fidelity_level,
                    created_at=datetime.utcnow()
                )

                db_session.add(new_message)
                await db_session.commit()
                await db_session.refresh(new_message)

                logger.debug(
                    f"Saved message: session={session_id}, index={message_index}, "
                    f"role={message_role}"
                )

                return new_message

        except SessionNotFoundError:
            raise
        except IntegrityError as e:
            # UNIQUE constraint violation on (session_id, message_index)
            logger.error(
                f"Message index {message_index} already exists for session {session_id}"
            )
            raise SessionPersistenceError(
                f"Message index {message_index} already exists for session"
            )
        except Exception as e:
            logger.error(
                f"Failed to save message for session {session_id}: {e}",
                exc_info=True
            )
            raise SessionPersistenceError(f"Failed to save message: {e}")

    async def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
        context_layer: Optional[str] = None
    ) -> List[SessionMessage]:
        """
        Retrieve messages for a session with pagination.

        Args:
            session_id: Session identifier
            limit: Optional maximum number of messages to return
            offset: Number of messages to skip (default: 0)
            context_layer: Optional filter by context layer (active, historical)

        Returns:
            List[SessionMessage]: List of messages ordered by message_index

        Raises:
            SessionPersistenceError: For database errors
        """
        try:
            async with get_async_session() as db_session:
                # Build query
                query = select(SessionMessage).where(
                    SessionMessage.session_id == session_id
                )

                # Filter by context layer if specified
                if context_layer is not None:
                    query = query.where(SessionMessage.context_layer == context_layer)

                # Order by message_index
                query = query.order_by(SessionMessage.message_index)

                # Apply pagination
                if limit is not None:
                    query = query.limit(limit)
                query = query.offset(offset)

                # Execute query
                result = await db_session.execute(query)
                messages = result.scalars().all()

                logger.debug(
                    f"Retrieved {len(messages)} messages for session {session_id}"
                )

                return list(messages)

        except Exception as e:
            logger.error(
                f"Failed to retrieve messages for session {session_id}: {e}",
                exc_info=True
            )
            raise SessionPersistenceError(f"Failed to retrieve messages: {e}")

    async def update_message(
        self,
        message_id: UUID,
        context_layer: Optional[str] = None,
        classification_tier: Optional[str] = None,
        importance_score: Optional[float] = None,
        fidelity_level: Optional[str] = None
    ) -> SessionMessage:
        """
        Update message context classification metadata.

        Args:
            message_id: Message UUID
            context_layer: Optional new context layer
            classification_tier: Optional new classification tier
            importance_score: Optional new importance score
            fidelity_level: Optional new fidelity level

        Returns:
            SessionMessage: Updated message object

        Raises:
            MessageNotFoundError: If message does not exist
            SessionPersistenceError: For other database errors
        """
        try:
            async with get_async_session() as db_session:
                # Fetch message
                result = await db_session.execute(
                    select(SessionMessage).where(SessionMessage.id == message_id)
                )
                message = result.scalar_one_or_none()

                if message is None:
                    raise MessageNotFoundError(f"Message '{message_id}' not found")

                # Update fields if provided
                if context_layer is not None:
                    message.context_layer = context_layer
                if classification_tier is not None:
                    message.classification_tier = classification_tier
                if importance_score is not None:
                    message.importance_score = importance_score
                if fidelity_level is not None:
                    message.fidelity_level = fidelity_level

                await db_session.commit()
                await db_session.refresh(message)

                logger.debug(f"Updated message: {message_id}")

                return message

        except MessageNotFoundError:
            raise
        except Exception as e:
            logger.error(
                f"Failed to update message {message_id}: {e}",
                exc_info=True
            )
            raise SessionPersistenceError(f"Failed to update message: {e}")

    # =========================================================================
    # Tool Output Operations
    # =========================================================================

    async def link_tool_output(
        self,
        tool_output_id: UUID,
        message_id: UUID
    ) -> ToolOutput:
        """
        Link a tool output to a message.

        Args:
            tool_output_id: Tool output UUID
            message_id: Message UUID to link to

        Returns:
            ToolOutput: Updated tool output object

        Raises:
            SessionPersistenceError: For database errors
        """
        try:
            async with get_async_session() as db_session:
                # Fetch tool output
                result = await db_session.execute(
                    select(ToolOutput).where(ToolOutput.id == tool_output_id)
                )
                tool_output = result.scalar_one_or_none()

                if tool_output is None:
                    raise SessionPersistenceError(
                        f"Tool output '{tool_output_id}' not found"
                    )

                # Update message_id link
                tool_output.message_id = message_id
                tool_output.retention_status = "active"

                await db_session.commit()
                await db_session.refresh(tool_output)

                logger.debug(
                    f"Linked tool output {tool_output_id} to message {message_id}"
                )

                return tool_output

        except Exception as e:
            logger.error(
                f"Failed to link tool output {tool_output_id} to message {message_id}: {e}",
                exc_info=True
            )
            raise SessionPersistenceError(f"Failed to link tool output: {e}")

    async def get_tool_outputs_for_message(
        self,
        message_id: UUID
    ) -> List[ToolOutput]:
        """
        Get all tool outputs linked to a message.

        Args:
            message_id: Message UUID

        Returns:
            List[ToolOutput]: List of tool outputs linked to message

        Raises:
            SessionPersistenceError: For database errors
        """
        try:
            async with get_async_session() as db_session:
                result = await db_session.execute(
                    select(ToolOutput)
                    .where(ToolOutput.message_id == message_id)
                    .order_by(ToolOutput.output_sequence)
                )
                tool_outputs = result.scalars().all()

                logger.debug(
                    f"Retrieved {len(tool_outputs)} tool outputs for message {message_id}"
                )

                return list(tool_outputs)

        except Exception as e:
            logger.error(
                f"Failed to retrieve tool outputs for message {message_id}: {e}",
                exc_info=True
            )
            raise SessionPersistenceError(f"Failed to retrieve tool outputs: {e}")
