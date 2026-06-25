"""
Session persistence layer for the orchestration service.

This package provides database session management utilities for session
persistence, cleanup scheduling, state management operations, and checkpoint
schema migration management.
"""

from ..models.base import Base
from ..legacy_persistence import AsyncSessionLocal, init_db
from ..legacy_models import Assistant, Run, RunStep
from .checkpointing import get_async_session, get_async_engine, dispose_engine
from .session_persistence import (
    SessionPersistenceManager,
    SessionPersistenceError,
    SessionNotFoundError,
    SessionAlreadyExistsError,
    MessageNotFoundError,
)
from .schema_migrator import (
    CheckpointSchemaMigrator,
    SchemaState,
    MigrationStrategy,
    SchemaDetectionResult,
    MigrationResult,
)

__all__ = [
    "Base",
    "AsyncSessionLocal",
    "init_db",
    "Assistant",
    "Run",
    "RunStep",
    "get_async_session",
    "get_async_engine",
    "dispose_engine",
    "SessionPersistenceManager",
    "SessionPersistenceError",
    "SessionNotFoundError",
    "SessionAlreadyExistsError",
    "MessageNotFoundError",
    "CheckpointSchemaMigrator",
    "SchemaState",
    "MigrationStrategy",
    "SchemaDetectionResult",
    "MigrationResult",
]
