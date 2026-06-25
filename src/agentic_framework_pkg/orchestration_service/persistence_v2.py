"""
LangGraph 1.0.5 AsyncPostgresSaver Wrapper

This module provides a backward-compatible wrapper for LangGraph 1.0.5's
AsyncPostgresSaver, which requires an external connection pool.

Architecture:
- Module-level singleton AsyncConnectionPool (5-10 connections total)
- Wrapper class preserving Session 26 API: __init__(pool_size, max_overflow)
- Delegates all operations to LangGraph 1.0.5 AsyncPostgresSaver
- Auto-setup guards ensure checkpointer is initialized before use

Session 26 Compatibility:
- Preserves session-level agent reuse pattern
- Preserves ultra-conservative pooling philosophy
- State isolation via thread IDs (not separate instances)

Connection Reduction:
- Phase 1 (Session 26): 150+ → 20-30 connections (80-85% reduction)
- Phase 2 (This): 20-30 → 10-20 connections (50% further reduction)
"""

import os
import asyncio
import json
from typing import Optional, Any, Iterator, Sequence, AsyncIterator, List
from contextlib import asynccontextmanager
from uuid import uuid4

from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver as LangGraphAsyncPostgresSaver
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata, CheckpointTuple, BaseCheckpointSaver
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..logger_config import get_logger
from .models.session_models import ToolOutput
from .persistence.checkpointing import get_async_session
from ..core.observability_factory import ObservabilityFactory

logger = get_logger(__name__)

# Module-level singleton: Shared connection pool
_global_connection_pool: Optional[AsyncConnectionPool] = None
_pool_lock = asyncio.Lock()


async def get_or_create_connection_pool() -> AsyncConnectionPool:
    """
    Get or create the module-level connection pool singleton.

    This function is thread-safe and ensures only one pool is created
    across all AsyncPostgresSaver instances in the application.

    Connection Pool Configuration:
    - min_size=2: Keep 2 connections warm at all times
    - max_size=10: Allow bursts up to 10 concurrent connections
    - timeout=30: Wait up to 30s for connection availability

    Returns:
        AsyncConnectionPool: Shared connection pool instance
    """
    global _global_connection_pool

    async with _pool_lock:
        if _global_connection_pool is None:
            database_url = os.getenv(
                "DATABASE_URL",
                "postgresql://admin:password@postgres:5432/agentic_orchestrator"
            )

            # Convert SQLAlchemy-style URL (postgresql+asyncpg://) to psycopg3 format (postgresql://)
            # This handles both postgresql+asyncpg and postgresql+psycopg2 notation
            if "+asyncpg://" in database_url:
                database_url = database_url.replace("+asyncpg://", "://")
            elif "+psycopg2://" in database_url:
                database_url = database_url.replace("+psycopg2://", "://")

            logger.info(
                "Creating module-level AsyncConnectionPool singleton "
                "(min_size=4, max_size=16)"
            )

            # Configure callback to set autocommit for CREATE INDEX CONCURRENTLY support
            async def configure_connection(conn):
                """Configure connection with autocommit for migrations."""
                await conn.set_autocommit(True)

            async def check_connection(conn):
                """Validate connection is alive before handing it out.

                Equivalent to SQLAlchemy's pool_pre_ping. Detects stale
                connections after container recreation (Podman IP change).
                If the check raises, psycopg_pool discards the connection
                and creates a new one.
                """
                try:
                    await conn.execute("SELECT 1")
                except Exception as e:
                    logger.warning(
                        f"Connection health check failed (will reconnect): {e}"
                    )
                    raise

            _global_connection_pool = AsyncConnectionPool(
                conninfo=database_url,
                min_size=4,   # Changed from 2: 1 warm connection per worker (4 workers)
                max_size=16,  # Changed from 10: 4 workers × 4 connections burst capacity
                timeout=30,
                configure=configure_connection,
                check=check_connection,
                reconnect_timeout=5,  # Retry reconnection for up to 5 seconds
                open=False  # Don't auto-open (deprecated), we'll open explicitly
            )

            # Explicitly open the pool (recommended pattern per psycopg_pool docs)
            await _global_connection_pool.open()

            logger.info("✅ Module-level connection pool created successfully")

        return _global_connection_pool


async def close_global_connection_pool():
    """
    Close the global connection pool (called at service shutdown).

    This function should be called in the service's shutdown lifecycle
    (e.g., FastAPI lifespan shutdown event).
    """
    global _global_connection_pool

    async with _pool_lock:
        if _global_connection_pool is not None:
            logger.info("Closing module-level connection pool...")
            await _global_connection_pool.close()
            _global_connection_pool = None
            logger.info("✅ Module-level connection pool closed")


class AsyncPostgresSaver(BaseCheckpointSaver):
    """
    Backward-compatible wrapper for LangGraph 1.0.6 AsyncPostgresSaver.

    Inherits from BaseCheckpointSaver to pass LangGraph's isinstance() type check.

    This wrapper preserves the Session 26 API while delegating to LangGraph 1.0.5's
    new AsyncPostgresSaver implementation that requires an external connection pool.

    LangGraph 1.0.5 Breaking Changes Handled:
    - BREAKING: AsyncPostgresSaver.__init__() now requires external conn parameter
      → Wrapper provides conn from module-level pool singleton
    - BREAKING: aput() now requires new_versions parameter (4 args instead of 3)
      → Wrapper accepts and forwards new_versions to LangGraph 1.0.5
    - BREAKING: Database schema expanded (checkpoint_ns, checkpoint_id, parent_checkpoint_id)
      → setup() runs 10 migrations to create new schema
    - BREAKING: psycopg3 replaces asyncpg for connection management
      → Module pool uses psycopg_pool.AsyncConnectionPool

    Preserved Session 26 API:
    - __init__(pool_size, max_overflow) - parameters ignored, module pool handles sizing
    - All BaseCheckpointSaver methods delegate to LangGraph 1.0.5 backend
    - Auto-setup guards ensure checkpointer initialized before use

    Usage (unchanged from Session 26):
        checkpointer = AsyncPostgresSaver(pool_size=1, max_overflow=1)
        # Auto-setup on first use, delegates to LangGraph 1.0.5 backend
        checkpoint = await checkpointer.aget(config)

    Key Design Decisions:
    - pool_size and max_overflow parameters IGNORED (preserved for API compatibility)
    - Module-level pool handles all connection management (5-10 connections total)
    - setup() called automatically on first use (idempotent)
    - _owns_checkpointer flag NOT needed (no per-instance disposal)
    - Connection pool shared across all AsyncPostgresSaver instances

    Migration from LangGraph 0.0.8 → 1.0.5:
    - Old schema (3 columns) automatically migrated to new schema (6 columns + 3 tables)
    - Checkpoint data format compatible with LangGraph 1.0.5 serialization
    - Rollback requires dropping new tables and recreating old schema
    """

    def __init__(self, pool_size: int = 1, max_overflow: int = 1):
        """
        Initialize AsyncPostgresSaver wrapper.

        Args:
            pool_size: IGNORED - Preserved for API compatibility with Session 26
            max_overflow: IGNORED - Module-level pool handles sizing

        Note: Parameters preserved to maintain backward compatibility with
        existing code: AsyncPostgresSaver(pool_size=1, max_overflow=1)
        """
        self._langgraph_saver: Optional[LangGraphAsyncPostgresSaver] = None
        self._setup_complete = False

        # Log parameter usage for debugging (parameters are ignored)
        if pool_size != 1 or max_overflow != 1:
            logger.warning(
                f"AsyncPostgresSaver initialized with pool_size={pool_size}, "
                f"max_overflow={max_overflow}. These parameters are IGNORED. "
                f"Module-level pool handles connection management."
            )

    async def setup(self):
        """
        Initialize the checkpointer with shared connection pool.

        This method is idempotent and can be called multiple times safely.
        It's called automatically by all checkpoint methods, but can also
        be called explicitly for eager initialization.
        """
        if not self._setup_complete:
            logger.debug("Setting up AsyncPostgresSaver with module-level pool...")

            # Get or create the shared module-level pool
            pool = await get_or_create_connection_pool()

            # Create LangGraph 1.0.5 AsyncPostgresSaver with external pool
            self._langgraph_saver = LangGraphAsyncPostgresSaver(conn=pool)

            # Initialize database schema (creates checkpoints table if needed)
            await self._langgraph_saver.setup()

            self._setup_complete = True
            logger.debug("✅ AsyncPostgresSaver setup complete")

    async def _ensure_setup(self):
        """Auto-setup guard: Ensures checkpointer initialized before use."""
        if not self._setup_complete:
            await self.setup()

    # Delegate all BaseCheckpointSaver methods to LangGraph 1.0.5 backend

    async def aget(self, config: dict, **kwargs) -> Optional[Checkpoint]:
        """Get checkpoint by config (auto-setup guard).

        Phase 3 Instrumentation: Tracks checkpoint load operations to observability backend.
        """
        await self._ensure_setup()
        result = await self._langgraph_saver.aget(config, **kwargs)

        # Phase 3: Track checkpoint load operation (non-blocking, error-safe)
        if result is not None:
            try:
                thread_id = config.get("configurable", {}).get("thread_id", "unknown")
                checkpoint_id = result.get("id", "unknown") if isinstance(result, dict) else "unknown"

                # Extract session context from config
                session_context = {
                    "session_id": config.get("configurable", {}).get("session_id"),
                    "mcp_session_id": config.get("configurable", {}).get("mcp_session_id"),
                    "multi_agent_session_id": config.get("configurable", {}).get("multi_agent_session_id"),
                    "gateway_session_id": config.get("configurable", {}).get("gateway_session_id"),
                }

                # Calculate checkpoint size for metrics
                checkpoint_size = len(json.dumps(str(result)))

                obs_factory = ObservabilityFactory()
                await obs_factory.track_checkpoint(
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_data={"size": checkpoint_size},
                    metadata={
                        "operation": "load",
                        "session_context": session_context
                    }
                )
                logger.debug(f"[CHECKPOINT_TRACKING] Tracked checkpoint load (aget): {checkpoint_id} for thread {thread_id}")
            except Exception as e:
                # Don't fail checkpoint load if observability tracking fails
                logger.warning(f"[CHECKPOINT_TRACKING] Failed to track checkpoint load (aget): {e}")

        return result

    async def aget_tuple(self, config: dict, **kwargs) -> Optional[CheckpointTuple]:
        """Get checkpoint tuple by config (auto-setup guard).

        Phase 3 Instrumentation: Tracks checkpoint load operations to observability backend.

        Handles LangGraph checkpoint format migrations gracefully (KeyError: 'v' for old checkpoints).
        """
        await self._ensure_setup()

        try:
            result = await self._langgraph_saver.aget_tuple(config, **kwargs)
        except KeyError as e:
            # Handle old checkpoint format without 'v' version field (LangGraph migration issue)
            if str(e) == "'v'":
                thread_id = config.get("configurable", {}).get("thread_id", "unknown")
                logger.warning(
                    f"Checkpoint format migration issue for thread {thread_id}: "
                    f"Old checkpoint missing 'v' version field. Treating as empty checkpoint."
                )
                # Return None to indicate no valid checkpoint found (trigger fresh initialization)
                return None
            # Re-raise other KeyErrors
            raise

        # Phase 3: Track checkpoint load operation (non-blocking, error-safe)
        if result is not None:
            try:
                thread_id = config.get("configurable", {}).get("thread_id", "unknown")
                checkpoint_id = result.checkpoint.get("id", "unknown") if result.checkpoint else "unknown"

                # Extract session context from config
                session_context = {
                    "session_id": config.get("configurable", {}).get("session_id"),
                    "mcp_session_id": config.get("configurable", {}).get("mcp_session_id"),
                    "multi_agent_session_id": config.get("configurable", {}).get("multi_agent_session_id"),
                    "gateway_session_id": config.get("configurable", {}).get("gateway_session_id"),
                }

                # Calculate checkpoint size for metrics
                checkpoint_size = len(json.dumps(str(result.checkpoint))) if result.checkpoint else 0

                obs_factory = ObservabilityFactory()
                await obs_factory.track_checkpoint(
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    checkpoint_data={"size": checkpoint_size},
                    metadata={
                        "operation": "load",
                        "session_context": session_context,
                        "metadata": result.metadata if hasattr(result, 'metadata') else {}
                    }
                )
                logger.debug(f"[CHECKPOINT_TRACKING] Tracked checkpoint load: {checkpoint_id} for thread {thread_id}")
            except Exception as e:
                # Don't fail checkpoint load if observability tracking fails
                logger.warning(f"[CHECKPOINT_TRACKING] Failed to track checkpoint load: {e}")

        return result

    async def alist(
        self, config: dict, *, filter: Optional[dict] = None, **kwargs
    ) -> AsyncIterator[CheckpointTuple]:
        """List checkpoints matching config and optional filter (auto-setup guard)."""
        await self._ensure_setup()
        async for item in self._langgraph_saver.alist(config, filter=filter, **kwargs):
            yield item

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
        **kwargs
    ) -> dict:
        """Save checkpoint with metadata and channel versions (auto-setup guard).

        Phase 3 Instrumentation: Tracks checkpoint save operations to observability backend.
        """
        await self._ensure_setup()
        result = await self._langgraph_saver.aput(config, checkpoint, metadata, new_versions, **kwargs)

        # Phase 3: Track checkpoint save operation (non-blocking, error-safe)
        try:
            thread_id = config.get("configurable", {}).get("thread_id", "unknown")
            checkpoint_id = result.get("checkpoint_id") or checkpoint.get("id", "unknown")

            # Extract session context from config
            session_context = {
                "session_id": config.get("configurable", {}).get("session_id"),
                "mcp_session_id": config.get("configurable", {}).get("mcp_session_id"),
                "multi_agent_session_id": config.get("configurable", {}).get("multi_agent_session_id"),
                "gateway_session_id": config.get("configurable", {}).get("gateway_session_id"),
            }

            # Calculate checkpoint size for metrics
            checkpoint_size = len(json.dumps({
                "checkpoint": str(checkpoint),
                "metadata": metadata,
                "versions": new_versions
            }))

            obs_factory = ObservabilityFactory()
            await obs_factory.track_checkpoint(
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                checkpoint_data={"size": checkpoint_size, "versions": new_versions},
                metadata={
                    "operation": "save",
                    "session_context": session_context,
                    "metadata": metadata
                }
            )
            logger.debug(f"[CHECKPOINT_TRACKING] Tracked checkpoint save: {checkpoint_id} for thread {thread_id}")
        except Exception as e:
            # Don't fail checkpoint save if observability tracking fails
            logger.warning(f"[CHECKPOINT_TRACKING] Failed to track checkpoint save: {e}")

        return result

    async def aput_writes(
        self, config: dict, writes: Sequence[tuple], task_id: str, **kwargs
    ):
        """Save pending writes for a checkpoint (auto-setup guard)."""
        await self._ensure_setup()
        return await self._langgraph_saver.aput_writes(config, writes, task_id, **kwargs)

    def get_next_version(self, current: Optional[str], channel: str) -> str:
        """
        Generate next version for a checkpoint.

        Note: This method doesn't require setup as it's a pure computation.
        """
        if self._langgraph_saver is None:
            # Fallback: Use LangGraph's default versioning logic
            import uuid
            return str(uuid.uuid4())
        return self._langgraph_saver.get_next_version(current, channel)

    async def dispose(self):
        """
        Dispose checkpointer (no-op for shared pool).

        Important: This method does NOT close the module-level connection pool.
        The pool is shared across all instances and is only closed at service
        shutdown via close_global_connection_pool().

        This preserves Session 26 agent lifecycle patterns where agents can be
        disposed without affecting other agents' checkpointers.
        """
        logger.debug("AsyncPostgresSaver.dispose() called (no-op for shared pool)")
        self._langgraph_saver = None
        self._setup_complete = False

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

        # Use SQLAlchemy ORM session (reuses existing connection pool)
        async with get_async_session() as db_session:
            for seq, output in enumerate(full_outputs):
                try:
                    # Extract tool metadata from output
                    tool_name = "unknown"
                    tool_call_id = None

                    if isinstance(output, dict):
                        tool_name = (
                            output.get("tool_name") or output.get("tool") or "unknown"
                        )
                        tool_call_id = output.get("tool_call_id")

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

                    # Generate tool_call_id if not present in output
                    if not tool_call_id:
                        tool_call_id = f"auto_{uuid4().hex[:12]}"

                    # Create ToolOutput ORM data
                    # ALL columns from model automatically included - no manual sync needed!
                    tool_output_data = {
                        'thread_id': thread_id,
                        'checkpoint_id': checkpoint_id,
                        'tool_call_id': tool_call_id,  # ✅ Now included (fixes constraint violation)
                        'output_sequence': seq,
                        'tool_name': tool_name,
                        'full_output': json.loads(output_json),  # JSONB column expects dict
                        'output_size': output_size,
                        'session_id': session_id,
                        'mcp_session_id': mcp_session_id,
                        'retention_status': 'active',  # Python default from model __init__
                    }

                    # PostgreSQL UPSERT using SQLAlchemy dialect-specific syntax
                    # ON CONFLICT ensures idempotency (safe for retries)
                    stmt = pg_insert(ToolOutput).values(**tool_output_data)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['thread_id', 'checkpoint_id', 'output_sequence'],
                        set_={
                            'full_output': stmt.excluded.full_output,
                            'output_size': stmt.excluded.output_size,
                            'tool_name': stmt.excluded.tool_name,
                            'tool_call_id': stmt.excluded.tool_call_id,
                        }
                    )

                    await db_session.execute(stmt)

                except Exception as e:
                    logger.error(
                        f"Failed to save tool output {seq} for thread {thread_id}: {e}"
                    )
                    # Continue saving other outputs even if one fails

            await db_session.commit()
            logger.info(
                f"Saved {len(full_outputs)} tool outputs for thread {thread_id} via ORM"
            )


# Optional: Context manager for explicit lifecycle management
@asynccontextmanager
async def create_checkpointer(pool_size: int = 1, max_overflow: int = 1):
    """
    Context manager for creating AsyncPostgresSaver with automatic setup.

    Usage:
        async with create_checkpointer() as checkpointer:
            checkpoint = await checkpointer.aget(config)

    Note: Prefer direct instantiation + auto-setup for most use cases.
    This is provided for explicit lifecycle management in tests.
    """
    checkpointer = AsyncPostgresSaver(pool_size=pool_size, max_overflow=max_overflow)
    await checkpointer.setup()
    try:
        yield checkpointer
    finally:
        await checkpointer.dispose()


# Export symbols for backward compatibility
__all__ = [
    "AsyncPostgresSaver",
    "get_or_create_connection_pool",
    "close_global_connection_pool",
    "create_checkpointer",
]
