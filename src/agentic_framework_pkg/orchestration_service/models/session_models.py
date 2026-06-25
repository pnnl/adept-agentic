"""
SQLAlchemy ORM models for integrated Session Management and Context Window Management.

This module implements the dual-layer retention architecture:
- Historical Retention Layer: user_sessions, session_messages, tool_outputs
- Active Context Layer: context_archives

Database schema matches the SESSION_CONTEXT_INTEGRATION_PROPOSAL.md specification.
"""

from datetime import datetime
from typing import Optional, List
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    TIMESTAMP,
    ARRAY,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
    PrimaryKeyConstraint,
    Index,
    Computed,
    text,
    desc,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC, TSVECTOR
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base


class UserSession(Base):
    """
    User session metadata for Historical Retention Layer.

    Stores session-level information including multi-tier identifiers,
    cost tracking, user-facing features (title, tags), and retention policy.

    Database Requirements:
        - PostgreSQL extension: pg_trgm (for fuzzy text search indexes)
          Automatically enabled via migration: CREATE EXTENSION IF NOT EXISTS pg_trgm
    """

    __tablename__ = "user_sessions"

    # Primary key
    session_id = Column(String, primary_key=True, index=True)

    # Multi-tier session identifiers (from existing session_manager.py)
    mcp_session_id = Column(String, nullable=True, index=True)
    multi_agent_session_id = Column(String, nullable=True, index=True)
    gateway_session_id = Column(String, nullable=True, index=True)

    # User identification
    user_id = Column(String, nullable=False, index=True)
    username = Column(String, nullable=True)

    # Session metadata
    session_type = Column(
        String, nullable=False, default="response", index=True
    )  # response, multi_agent (assistant DEPRECATED - see Q1 architectural clarifications)
    status = Column(
        String, nullable=False, default="active", index=True
    )  # active, archived, pending_deletion, deleted

    # Timestamps
    created_at = Column(TIMESTAMP, nullable=False, default=func.now(), index=True)
    last_active_at = Column(TIMESTAMP, nullable=False, default=func.now(), index=True)
    archived_at = Column(TIMESTAMP, nullable=True)
    deleted_at = Column(TIMESTAMP, nullable=True)

    # Cost tracking
    total_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(NUMERIC(10, 6), default=0.0)

    # User-facing features
    title = Column(String, nullable=True)
    tags = Column(ARRAY(String), nullable=True)
    session_metadata = Column(JSONB, nullable=False, default=lambda: {})

    # Retention policy
    retention_policy = Column(
        String, nullable=False, default="indefinite"
    )  # "indefinite", "30d", "90d", "1m", "-1", etc.

    # Relationships
    messages = relationship(
        "SessionMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived', 'pending_deletion', 'deleted')",
            name="chk_user_sessions_status",
        ),
        # Phase 1 indexes (existing)
        Index("idx_user_sessions_user_status_created", "user_id", "status", "created_at"),
        Index("idx_user_sessions_last_active", "last_active_at"),
        Index("idx_user_sessions_multi_tier", "mcp_session_id", "multi_agent_session_id"),
        # Phase 2 indexes (enhanced navigation UI)
        Index("idx_user_sessions_tags", "tags", postgresql_using="gin"),
        Index(
            "idx_user_sessions_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "idx_user_sessions_metadata_summary",
            text("(session_metadata->>'summary_5w')"),
            postgresql_using="gin",
            postgresql_ops={"(session_metadata->>'summary_5w')": "gin_trgm_ops"},
        ),
        Index(
            "idx_user_sessions_cost",
            desc("estimated_cost_usd").nullslast(),
        ),
        Index(
            "idx_user_sessions_tokens",
            desc("total_tokens").nullslast(),
        ),
    )

    def __init__(self, **kwargs):
        """Initialize UserSession with Python-level defaults."""
        # Set Python-level defaults if not provided
        kwargs.setdefault('session_type', 'response')
        kwargs.setdefault('status', 'active')
        kwargs.setdefault('retention_policy', 'indefinite')
        kwargs.setdefault('total_tokens', 0)
        kwargs.setdefault('estimated_cost_usd', 0.0)
        kwargs.setdefault('session_metadata', {})
        super().__init__(**kwargs)

    def __repr__(self):
        return (
            f"<UserSession(session_id={self.session_id}, user_id={self.user_id}, "
            f"status={self.status}, created_at={self.created_at})>"
        )


class SessionMessage(Base):
    """
    Full conversation history for Historical Retention Layer.

    Stores all messages with context classification metadata from Active Context Layer.
    Supports FK linking to tool_outputs to prevent orphaned data.

    **IMPORTANT**: This table is RANGE-partitioned by `created_at` in PostgreSQL.

    Partitioning Strategy:
    - Monthly partitions (session_messages_YYYY_MM)
    - Managed via SQL migrations in persistence/migrations/
    - Fresh deployments MUST run consolidated_initial_schema.sql

    Database Requirements:
    - PostgreSQL 12+ (for generated columns and partitioning)
    - Partitions must be created before inserts

    ORM Limitations:
    - create_all() creates regular table, not partitioned
    - Production deployments MUST use Alembic/SQL migrations
    """

    __tablename__ = "session_messages"

    # Primary key (composite for partitioned table)
    id = Column(UUID(as_uuid=True), default=uuid4, index=True)
    created_at = Column(TIMESTAMP, nullable=False, default=func.now(), index=True)

    # Foreign key to session
    session_id = Column(
        String,
        ForeignKey("user_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Message identification
    message_index = Column(Integer, nullable=False)
    message_role = Column(String, nullable=False, index=True)  # user, assistant, system, tool

    # Message content
    message_content = Column(Text, nullable=True)
    message_metadata = Column(JSONB, nullable=False, default=lambda: {})

    # Full-text search generated column
    content_tsvector = Column(
        TSVECTOR,
        Computed("to_tsvector('english', COALESCE(message_content, ''))", persisted=True),
        nullable=True,
    )

    # Context classification (from Active Context Layer)
    context_layer = Column(
        String, nullable=False, default="historical", index=True
    )  # active, historical
    classification_tier = Column(String, nullable=True)  # retain, summarize, delete
    importance_score = Column(Float, nullable=True)
    fidelity_level = Column(String, nullable=True)  # high, medium, low

    # Tool call linkage (for preventing orphaned tool_outputs)
    tool_call_ids = Column(ARRAY(String), nullable=True)
    has_tool_outputs = Column(Boolean, nullable=False, default=False)

    # Relationships
    session = relationship("UserSession", back_populates="messages")
    tool_outputs = relationship(
        "ToolOutput",
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    # Constraints and indexes
    __table_args__ = (
        # Primary key includes partition key (required for partitioned tables)
        PrimaryKeyConstraint("id", "created_at"),
        # Unique constraint for message ordering (includes partition key)
        UniqueConstraint(
            "session_id", "message_index", "created_at", name="uq_session_message_idx"
        ),
        # Standard B-tree indexes
        Index("idx_session_messages_session", "session_id", "message_index"),
        Index("idx_session_messages_created", "created_at"),
        Index("idx_session_messages_context_layer", "context_layer"),
        # GIN indexes for full-text search and array operations
        Index(
            "idx_session_messages_content_fts",
            "content_tsvector",
            postgresql_using="gin",
        ),
        Index(
            "idx_session_messages_tool_calls", "tool_call_ids", postgresql_using="gin"
        ),
    )

    def __init__(self, **kwargs):
        """Initialize SessionMessage with Python-level defaults."""
        # Set Python-level defaults if not provided
        kwargs.setdefault('message_metadata', {})
        kwargs.setdefault('context_layer', 'historical')
        kwargs.setdefault('has_tool_outputs', False)
        super().__init__(**kwargs)

    def __repr__(self):
        return (
            f"<SessionMessage(id={self.id}, session_id={self.session_id}, "
            f"message_index={self.message_index}, role={self.message_role})>"
        )


class ToolOutput(Base):
    """
    Large tool outputs stored separately to prevent token explosion.

    MODIFICATION of existing tool_outputs table to add FK link to session_messages.
    Prevents orphaned outputs when messages are deleted.
    """

    __tablename__ = "tool_outputs"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    # Existing columns (from persistence_v2.py)
    thread_id = Column(String, nullable=False, index=True)
    checkpoint_id = Column(String, nullable=False, index=True)
    tool_call_id = Column(String, nullable=False, index=True)
    output_sequence = Column(Integer, nullable=False)
    tool_name = Column(String, nullable=True)
    full_output = Column(JSONB, nullable=False)
    output_size = Column(Integer, nullable=False)
    session_id = Column(String, nullable=True, index=True)
    mcp_session_id = Column(String, nullable=True, index=True)
    created_at = Column(TIMESTAMP, nullable=False, default=func.now())

    # NEW columns for session integration
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("session_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    retention_status = Column(
        String, nullable=False, default="active", index=True
    )  # active, orphaned, pending_deletion, deleted

    # Relationships
    message = relationship("SessionMessage", back_populates="tool_outputs")

    # Constraints
    __table_args__ = (
        UniqueConstraint(
            "thread_id", "checkpoint_id", "output_sequence",
            name="uq_tool_outputs_thread_checkpoint_seq"  # Match migration 004
        ),
        Index("idx_tool_outputs_thread", "thread_id", "checkpoint_id"),
        Index("idx_tool_outputs_message", "message_id"),
        Index("idx_tool_outputs_retention", "retention_status"),
    )

    def __init__(self, **kwargs):
        """Initialize ToolOutput with Python-level defaults."""
        # Set Python-level defaults if not provided
        kwargs.setdefault('retention_status', 'active')
        super().__init__(**kwargs)

    def __repr__(self):
        return (
            f"<ToolOutput(id={self.id}, thread_id={self.thread_id}, "
            f"tool_name={self.tool_name}, output_size={self.output_size}, "
            f"retention_status={self.retention_status})>"
        )


class ContextArchive(Base):
    """
    LLM-generated summaries of archived message blocks for Active Context Layer.

    Stores compressed representations of conversation history to keep LLM context
    under token limits while preserving key information.
    """

    __tablename__ = "context_archives"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)

    # Session identifiers
    session_id = Column(String, nullable=False, index=True)
    thread_id = Column(String, nullable=False, index=True)
    mcp_session_id = Column(String, nullable=True)
    multi_agent_session_id = Column(String, nullable=True)

    # Archive metadata
    archive_sequence = Column(Integer, nullable=False)  # Sequential number for this session's archives
    message_range_start = Column(Integer, nullable=False)  # First message index in this archive
    message_range_end = Column(Integer, nullable=False)  # Last message index in this archive

    # Summarized content
    summary_content = Column(Text, nullable=False)  # LLM-generated summary
    original_token_count = Column(Integer, nullable=False)
    summary_token_count = Column(Integer, nullable=False)
    compression_ratio = Column(Float, nullable=True)  # summary_tokens / original_tokens

    # Classification metadata
    classification_tier = Column(
        String, nullable=False, default="summarize"
    )  # DELETE, SUMMARIZE, RETAIN
    average_importance_score = Column(Float, nullable=True)

    # Summarization metadata
    summarization_model = Column(String, nullable=True)  # Model used for summarization
    summarization_strategy = Column(String, nullable=True)  # Strategy name from factory
    summarized_at = Column(TIMESTAMP, nullable=False, default=func.now(), index=True)

    # User context
    user_id = Column(String, nullable=True)

    # Constraints
    __table_args__ = (
        UniqueConstraint("session_id", "archive_sequence", name="uq_context_archives_seq"),
        Index("idx_context_archives_session", "session_id", "archive_sequence"),
        Index("idx_context_archives_thread", "thread_id"),
        Index("idx_context_archives_summarized", "summarized_at"),
    )

    def __init__(self, **kwargs):
        """Initialize ContextArchive with Python-level defaults."""
        # Set Python-level defaults if not provided
        kwargs.setdefault('classification_tier', 'summarize')
        super().__init__(**kwargs)

    def __repr__(self):
        return (
            f"<ContextArchive(id={self.id}, session_id={self.session_id}, "
            f"archive_sequence={self.archive_sequence}, "
            f"message_range={self.message_range_start}-{self.message_range_end}, "
            f"compression_ratio={self.compression_ratio})>"
        )
