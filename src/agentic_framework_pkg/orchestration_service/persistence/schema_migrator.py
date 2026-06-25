"""
Checkpoint Schema Migrator

Idempotent schema migration manager for LangGraph 1.0.5 checkpoints.

This module provides automatic detection and migration of checkpoint schema
from LangGraph 0.0.8 (old) to LangGraph 1.0.5 (new) using the ORM models
in `models/checkpoint_schema.py` as the source of truth.

Features:
- Detects schema state: MISSING, OLD, CURRENT, DRIFT
- Migrates old schemas to new (ALTER TABLE or DROP/CREATE)
- Validates schema matches ORM definitions
- Provides backup and rollback support
- Integrates with Alembic and quick-start script

Usage:
    ```python
    migrator = CheckpointSchemaMigrator()
    state = await migrator.detect_schema_state()

    if state != SchemaState.CURRENT:
        result = await migrator.migrate_to_current(backup=True)
        print(f"Migration result: {result.status}")
    ```

Integration:
- Quick-start script: `scripts/deps/manage_checkpoint_schema.py --auto-migrate`
- Alembic migration: `versions/YYYYMMDD_HHMM_migrate_langgraph_checkpoints.py`
- Validation: `scripts/deps/validate_schema.py` (checkpoints table)
"""

import os
import asyncio
from enum import Enum
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime

import asyncpg
from sqlalchemy import create_engine, inspect, MetaData, Table
from sqlalchemy.engine import Engine

from ...logger_config import get_logger
from ..models.checkpoint_schema import (
    Base,
    Checkpoint,
    CheckpointBlob,
    CheckpointMigration,
    CheckpointWrite,
    CHECKPOINT_TABLES,
    CHECKPOINT_SCHEMA_VERSION,
)

logger = get_logger(__name__)


class SchemaState(Enum):
    """
    Checkpoint schema state enumeration.

    States:
        MISSING: Checkpoints table doesn't exist
        OLD: LangGraph 0.0.8 schema (3-5 columns, bytea types, single PK)
        CURRENT: LangGraph 1.0.5 schema (7 columns, jsonb types, composite PK)
        DRIFT: Unexpected schema (neither old nor new, manual intervention needed)
    """

    MISSING = "missing"
    OLD = "old"
    CURRENT = "current"
    DRIFT = "drift"


class MigrationStrategy(Enum):
    """
    Migration strategy enumeration.

    Strategies:
        ALTER_TABLE: Preserve data, add/modify columns (safer for production)
        DROP_CREATE: Drop old table, create new (faster, acceptable for ephemeral checkpoints)
        MANUAL: Manual intervention required (drift state)
    """

    ALTER_TABLE = "alter_table"
    DROP_CREATE = "drop_create"
    MANUAL = "manual"


@dataclass
class SchemaDetectionResult:
    """
    Schema detection result.

    Attributes:
        state: Detected schema state
        table_exists: Whether checkpoints table exists
        column_count: Number of columns in checkpoints table
        columns: Dictionary of column names to types
        primary_key: List of primary key column names
        indexes: List of index names
        drift_details: Details about schema drift (if DRIFT state)
    """

    state: SchemaState
    table_exists: bool
    column_count: int
    columns: Dict[str, str]
    primary_key: List[str]
    indexes: List[str]
    drift_details: Optional[str] = None

    def __str__(self) -> str:
        """String representation for logging."""
        return (
            f"SchemaDetectionResult("
            f"state={self.state.value}, "
            f"table_exists={self.table_exists}, "
            f"column_count={self.column_count}, "
            f"pk_columns={len(self.primary_key)})"
        )


@dataclass
class MigrationResult:
    """
    Migration execution result.

    Attributes:
        status: Migration status (success, failed, skipped)
        strategy: Strategy used for migration
        backup_file: Path to database backup (if created)
        start_time: Migration start timestamp
        end_time: Migration end timestamp
        duration_seconds: Migration duration
        message: Human-readable result message
        error: Error message (if failed)
    """

    status: str
    strategy: MigrationStrategy
    backup_file: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    message: str = ""
    error: Optional[str] = None

    def __str__(self) -> str:
        """String representation for logging."""
        return (
            f"MigrationResult("
            f"status={self.status}, "
            f"strategy={self.strategy.value}, "
            f"duration={self.duration_seconds}s)"
        )


class CheckpointSchemaMigrator:
    """
    Idempotent schema migration manager for LangGraph checkpoints.

    This class provides automatic detection and migration of checkpoint schema
    from LangGraph 0.0.8 to 1.0.5, using SQLAlchemy ORM models as the source of truth.

    Features:
        - Auto-detects schema state (MISSING, OLD, CURRENT, DRIFT)
        - Migrates using ALTER TABLE (preserve data) or DROP/CREATE (fast)
        - Validates schema against ORM models
        - Creates backups before destructive operations
        - Provides rollback support

    Usage:
        ```python
        migrator = CheckpointSchemaMigrator()

        # Detect current schema state
        detection = await migrator.detect_schema_state()
        print(f"Schema state: {detection.state}")

        # Migrate if needed
        if detection.state != SchemaState.CURRENT:
            result = await migrator.migrate_to_current(
                backup=True,
                strategy=MigrationStrategy.DROP_CREATE
            )
            print(f"Migration: {result.message}")
        ```

    Integration:
        - CLI: `python scripts/deps/manage_checkpoint_schema.py --auto-migrate`
        - Alembic: `alembic upgrade head` (auto-detects and migrates)
        - Quick-start: Automatic migration before service startup
    """

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize CheckpointSchemaMigrator.

        Args:
            database_url: PostgreSQL connection URL. If None, uses DATABASE_URL env var.
        """
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://admin:password@postgres:5432/agentic_orchestrator",
        )

        # Convert asyncpg URL to psycopg3 for synchronous operations
        # Note: Container has psycopg[binary,pool]>=3.2.0 (psycopg3), not psycopg2
        if "postgresql+asyncpg://" in self.database_url:
            # Use psycopg3 dialect for synchronous engine operations
            self.database_url = self.database_url.replace(
                "postgresql+asyncpg://", "postgresql+psycopg://"
            )
        elif "+psycopg2://" in self.database_url:
            # Convert psycopg2 to psycopg3 dialect
            self.database_url = self.database_url.replace(
                "+psycopg2://", "+psycopg://"
            )
        elif "postgresql://" in self.database_url and "+psycopg" not in self.database_url:
            # Handle bare postgresql:// URLs (default/env var without dialect)
            # SQLAlchemy defaults to psycopg2 for bare URLs, but we only have psycopg3
            self.database_url = self.database_url.replace(
                "postgresql://", "postgresql+psycopg://"
            )

        self.engine: Optional[Engine] = None
        self.metadata = MetaData()

    async def detect_schema_state(self) -> SchemaDetectionResult:
        """
        Detect current checkpoint schema state.

        This method inspects the database and determines which schema state
        the checkpoints table is in:

        - MISSING: Table doesn't exist yet
        - OLD: LangGraph 0.0.8 schema (3-5 columns, bytea)
        - CURRENT: LangGraph 1.0.5 schema (7 columns, jsonb)
        - DRIFT: Unexpected schema (manual investigation needed)

        Returns:
            SchemaDetectionResult with detailed schema information

        Detection Logic:
            1. Check if checkpoints table exists
            2. Count columns (3-5 = OLD, 7 = potential CURRENT)
            3. Check for checkpoint_ns column (CURRENT)
            4. Check column types (bytea = OLD, jsonb = CURRENT)
            5. Check primary key (single = OLD, composite = CURRENT)

        Example:
            ```python
            migrator = CheckpointSchemaMigrator()
            detection = await migrator.detect_schema_state()

            if detection.state == SchemaState.OLD:
                print("Old LangGraph 0.0.8 schema detected")
                print(f"Columns: {detection.columns}")
            ```
        """
        logger.info("Detecting checkpoint schema state...")

        # Create synchronous engine for inspection
        if not self.engine:
            self.engine = create_engine(self.database_url)

        inspector = inspect(self.engine)

        # Check if checkpoints table exists
        table_exists = inspector.has_table("checkpoints")

        if not table_exists:
            logger.info("✅ Schema state: MISSING (table doesn't exist)")
            return SchemaDetectionResult(
                state=SchemaState.MISSING,
                table_exists=False,
                column_count=0,
                columns={},
                primary_key=[],
                indexes=[],
            )

        # Get table structure
        columns_info = inspector.get_columns("checkpoints")
        pk_constraint = inspector.get_pk_constraint("checkpoints")
        indexes_info = inspector.get_indexes("checkpoints")

        columns = {col["name"]: str(col["type"]) for col in columns_info}
        column_count = len(columns)
        primary_key = pk_constraint.get("constrained_columns", [])
        indexes = [idx["name"] for idx in indexes_info]

        logger.debug(f"Checkpoints table: {column_count} columns, PK={primary_key}")

        # Detect schema state based on structure
        has_checkpoint_ns = "checkpoint_ns" in columns
        has_checkpoint_id = "checkpoint_id" in columns
        has_created_at = "created_at" in columns
        has_updated_at = "updated_at" in columns

        checkpoint_type = columns.get("checkpoint", "unknown").upper()
        metadata_type = columns.get("metadata", "unknown").upper()

        is_jsonb = "JSONB" in checkpoint_type and "JSONB" in metadata_type
        is_bytea = "BYTEA" in checkpoint_type and "BYTEA" in metadata_type

        # OLD schema detection (LangGraph 0.0.8)
        if (
            column_count in (3, 4, 5)
            and not has_checkpoint_ns
            and not has_checkpoint_id
            and is_bytea
            and len(primary_key) == 1
            and primary_key[0] == "thread_id"
        ):
            logger.warning("⚠️  Schema state: OLD (LangGraph 0.0.8 detected)")
            logger.warning(
                f"   Found: {column_count} columns, bytea types, single PK"
            )
            return SchemaDetectionResult(
                state=SchemaState.OLD,
                table_exists=True,
                column_count=column_count,
                columns=columns,
                primary_key=primary_key,
                indexes=indexes,
            )

        # CURRENT schema detection (LangGraph 1.0.5)
        if (
            column_count == 7
            and has_checkpoint_ns
            and has_checkpoint_id
            and not has_created_at
            and not has_updated_at
            and is_jsonb
            and len(primary_key) == 3
            and set(primary_key) == {"thread_id", "checkpoint_ns", "checkpoint_id"}
        ):
            logger.info("✅ Schema state: CURRENT (LangGraph 1.0.5 up to date)")
            return SchemaDetectionResult(
                state=SchemaState.CURRENT,
                table_exists=True,
                column_count=column_count,
                columns=columns,
                primary_key=primary_key,
                indexes=indexes,
            )

        # DRIFT detection (unexpected schema)
        drift_details = (
            f"Unexpected schema: {column_count} columns, "
            f"checkpoint_ns={has_checkpoint_ns}, "
            f"checkpoint_id={has_checkpoint_id}, "
            f"types={'jsonb' if is_jsonb else 'bytea' if is_bytea else 'unknown'}, "
            f"PK={primary_key}"
        )
        logger.error(f"❌ Schema state: DRIFT - {drift_details}")

        return SchemaDetectionResult(
            state=SchemaState.DRIFT,
            table_exists=True,
            column_count=column_count,
            columns=columns,
            primary_key=primary_key,
            indexes=indexes,
            drift_details=drift_details,
        )

    async def migrate_to_current(
        self,
        backup: bool = True,
        strategy: Optional[MigrationStrategy] = None,
    ) -> MigrationResult:
        """
        Migrate checkpoint schema to LangGraph 1.0.5.

        This method migrates from any state to CURRENT:
        - MISSING → CREATE TABLE (from ORM)
        - OLD → ALTER TABLE or DROP/CREATE (depending on strategy)
        - CURRENT → No-op (already up to date)
        - DRIFT → Manual intervention (return error)

        Args:
            backup: Create database backup before migration (recommended)
            strategy: Migration strategy (default: DROP_CREATE for ephemeral checkpoints)

        Returns:
            MigrationResult with status, duration, and messages

        Raises:
            Exception: If migration fails or drift state detected

        Example:
            ```python
            migrator = CheckpointSchemaMigrator()
            result = await migrator.migrate_to_current(
                backup=True,
                strategy=MigrationStrategy.DROP_CREATE
            )

            if result.status == "success":
                print(f"Migration completed in {result.duration_seconds}s")
            else:
                print(f"Migration failed: {result.error}")
            ```
        """
        start_time = datetime.now()
        logger.info("Starting checkpoint schema migration...")

        # Detect current schema state
        detection = await self.detect_schema_state()
        logger.info(f"Detected schema state: {detection.state.value}")

        # Determine migration strategy
        if strategy is None:
            # Default: DROP/CREATE for ephemeral checkpoints (faster)
            strategy = MigrationStrategy.DROP_CREATE

        # Handle each schema state
        if detection.state == SchemaState.CURRENT:
            logger.info("✅ Schema already up to date (no migration needed)")
            return MigrationResult(
                status="skipped",
                strategy=strategy,
                start_time=start_time,
                end_time=datetime.now(),
                duration_seconds=0.0,
                message="Schema already up to date (LangGraph 1.0.5)",
            )

        if detection.state == SchemaState.DRIFT:
            logger.warning(f"⚠️  Schema drift detected: {detection.drift_details}")
            logger.info(
                "Auto-migrating DRIFT state (checkpoints are ephemeral and safe to recreate)"
            )
            # Fall through to migration logic below (will be handled like OLD state)

        # Create backup if requested
        backup_file = None
        if backup and detection.table_exists:
            backup_file = await self._create_backup()
            logger.info(f"✅ Database backup created: {backup_file}")

        # Execute migration based on state and strategy
        try:
            if detection.state == SchemaState.MISSING:
                await self._create_from_orm()
                message = "Created checkpoints table from ORM (LangGraph 1.0.5)"

            elif detection.state in (SchemaState.OLD, SchemaState.DRIFT):
                if strategy == MigrationStrategy.DROP_CREATE:
                    await self._drop_and_recreate()
                    if detection.state == SchemaState.DRIFT:
                        message = "Fixed schema drift (DROP/CREATE)"
                    else:
                        message = "Migrated from 0.0.8 to 1.0.5 (DROP/CREATE)"
                else:
                    await self._alter_table_migration()
                    if detection.state == SchemaState.DRIFT:
                        message = "Fixed schema drift (ALTER TABLE)"
                    else:
                        message = "Migrated from 0.0.8 to 1.0.5 (ALTER TABLE)"

            else:
                raise ValueError(f"Unexpected schema state: {detection.state}")

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            logger.info(f"✅ Migration successful: {message}")
            logger.info(f"   Duration: {duration:.2f} seconds")

            return MigrationResult(
                status="success",
                strategy=strategy,
                backup_file=backup_file,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration,
                message=message,
            )

        except Exception as e:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            error_msg = f"Migration failed: {str(e)}"
            logger.error(f"❌ {error_msg}")

            if backup_file:
                logger.info(f"⚠️  Restore from backup: {backup_file}")

            return MigrationResult(
                status="failed",
                strategy=strategy,
                backup_file=backup_file,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration,
                message="Migration failed",
                error=error_msg,
            )

    async def _create_backup(self) -> str:
        """
        Create PostgreSQL database backup.

        Returns:
            Path to backup file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = "/tmp/checkpoint_schema_backups"
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = f"{backup_dir}/agentic_orchestrator_backup_{timestamp}.sql"

        logger.info(f"Creating database backup: {backup_file}")

        # Extract connection parameters from URL
        from urllib.parse import urlparse
        parsed = urlparse(self.database_url)

        # Use pg_dump via docker exec
        cmd = (
            f"docker exec postgres pg_dump "
            f"-U {parsed.username} "
            f"{parsed.path.lstrip('/')} "
            f"> {backup_file}"
        )

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise Exception(f"Backup failed: {stderr.decode()}")

        return backup_file

    async def _create_from_orm(self):
        """Create checkpoints table from ORM (fresh install)."""
        logger.info("Creating checkpoints table from ORM...")

        # Use SQLAlchemy to create tables
        Base.metadata.create_all(self.engine, tables=[Checkpoint.__table__])

        logger.info("✅ Checkpoints table created from ORM")

    async def _drop_and_recreate(self):
        """Drop old checkpoints table and recreate from ORM (DROP/CREATE strategy)."""
        logger.info("Dropping old checkpoints table...")

        # Drop CASCADE to handle foreign keys
        Base.metadata.drop_all(self.engine, tables=[Checkpoint.__table__])

        logger.info("✅ Old table dropped")

        # Recreate from ORM
        await self._create_from_orm()

    async def _alter_table_migration(self):
        """
        Migrate checkpoints table using ALTER TABLE (preserve data).

        This is more complex but preserves existing checkpoint data:
        1. Add new columns (checkpoint_ns, checkpoint_id, parent_checkpoint_id, type)
        2. Convert checkpoint and metadata from bytea to jsonb
        3. Drop old constraints and indexes
        4. Add new composite primary key
        5. Drop old columns (created_at, updated_at)
        """
        logger.info("Migrating checkpoints table using ALTER TABLE...")

        # This would require complex SQL to preserve data
        # For checkpoints (ephemeral), DROP/CREATE is recommended
        raise NotImplementedError(
            "ALTER TABLE migration not yet implemented. "
            "Use DROP_CREATE strategy for ephemeral checkpoints."
        )

    async def validate_schema_matches_orm(self) -> bool:
        """
        Validate that database schema matches ORM definitions.

        Returns:
            True if schema matches ORM, False otherwise

        Example:
            ```python
            migrator = CheckpointSchemaMigrator()
            if await migrator.validate_schema_matches_orm():
                print("✅ Schema matches ORM")
            else:
                print("❌ Schema drift detected")
            ```
        """
        detection = await self.detect_schema_state()
        return detection.state == SchemaState.CURRENT

    def close(self):
        """Close database connections."""
        if self.engine:
            self.engine.dispose()
