"""
This module provides the persistence layer for the Orchestration Service.

It handles all interactions with the PostgreSQL database, providing a durable
and consistent state management solution for the agentic framework.

Architectural Role:
-   **State Persistence:** This is the core of the state management for the
    entire framework.
-   **LangGraph Checkpointer:** The `AsyncPostgresSaver` class implements the
    `BaseCheckpointSaver` interface from LangGraph. It is responsible for
    atomically saving and loading the state of the `ScientificWorkflowAgent`'s
    graph to the `checkpoints` table in PostgreSQL. This ensures that
    conversations are durable and can be resumed.
-   **Multi-Agent Session Storage:** The `init_db` function also creates the
    `multi_agent_sessions` table, which is used by the `multi_agent_manager`
    to store the pickled state of multi-agent teams.
-   **Database Initialization:** The `init_db` function is called on startup by
    the lifespan manager to ensure all necessary tables are created.
"""

import asyncio
import json
import os
import pickle
import uuid
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
from langgraph.types import Send
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from ..logger_config import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://admin:password@postgres:5432/agentic_orchestrator",
)

# Module-level engine for non-checkpointer database operations
# (assistants, threads, runs tables accessed by routers and managers)
# This provides backward compatibility with existing code.
# AsyncPostgresSaver uses its own per-instance engine for event loop safety.
_shared_engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = sessionmaker(
    _shared_engine, expire_on_commit=False, class_=AsyncSession
)

# Import Base from centralized location to avoid circular dependencies
from .models.base import Base

# This import must come AFTER Base is defined to avoid circular dependencies.
from .models import Assistant, Run, RunStep

# Note: Removed module-level table object exports (assistants, runs, run_steps)
# that were causing AttributeError during test collection. These were not used
# anywhere in the codebase and caused import failures when accessing __table__
# attributes before SQLAlchemy fully initialized the models.


async def init_db():
    """
    Initializes the database by creating the necessary tables if they do not exist.

    Creates a temporary engine for database initialization.
    This function is called once at startup and doesn't need a persistent engine.
    """
    # Create temporary engine for initialization
    temp_engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

    try:
        async with temp_engine.begin() as conn:
            # The Base.metadata will automatically know about the Assistant table
            # because the Assistant class inherits from Base.
            await conn.run_sync(Base.metadata.create_all)

            # You can still add other raw SQL commands if needed, but create_all is safer.
            # NOTE: checkpoints table is now managed by LangGraph 1.0.5 AsyncPostgresSaver.setup()
            # Do NOT create it here as it will conflict with LangGraph's expected schema.
            # LangGraph 1.0.5 requires a 7-column schema with JSONB types, not the old 3-column BYTEA schema.
            # The checkpointer.setup() method handles all checkpoint table creation and migrations.

            # Create separate table for full tool outputs to prevent token explosion
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS tool_outputs (
                    thread_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    output_sequence INT NOT NULL,
                    tool_name TEXT,
                    full_output JSONB NOT NULL,
                    output_size INT,
                    session_id TEXT,
                    mcp_session_id TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (thread_id, checkpoint_id, output_sequence)
                );
            """))

            # Create indexes for efficient querying
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_tool_outputs_thread ON tool_outputs(thread_id);"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_tool_outputs_session ON tool_outputs(session_id);"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_tool_outputs_created ON tool_outputs(created_at);"
                )
            )
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS run_steps (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    assistant_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    step_details JSON NOT NULL,
                    last_error JSON,
                    created_at BIGINT NOT NULL,
                    completed_at BIGINT,
                    failed_at BIGINT,
                    cancelled_at BIGINT,
                    expires_at BIGINT,
                    metadata JSON,
                    owner_id TEXT
                );
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    assistant_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    model TEXT,
                    instructions TEXT,
                    tools JSON,
                    metadata JSON,
                    owner_id TEXT
                );
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS multi_agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    session_data BYTEA
                );
            """))
        logger.info("Database tables initialized.")
    finally:
        # Dispose of temporary engine
        await temp_engine.dispose()


class AsyncPostgresSaver(BaseCheckpointSaver):
    """
    A LangGraph checkpointer that persists agent state to a PostgreSQL database.

    This class handles the serialization of agent checkpoints and metadata,
    storing them in the `checkpoints` table. It uses `pickle` for serialization
    and `sqlalchemy` with `asyncpg` for non-blocking database operations.

    ARCHITECTURE: Per-Instance Engine Pattern (Phase 1 Refactoring)

    Each AsyncPostgresSaver instance creates its own SQLAlchemy engine with
    its own connection pool. This provides:
    - Event loop safety: Engine created in current event loop context
    - No event loop binding conflicts with module-level engines
    - Eliminates database connection pool contention during concurrent operations
    - Faster checkpoint saves (10-50ms vs 100-500ms with module-level conflicts)
    - Improved reliability for long-running tool calls

    Connection Pool Configuration:
    - pool_size=3 (conservative, down from default 5)
    - max_overflow=7 (conservative, down from default 10)
    - Total per instance: 3-10 connections
    - Typical deployment: 3 pods × 4 instances = 120 connections (vs 45 with module-level)
    - Well within PostgreSQL max_connections=200 limit

    See: docs/architecture/ASYNCPOSTGRESSAVER_ARCHITECTURE_ANALYSIS.md
    """

    def __init__(self, pool_size: int = 1, max_overflow: int = 1):
        """
        Initialize AsyncPostgresSaver with per-instance database engine.

        Architecture Note:
        - This class creates its own per-instance engine for event loop safety
        - Module-level AsyncSessionLocal is used by routers/managers for assistants/runs tables
        - This separation prevents event loop conflicts while maintaining backward compatibility
        - CRITICAL: Many routers create AsyncPostgresSaver instances per-request (15+ locations)
        - Very conservative pool sizing (1+1=2 connections) prevents exhaustion under load

        Args:
            pool_size: Base connection pool size (default: 1, ultra-conservative)
            max_overflow: Maximum overflow connections (default: 1, ultra-conservative)

        Note: Ultra-conservative pool sizing prevents connection exhaustion in production.
        Total connections = pool_size + max_overflow = 2 per instance.
        With 15+ code locations creating instances, 2 connections/instance is critical.
        """
        super().__init__()

        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://admin:password@postgres:5432/agentic_orchestrator",
        )

        # Per-instance engine created in CURRENT event loop context
        # This eliminates event loop binding conflicts that slow down checkpoint saves
        self.engine = create_async_engine(
            database_url,
            pool_pre_ping=True,  # Verify connections before use
            pool_size=pool_size,
            max_overflow=max_overflow,
        )

        # Per-instance session factory using the instance engine
        self.session_factory = sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

        logger.debug(
            f"AsyncPostgresSaver initialized with per-instance engine "
            f"(pool_size={pool_size}, max_overflow={max_overflow})"
        )

    def __del__(self):
        """
        Finalizer to ensure engine disposal when instance is garbage collected.

        Mitigation for Risk #2 (Memory Leak from Undisposed Engines) from
        ASYNCPOSTGRESSAVER_REFACTORING_PLAN.md.

        Note: This provides automatic cleanup, but explicit cleanup via async
        context manager or HybridOrchestrationService.stop() is preferred.

        WARNING: __del__ cannot reliably dispose async resources during GC.
        This is a best-effort attempt that logs warnings instead of disposing.
        """
        if hasattr(self, "engine") and self.engine:
            logger.warning(
                "AsyncPostgresSaver being garbage collected with undisposed engine. "
                "This may indicate a connection leak. Use async context manager or "
                "explicit cleanup in HybridOrchestrationService.stop() instead."
            )
            # Note: We cannot reliably call async dispose() from __del__
            # because the event loop may already be closed during GC.
            # The engine will eventually be cleaned up by Python's GC,
            # but connections may remain in the pool temporarily.

    async def __aenter__(self):
        """Async context manager entry - return self."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - dispose engine on cleanup."""
        await self.engine.dispose()
        return False  # Don't suppress exceptions

    def _remove_orphaned_tool_messages(self, messages: list, thread_id: str) -> int:
        """
        Remove ToolMessages that are orphaned or duplicated.

        ENHANCED: Now detects and removes both:
        1. Orphaned ToolMessages (no matching AIMessage with tool_call_id)
        2. Duplicate ToolMessages (multiple ToolMessages with same tool_call_id)

        Duplicates can occur when synthetic error responses are added during checkpoint
        repair, and then the real ToolMessage arrives from the MCP server later.

        Args:
            messages: List of messages to check and repair
            thread_id: Thread ID for logging

        Returns:
            Total number of ToolMessages removed (orphaned + duplicates)
        """
        # Phase 1: Collect all valid tool_call_ids from AIMessages
        valid_tool_call_ids = set()
        for msg in messages:
            if (
                isinstance(msg, AIMessage)
                and hasattr(msg, "tool_calls")
                and msg.tool_calls
            ):
                for tool_call in msg.tool_calls:
                    # Handle both dict and object formats
                    if isinstance(tool_call, dict):
                        tool_id = tool_call.get("id")
                    else:
                        tool_id = getattr(tool_call, "id", None)
                    if tool_id:
                        valid_tool_call_ids.add(tool_id)

        # Phase 2: Track seen tool_call_ids to detect duplicates AND orphans
        seen_tool_call_ids = {}  # {tool_call_id: first_occurrence_index}
        duplicates_to_remove = []
        orphaned_to_remove = []

        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                tool_id = getattr(msg, "tool_call_id", None)

                # Check if orphaned (invalid tool_call_id)
                if tool_id and tool_id not in valid_tool_call_ids:
                    orphaned_to_remove.append((i, tool_id, "orphaned"))
                    logger.warning(
                        f"Orphaned ToolMessage at [{i}] with tool_call_id={tool_id} "
                        f"(no matching AIMessage)"
                    )
                # Check if duplicate (seen before)
                elif tool_id and tool_id in seen_tool_call_ids:
                    first_idx = seen_tool_call_ids[tool_id]
                    duplicates_to_remove.append((i, tool_id, "duplicate"))
                    logger.warning(
                        f"Duplicate ToolMessage at [{i}] with tool_call_id={tool_id}, "
                        f"first occurrence at [{first_idx}] - removing duplicate"
                    )
                # First occurrence - track it
                elif tool_id:
                    seen_tool_call_ids[tool_id] = i

        # Phase 3: Remove in reverse order to preserve indices
        all_removals = sorted(
            duplicates_to_remove + orphaned_to_remove, key=lambda x: x[0], reverse=True
        )

        for i, tool_id, reason in all_removals:
            logger.info(
                f"Removing {reason} ToolMessage at position [{i}] "
                f"with tool_call_id={tool_id}"
            )
            messages.pop(i)

        # Log summary
        if all_removals:
            logger.info(
                f"Checkpoint repair for thread {thread_id}: "
                f"removed {len(duplicates_to_remove)} duplicate ToolMessages, "
                f"{len(orphaned_to_remove)} orphaned ToolMessages"
            )

        return len(all_removals)

    def _repair_orphaned_tool_calls(self, messages: list, thread_id: str) -> int:
        """
        DISABLED: Do not add synthetic responses for orphaned tool_calls.

        Reason: Tool execution may still be in progress when checkpoint is saved.
        Adding synthetic responses during normal execution creates duplicates when
        the real ToolMessage arrives later from the MCP tool server.

        This is caused by LangGraph's async architecture:
        1. Agent node creates AIMessage with tool_calls
        2. Checkpoint saved immediately after agent node completes
        3. Tool node executes asynchronously (tools still in-flight)
        4. If we add synthetic ToolMessage here, we create duplicate when real response arrives

        Instead, we only log warnings to track tool_calls without responses.
        The real ToolMessage will arrive when tool execution completes.

        Args:
            messages: List of messages to check
            thread_id: Thread ID for logging

        Returns:
            Always returns 0 (no repairs made)
        """
        tool_call_ids_seen = {}  # Map tool_call_id to its position
        tool_response_ids_seen = set()

        # First pass: collect all tool call IDs and response IDs
        for i, msg in enumerate(messages):
            # Check for AIMessage with tool_calls
            if (
                isinstance(msg, AIMessage)
                and hasattr(msg, "tool_calls")
                and msg.tool_calls
            ):
                for tool_call in msg.tool_calls:
                    # Handle both dict and object formats
                    if isinstance(tool_call, dict):
                        tool_id = tool_call.get("id")
                    else:
                        tool_id = getattr(tool_call, "id", None)

                    if tool_id:
                        tool_call_ids_seen[tool_id] = i
            # Check for ToolMessage responses
            elif isinstance(msg, ToolMessage):
                tool_id = getattr(msg, "tool_call_id", None)
                if tool_id:
                    tool_response_ids_seen.add(tool_id)

        # Find orphaned tool calls
        orphaned_ids = set(tool_call_ids_seen.keys()) - tool_response_ids_seen

        # DISABLED: Do NOT add synthetic messages - just log and return 0
        # This prevents duplicate ToolMessages when real responses arrive
        if orphaned_ids:
            logger.warning(
                f"Thread {thread_id} has {len(orphaned_ids)} tool_calls without responses yet. "
                f"This is NORMAL if tools are still executing. "
                f"tool_call_ids: {list(orphaned_ids)}"
            )
            logger.debug(
                f"Checkpoint state for thread {thread_id}: "
                f"{len(tool_call_ids_seen)} tool_calls made, "
                f"{len(tool_response_ids_seen)} responses received"
            )

        # Return 0 - no synthetic messages added
        return 0

    def _validate_message_consistency(self, messages: list) -> bool:
        """
        Check if all tool calls have responses.

        Args:
            messages: List of messages to validate

        Returns:
            True if consistent, False otherwise
        """
        tool_call_ids = set()
        tool_response_ids = set()

        for msg in messages:
            # Check for AIMessage with tool_calls
            if (
                isinstance(msg, AIMessage)
                and hasattr(msg, "tool_calls")
                and msg.tool_calls
            ):
                for tool_call in msg.tool_calls:
                    # Handle both dict and object formats
                    if isinstance(tool_call, dict):
                        tool_id = tool_call.get("id")
                    else:
                        tool_id = getattr(tool_call, "id", None)

                    if tool_id:
                        tool_call_ids.add(tool_id)
            # Check for ToolMessage responses
            elif isinstance(msg, ToolMessage):
                tool_id = getattr(msg, "tool_call_id", None)
                if tool_id:
                    tool_response_ids.add(tool_id)

        # All tool calls should have responses
        orphaned = tool_call_ids - tool_response_ids
        if orphaned:
            logger.warning(f"Found orphaned tool calls: {orphaned}")
            return False
        return True

    async def aget_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        """
        Asynchronously retrieves a checkpoint and its metadata from the database.

        Args:
            config: The LangGraph configuration dictionary, which must contain
                    `configurable.thread_id`.

        Returns:
            A CheckpointTuple if found, otherwise None.
        """
        thread_id = config["configurable"]["thread_id"]
        async with self.session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT checkpoint, metadata FROM checkpoints WHERE thread_id = :thread_id"
                ),
                {"thread_id": thread_id},
            )
            row = result.fetchone()
            if row:
                checkpoint = pickle.loads(row[0])
                metadata = pickle.loads(row[1])

                # Restore empty full_tool_outputs field to conform to AgentState schema
                if isinstance(checkpoint, dict) and "channel_values" in checkpoint:
                    channel_values = checkpoint["channel_values"]
                    if (
                        isinstance(channel_values, dict)
                        and "full_tool_outputs" not in channel_values
                    ):
                        channel_values["full_tool_outputs"] = []
                        logger.debug(
                            f"Restored empty full_tool_outputs field for thread {thread_id}"
                        )

                    # Repair checkpoint messages - two-phase repair strategy:
                    # 1. Remove orphaned ToolMessages (no preceding tool_calls)
                    # 2. Add synthetic responses for orphaned tool_calls (no response ToolMessages)
                    messages = channel_values.get("messages", [])
                    if messages:
                        # Debug: Log message sequence before repair
                        logger.debug(
                            f"Loading checkpoint for thread {thread_id} with {len(messages)} messages"
                        )
                        for i, msg in enumerate(messages):
                            msg_type = type(msg).__name__
                            if (
                                isinstance(msg, AIMessage)
                                and hasattr(msg, "tool_calls")
                                and msg.tool_calls
                            ):
                                tool_ids = [
                                    (
                                        tc.get("id")
                                        if isinstance(tc, dict)
                                        else getattr(tc, "id", None)
                                    )
                                    for tc in msg.tool_calls
                                ]
                                logger.debug(
                                    f"  [{i}] {msg_type} with tool_calls: {tool_ids}"
                                )
                            elif isinstance(msg, ToolMessage):
                                tool_call_id = getattr(msg, "tool_call_id", None)
                                logger.debug(
                                    f"  [{i}] {msg_type} responding to tool_call_id: {tool_call_id}"
                                )
                            else:
                                logger.debug(f"  [{i}] {msg_type}")

                        # Phase 1: Remove orphaned ToolMessages
                        removed = self._remove_orphaned_tool_messages(
                            messages, thread_id
                        )

                        # Phase 2: Add synthetic responses for orphaned tool_calls
                        repaired = self._repair_orphaned_tool_calls(messages, thread_id)

                        # Update checkpoint if any repairs were made
                        if removed > 0 or repaired > 0:
                            await session.execute(
                                text("""
                                    UPDATE checkpoints SET checkpoint = :checkpoint
                                    WHERE thread_id = :thread_id
                                """),
                                {
                                    "thread_id": thread_id,
                                    "checkpoint": pickle.dumps(checkpoint),
                                },
                            )
                            await session.commit()
                            logger.info(
                                f"Saved repaired checkpoint for thread {thread_id}: removed {removed} orphaned ToolMessages, added {repaired} synthetic responses"
                            )

                # Ensure checkpoint has proper LangGraph version field for migration compatibility
                if isinstance(checkpoint, dict) and "v" not in checkpoint:
                    checkpoint["v"] = 4  # Current LangGraph checkpoint version
                    logger.debug(
                        f"Added version field to loaded checkpoint for thread {thread_id}"
                    )

                    # Update the checkpoint in the database with the version field
                    await session.execute(
                        text("""
                            UPDATE checkpoints SET checkpoint = :checkpoint 
                            WHERE thread_id = :thread_id
                        """),
                        {
                            "thread_id": thread_id,
                            "checkpoint": pickle.dumps(checkpoint),
                        },
                    )
                    await session.commit()

                return CheckpointTuple(
                    config=config,
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config=config,
                )
        return None

    async def aput(
        self,
        config: dict,
        checkpoint: dict,
        metadata: dict,
        parent_config: Optional[dict] = None,
    ) -> None:
        """
        Asynchronously saves (upserts) a checkpoint and its metadata to the database.

        Args:
            config: The LangGraph configuration dictionary, which must contain
                    `configurable.thread_id`.
            checkpoint: The agent state checkpoint to save.
            metadata: The metadata associated with the checkpoint.
        """
        thread_id = config["configurable"]["thread_id"]

        # Create a copy of checkpoint to avoid modifying the original
        # CRITICAL FIX: LangGraph Send objects don't support .copy() method
        # Send objects are used for dynamic routing in graph mode and are immutable
        if isinstance(checkpoint, Send):
            # Send objects are immutable routing instructions, preserve reference
            checkpoint_copy = checkpoint
        elif checkpoint:
            checkpoint_copy = checkpoint.copy()
        else:
            checkpoint_copy = {}

        # Validate and repair message consistency before saving
        if isinstance(checkpoint_copy, dict) and "channel_values" in checkpoint_copy:
            channel_values = checkpoint_copy["channel_values"]

            # Check and repair message consistency - two-phase repair strategy
            messages = channel_values.get("messages", [])
            if messages and not self._validate_message_consistency(messages):
                logger.warning(
                    f"Checkpoint has inconsistent tool messages for thread {thread_id}, attempting repair before save"
                )
                # Phase 1: Remove orphaned ToolMessages
                removed = self._remove_orphaned_tool_messages(messages, thread_id)

                # Phase 2: Add synthetic responses for orphaned tool_calls
                repaired = self._repair_orphaned_tool_calls(messages, thread_id)

                if removed > 0 or repaired > 0:
                    logger.info(
                        f"Repaired checkpoint before saving for thread {thread_id}: removed {removed} orphaned ToolMessages, added {repaired} synthetic responses"
                    )

            # Save full_tool_outputs to separate table before removing from checkpoint
            if (
                isinstance(channel_values, dict)
                and "full_tool_outputs" in channel_values
            ):
                # Log the size of data being filtered for monitoring
                full_outputs = channel_values["full_tool_outputs"]
                if full_outputs:
                    total_size = sum(
                        len(str(output)) for output in full_outputs if output
                    )
                    logger.debug(
                        f"Saving full_tool_outputs to separate table (thread {thread_id}): {len(full_outputs)} outputs, ~{total_size} chars"
                    )

                    # Save to separate table BEFORE deleting from checkpoint
                    checkpoint_id = checkpoint_copy.get("id", str(uuid.uuid4()))
                    await self.save_tool_outputs(
                        thread_id, checkpoint_id, full_outputs, config
                    )

                    # Replace with empty list instead of deleting to maintain schema
                    # This prevents issues with LangGraph expecting the field to exist
                    checkpoint_copy["channel_values"]["full_tool_outputs"] = []

                # Verify messages field is intact
                if "messages" in channel_values:
                    message_count = len(channel_values["messages"])
                    logger.debug(
                        f"Checkpoint has {message_count} messages preserved after full_tool_outputs separation"
                    )

        # Ensure checkpoint has proper LangGraph fields for migration compatibility
        if isinstance(checkpoint_copy, dict):
            if "v" not in checkpoint_copy:
                checkpoint_copy["v"] = 4  # Current LangGraph checkpoint version
                logger.debug(
                    f"Added version field to checkpoint for thread {thread_id}"
                )
            if "id" not in checkpoint_copy:
                checkpoint_copy["id"] = str(
                    uuid.uuid4()
                )  # Generate unique checkpoint ID
                logger.debug(f"Added ID field to checkpoint for thread {thread_id}")

        # Ensure metadata has required LangGraph fields
        if isinstance(metadata, dict):
            if "step" not in metadata:
                metadata["step"] = (
                    0  # Initialize step counter for LangGraph compatibility
                )
                logger.debug(
                    f"Added step field to checkpoint metadata for thread {thread_id}"
                )
            if "source" not in metadata:
                metadata["source"] = "input"  # Default source value
                logger.debug(
                    f"Added source field to checkpoint metadata for thread {thread_id}"
                )
            if "writes" not in metadata:
                metadata["writes"] = {}  # Initialize writes dictionary
                logger.debug(
                    f"Added writes field to checkpoint metadata for thread {thread_id}"
                )

        async with self.session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO checkpoints (thread_id, checkpoint, metadata)
                    VALUES (:thread_id, :checkpoint, :metadata)
                    ON CONFLICT (thread_id) DO UPDATE SET
                        checkpoint = EXCLUDED.checkpoint,
                        metadata = EXCLUDED.metadata;
                """),
                {
                    "thread_id": thread_id,
                    "checkpoint": pickle.dumps(checkpoint_copy),
                    "metadata": pickle.dumps(metadata),
                },
            )
            await session.commit()

    async def save_tool_outputs(
        self, thread_id: str, checkpoint_id: str, full_outputs: List, config: dict
    ) -> None:
        """
        Save full tool outputs to separate table to prevent token explosion.

        This method stores the complete tool outputs in a separate table while the main
        checkpoint only contains sanitized versions for LLM context.

        Args:
            thread_id: The LangGraph thread ID (typically the session_id)
            checkpoint_id: Unique identifier for this checkpoint
            full_outputs: List of full tool outputs to save
            config: Configuration dict that may contain session information
        """
        if not full_outputs:
            return

        # Extract session IDs from config if available
        session_id = config.get("configurable", {}).get("session_id")
        mcp_session_id = config.get("configurable", {}).get("mcp_session_id")

        # For multi-agent sessions, thread_id might be formatted as "mcp_session::multi_agent_session"
        if "::" in thread_id:
            parts = thread_id.split("::")
            if len(parts) == 2 and not mcp_session_id:
                mcp_session_id = parts[0]

        async with self.session_factory() as session:
            for seq, output in enumerate(full_outputs):
                try:
                    # Extract tool name if available
                    tool_name = "unknown"
                    if isinstance(output, dict):
                        tool_name = (
                            output.get("tool_name") or output.get("tool") or "unknown"
                        )

                    # Convert output to JSON
                    if isinstance(output, str):
                        output_json = json.dumps({"output": output})
                    else:
                        output_json = json.dumps(output)

                    output_size = len(output_json)

                    # Log if output is very large
                    if output_size > 100000:  # 100KB
                        logger.warning(
                            f"Large tool output detected: {tool_name} - {output_size} chars"
                        )

                    await session.execute(
                        text("""
                            INSERT INTO tool_outputs
                            (thread_id, checkpoint_id, output_sequence, tool_name, full_output, output_size, session_id, mcp_session_id)
                            VALUES (:thread_id, :checkpoint_id, :sequence, :tool_name, :output, :size, :session_id, :mcp_session_id)
                            ON CONFLICT (thread_id, checkpoint_id, output_sequence) DO UPDATE
                            SET full_output = EXCLUDED.full_output,
                                output_size = EXCLUDED.output_size,
                                tool_name = EXCLUDED.tool_name
                        """),
                        {
                            "thread_id": thread_id,
                            "checkpoint_id": checkpoint_id,
                            "sequence": seq,
                            "tool_name": tool_name,
                            "output": output_json,
                            "size": output_size,
                            "session_id": session_id,
                            "mcp_session_id": mcp_session_id,
                        },
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to save tool output {seq} for thread {thread_id}: {e}"
                    )
                    # Continue saving other outputs even if one fails

            await session.commit()
            logger.info(
                f"Saved {len(full_outputs)} tool outputs for thread {thread_id} to separate table"
            )

    async def get_tool_outputs(
        self, thread_id: str, checkpoint_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Retrieve full tool outputs for a thread.

        Args:
            thread_id: The thread ID to retrieve outputs for
            checkpoint_id: Optional specific checkpoint ID

        Returns:
            List of tool outputs as dictionaries
        """
        async with self.session_factory() as session:
            if checkpoint_id:
                result = await session.execute(
                    text("""
                        SELECT full_output, tool_name, output_size
                        FROM tool_outputs
                        WHERE thread_id = :thread_id AND checkpoint_id = :checkpoint_id
                        ORDER BY output_sequence
                    """),
                    {"thread_id": thread_id, "checkpoint_id": checkpoint_id},
                )
            else:
                result = await session.execute(
                    text("""
                        SELECT full_output, tool_name, output_size
                        FROM tool_outputs
                        WHERE thread_id = :thread_id
                        ORDER BY created_at DESC, output_sequence
                        LIMIT 100
                    """),
                    {"thread_id": thread_id},
                )

            outputs = []
            for row in result.fetchall():
                try:
                    output_data = json.loads(row[0])
                    output_data["_tool_name"] = row[1]
                    output_data["_size"] = row[2]
                    outputs.append(output_data)
                except json.JSONDecodeError:
                    logger.error(f"Failed to decode tool output for thread {thread_id}")

            return outputs

    async def aput_writes(
        self,
        config: dict,
        writes: List[Tuple[str, Any]],
        parent_config: Optional[dict] = None,
    ) -> None:
        """
        Asynchronously saves multiple writes to the database.
        This is a required method for the BaseCheckpointSaver interface.
        """
        for thread_id, checkpoint in writes:
            # Since aput requires metadata, we fetch the existing metadata first.
            # This ensures metadata is not lost during multi-step agent runs.
            existing_tuple = await self.aget_tuple(
                {"configurable": {"thread_id": thread_id}}
            )
            existing_metadata = existing_tuple[1] if existing_tuple else {}
            await self.aput(
                {"configurable": {"thread_id": thread_id}},
                checkpoint,
                existing_metadata,
            )

    async def adelete(self, config: dict) -> None:
        """
        Asynchronously deletes a checkpoint from the database.

        Args:
            config: The LangGraph configuration dictionary, which must contain
                    `configurable.thread_id`.
        """
        thread_id = config["configurable"]["thread_id"]
        async with self.session_factory() as session:
            await session.execute(
                text("DELETE FROM checkpoints WHERE thread_id = :thread_id"),
                {"thread_id": thread_id},
            )
            await session.commit()

    # Add synchronous stubs to fully comply with the BaseCheckpointSaver interface
    def get_tuple(self, config: dict) -> Optional[Tuple[dict, dict]]:
        raise NotImplementedError("Synchronous get_tuple is not implemented.")

    def put(self, config: dict, checkpoint: dict, metadata: dict) -> None:
        raise NotImplementedError("Synchronous put is not implemented.")

    def put_writes(self, config: dict, writes: List[Tuple[str, Any]]) -> None:
        raise NotImplementedError("Synchronous put_writes is not implemented.")

    async def alist(self, config: dict) -> None:
        raise NotImplementedError("alist is not implemented.")

    def list(self, config: dict) -> None:
        raise NotImplementedError("list is not implemented.")
