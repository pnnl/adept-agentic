"""
Database session management for session persistence layer.

This module provides database session utilities for the session management
and cleanup scheduler components.
"""

import asyncio
import os
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ...logger_config import get_logger

logger = get_logger(__name__)

# Database URL configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://admin:password@postgres:5432/agentic_orchestrator",
)

# Module-level engine for session persistence operations
# This is separate from the LangGraph checkpointer pool to avoid conflicts
# IMPORTANT: Engine is initialized lazily with event loop detection to avoid affinity issues
_session_persistence_engine: Optional[AsyncEngine] = None
_engine_event_loop_id: Optional[int] = None
_engine_lock = threading.Lock()


def _get_or_create_engine() -> AsyncEngine:
    """
    Get or create the async engine lazily (in the caller's event loop context).

    This ensures the engine is created within the correct event loop, avoiding
    "Task got Future attached to a different loop" errors.

    Detects event loop changes and recreates the engine when switching loops
    (important for pytest where different tests may use different event loops).

    Uses threading.Lock() for thread safety without event loop affinity.
    Double-check locking pattern ensures only one engine is created per loop.

    Returns:
        AsyncEngine: SQLAlchemy async engine
    """
    global _session_persistence_engine, _engine_event_loop_id

    # Get current event loop ID (None if no loop running)
    try:
        current_loop = asyncio.get_running_loop()
        current_loop_id = id(current_loop)
    except RuntimeError:
        current_loop_id = None

    # If engine exists but we're in a different event loop, dispose it
    if _session_persistence_engine is not None and _engine_event_loop_id != current_loop_id:
        with _engine_lock:
            if _session_persistence_engine is not None and _engine_event_loop_id != current_loop_id:
                logger.debug(
                    f"Event loop changed (old={_engine_event_loop_id}, new={current_loop_id}), "
                    "marking engine for disposal"
                )
                # Mark for disposal (can't await dispose() in sync function)
                _session_persistence_engine = None
                _engine_event_loop_id = None

    if _session_persistence_engine is None:
        with _engine_lock:
            # Double-check after acquiring lock
            if _session_persistence_engine is None:
                logger.debug(f"Initializing session persistence engine in event loop {current_loop_id}")
                _session_persistence_engine = create_async_engine(
                    DATABASE_URL,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=10,
                    echo=False
                )
                _engine_event_loop_id = current_loop_id

    return _session_persistence_engine


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    """
    Async context manager that provides a database session.

    This function creates an AsyncSession for database operations and ensures
    proper lifecycle management (commit on success, rollback on error, always close).

    The engine is lazily initialized on first use to ensure it's created in the
    correct event loop context, avoiding "Task got Future attached to a different loop"
    errors.

    Usage:
        async with get_async_session() as session:
            result = await session.execute(select(UserSession))
            sessions = result.scalars().all()

    Yields:
        AsyncSession: SQLAlchemy async session for database operations

    Example:
        >>> async with get_async_session() as session:
        ...     user_session = UserSession(session_id="test", user_id="user-123")
        ...     session.add(user_session)
        ...     await session.commit()
    """
    # Lazy engine initialization
    engine = _get_or_create_engine()
    session_maker = sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession
    )
    session = session_maker()

    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Database session error: {e}", exc_info=True)
        raise
    finally:
        await session.close()


async def get_async_engine():
    """
    Get the async engine for session persistence operations.

    Returns:
        AsyncEngine: SQLAlchemy async engine (lazily initialized)
    """
    return _get_or_create_engine()


async def dispose_engine():
    """
    Dispose of the session persistence engine.

    Call this during service shutdown to properly close all connections.
    Resets the engine to None so it can be recreated if needed.
    """
    global _session_persistence_engine

    if _session_persistence_engine is not None:
        logger.info("Disposing session persistence engine")
        await _session_persistence_engine.dispose()
        _session_persistence_engine = None
