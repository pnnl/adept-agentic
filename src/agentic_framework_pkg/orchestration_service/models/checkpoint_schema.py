"""
LangGraph 1.0.5 Checkpoint Schema ORM Models

This module defines the SQLAlchemy ORM models for LangGraph 1.0.5 checkpoint persistence.
These models serve as the single source of truth for the checkpoint schema and are used
by the CheckpointSchemaMigrator for idempotent schema management.

Schema Version: LangGraph 1.0.5 / langgraph-checkpoint-postgres 3.0.2

Breaking Changes from LangGraph 0.0.8:
- Composite primary key (thread_id, checkpoint_ns, checkpoint_id) instead of single thread_id
- JSONB types instead of BYTEA for checkpoint and metadata columns
- Added checkpoint_ns, checkpoint_id, parent_checkpoint_id, type columns
- Removed created_at, updated_at columns (managed by LangGraph internally)

Migration Path:
- OLD (0.0.8): 3-5 columns, BYTEA types, single PK
- NEW (1.0.5): 7 columns, JSONB types, composite PK

References:
- LangGraph Docs: https://python.langchain.com/docs/langgraph/how-tos/persistence
- Checkpoint Postgres: https://github.com/langchain-ai/langgraph-checkpoint-postgres
"""

from sqlalchemy import Column, String, LargeBinary, Integer, PrimaryKeyConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Checkpoint(Base):
    """
    LangGraph 1.0.5 main checkpoint table.

    Stores agent state snapshots with composite key for hierarchical checkpointing.

    Columns:
        thread_id: Thread/conversation identifier
        checkpoint_ns: Checkpoint namespace (default: "" for main checkpoints)
        checkpoint_id: Unique checkpoint identifier (UUID or timestamp)
        parent_checkpoint_id: Parent checkpoint for branching/rollback
        type: Checkpoint type (standard, subgraph, etc.)
        checkpoint: JSONB serialized checkpoint data (LangGraph state)
        metadata: JSONB metadata (timestamp, version, etc.)

    Primary Key:
        Composite: (thread_id, checkpoint_ns, checkpoint_id)

    Indexes:
        - checkpoints_pkey: Primary key index
        - checkpoints_thread_id_idx: Query optimization for thread lookups

    Usage:
        This model is used by CheckpointSchemaMigrator for:
        - Schema validation (compare DB vs ORM)
        - Schema creation (fresh installs)
        - Schema migration (0.0.8 → 1.0.5 upgrades)
    """

    __tablename__ = "checkpoints"

    # Composite primary key columns
    thread_id = Column(String, nullable=False, comment="Thread/conversation ID")
    checkpoint_ns = Column(
        String,
        nullable=False,
        server_default="",
        comment="Checkpoint namespace (default: '' for main)",
    )
    checkpoint_id = Column(
        String, nullable=False, comment="Unique checkpoint ID (UUID/timestamp)"
    )

    # Relationship columns
    parent_checkpoint_id = Column(
        String,
        nullable=True,
        comment="Parent checkpoint for branching/rollback (optional)",
    )
    type = Column(
        String, nullable=True, comment="Checkpoint type (standard, subgraph, etc.)"
    )

    # Data columns (JSONB for efficient querying and storage)
    checkpoint = Column(
        JSONB, nullable=False, comment="Serialized checkpoint data (LangGraph state)"
    )
    # Note: 'metadata' is reserved by SQLAlchemy, use metadata_ with column name mapping
    metadata_ = Column(
        "metadata",  # Database column name
        JSONB,
        nullable=False,
        server_default="{}",
        comment="Checkpoint metadata (timestamp, version, etc.)",
    )

    # Composite primary key
    __table_args__ = (
        PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id"),
        Index("checkpoints_thread_id_idx", "thread_id"),
        {"comment": "LangGraph 1.0.5 checkpoints (managed by CheckpointSchemaMigrator)"},
    )


class CheckpointBlob(Base):
    """
    LangGraph 1.0.5 checkpoint blob storage.

    Stores large binary data referenced by checkpoints (e.g., serialized models,
    embeddings, large artifacts).

    Columns:
        thread_id: Thread/conversation identifier
        checkpoint_ns: Checkpoint namespace
        channel: Channel name (state variable name)
        version: Channel version (for concurrent updates)
        type: Blob type (model, embedding, artifact, etc.)
        blob: Binary blob data (BYTEA)

    Primary Key:
        Composite: (thread_id, checkpoint_ns, channel, version)

    Usage:
        Automatically managed by LangGraph's AsyncPostgresSaver.
        Stores large artifacts that don't fit efficiently in JSONB.
    """

    __tablename__ = "checkpoint_blobs"

    thread_id = Column(String, primary_key=True, nullable=False)
    checkpoint_ns = Column(String, primary_key=True, nullable=False, server_default="")
    channel = Column(String, primary_key=True, nullable=False)
    version = Column(String, primary_key=True, nullable=False)
    type = Column(String, nullable=False)
    blob = Column(LargeBinary, nullable=True)

    __table_args__ = (
        {"comment": "LangGraph 1.0.5 checkpoint blob storage for large artifacts"},
    )


class CheckpointMigration(Base):
    """
    LangGraph 1.0.5 checkpoint migration tracker.

    Tracks which LangGraph schema migrations have been applied.

    Columns:
        v: Migration version number (0-9 for LangGraph 1.0.5)

    Primary Key:
        v (migration version)

    Usage:
        Automatically managed by LangGraph's setup() method.
        Records migrations v0 through v9 for LangGraph 1.0.5.
    """

    __tablename__ = "checkpoint_migrations"

    v = Column(Integer, primary_key=True, nullable=False, comment="Migration version")

    __table_args__ = (
        {"comment": "LangGraph 1.0.5 migration tracker (managed by LangGraph)"},
    )


class CheckpointWrite(Base):
    """
    LangGraph 1.0.5 pending checkpoint writes.

    Stores pending writes for a checkpoint (transactional write buffer).

    Columns:
        thread_id: Thread/conversation identifier
        checkpoint_ns: Checkpoint namespace
        checkpoint_id: Checkpoint ID
        task_id: Task ID for the write operation
        idx: Write operation index (for ordering)
        channel: Channel name (state variable name)
        type: Write type (update, delete, etc.)
        blob: Binary write data

    Primary Key:
        Composite: (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)

    Usage:
        Automatically managed by LangGraph's AsyncPostgresSaver.
        Ensures atomic writes to checkpoint state.
    """

    __tablename__ = "checkpoint_writes"

    thread_id = Column(String, primary_key=True, nullable=False)
    checkpoint_ns = Column(String, primary_key=True, nullable=False, server_default="")
    checkpoint_id = Column(String, primary_key=True, nullable=False)
    task_id = Column(String, primary_key=True, nullable=False)
    idx = Column(Integer, primary_key=True, nullable=False)
    channel = Column(String, nullable=False)
    type = Column(String, nullable=False)
    blob = Column(LargeBinary, nullable=False)

    __table_args__ = (
        {"comment": "LangGraph 1.0.5 pending checkpoint writes (transactional buffer)"},
    )


# Schema version metadata
CHECKPOINT_SCHEMA_VERSION = "1.0.5"
CHECKPOINT_SCHEMA_PACKAGE = "langgraph-checkpoint-postgres>=3.0.2"

# Expected table list for validation
CHECKPOINT_TABLES = [
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_migrations",
    "checkpoint_writes",
]
