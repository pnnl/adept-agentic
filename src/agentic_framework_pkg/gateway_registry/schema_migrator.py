"""
Gateway Registry Schema Migrator

Idempotent schema management for the gateway registry gateways table.

This module provides automatic schema validation and migration using SQLAlchemy
ORM models as the single source of truth. Since gateway registration data is
ephemeral (gateways re-register on startup), this uses a DROP/CREATE strategy
when schema drift is detected.

Features:
- Detects schema drift (column mismatch, type changes)
- Recreates table on schema drift (safe for ephemeral data)
- Validates schema matches ORM definitions
- Runs automatically on service startup

Usage:
    ```python
    from .schema_migrator import migrate_schema_if_needed

    # In database.py init_db()
    await migrate_schema_if_needed(engine, Base)
    ```
"""

import os
from typing import Dict, Set
from sqlalchemy import inspect, MetaData
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import declarative_base
from ..logger_config import get_logger

logger = get_logger(__name__)


async def detect_schema_drift(engine: AsyncEngine, base: declarative_base) -> bool:
    """
    Detect if database schema differs from ORM model definitions.

    Args:
        engine: Async SQLAlchemy engine
        base: Declarative base with ORM models

    Returns:
        True if schema drift detected, False if schema matches ORM

    Detection Logic:
        1. Check if table exists
        2. Compare column names between DB and ORM
        3. Compare column types
        4. Compare primary key constraints
    """
    logger.info("Checking for gateway registry schema drift...")

    # Get ORM model metadata
    orm_tables = base.metadata.tables

    # Use sync connection for inspection (inspect doesn't support async)
    def _check_drift(connection):
        inspector = inspect(connection)

        # Check each ORM table
        for table_name, orm_table in orm_tables.items():
            # Check if table exists
            if not inspector.has_table(table_name):
                logger.info(f"✅ Table '{table_name}' does not exist (will be created)")
                return True  # Not drift, but needs creation

            # Get DB column structure
            db_columns_info = inspector.get_columns(table_name)
            db_columns = {col["name"]: str(col["type"]) for col in db_columns_info}
            db_column_names = set(db_columns.keys())

            # Get ORM column structure
            orm_columns = {col.name: str(col.type) for col in orm_table.columns}
            orm_column_names = set(orm_columns.keys())

            # Check for column name mismatches
            missing_in_db = orm_column_names - db_column_names
            extra_in_db = db_column_names - orm_column_names

            if missing_in_db or extra_in_db:
                logger.warning(f"⚠️  Schema drift detected in table '{table_name}':")
                if missing_in_db:
                    logger.warning(f"   Missing columns in DB: {missing_in_db}")
                if extra_in_db:
                    logger.warning(f"   Extra columns in DB: {extra_in_db}")
                return True

            # Check for column type mismatches (basic comparison)
            for col_name in orm_column_names:
                orm_type = str(orm_columns[col_name]).upper()
                db_type = str(db_columns[col_name]).upper()

                # Normalize type names for comparison (e.g., VARCHAR(255) vs VARCHAR)
                orm_type_base = orm_type.split("(")[0]
                db_type_base = db_type.split("(")[0]

                # PostgreSQL type equivalence mappings
                # SQLAlchemy DateTime(timezone=True) -> PostgreSQL TIMESTAMP WITH TIME ZONE
                pg_type_equivalents = {
                    ("DATETIME", "TIMESTAMP"): True,
                    ("TIMESTAMP", "DATETIME"): True,
                }

                types_match = (
                    orm_type_base == db_type_base
                    or pg_type_equivalents.get((orm_type_base, db_type_base), False)
                )

                if not types_match:
                    logger.warning(
                        f"⚠️  Type mismatch for column '{table_name}.{col_name}': "
                        f"ORM={orm_type} vs DB={db_type}"
                    )
                    return True

            # Check primary key constraints
            db_pk = inspector.get_pk_constraint(table_name)
            db_pk_columns = set(db_pk.get("constrained_columns", []))
            orm_pk_columns = {col.name for col in orm_table.primary_key.columns}

            if db_pk_columns != orm_pk_columns:
                logger.warning(
                    f"⚠️  Primary key mismatch in table '{table_name}': "
                    f"ORM={orm_pk_columns} vs DB={db_pk_columns}"
                )
                return True

        logger.info("✅ No schema drift detected - database matches ORM")
        return False

    # Run sync check in async context
    async with engine.begin() as conn:
        drift_detected = await conn.run_sync(_check_drift)

    return drift_detected


async def recreate_tables(engine: AsyncEngine, base: declarative_base):
    """
    Recreate all tables from ORM metadata (DROP/CREATE).

    This is safe for gateway registry since registration data is ephemeral -
    gateways automatically re-register on startup and during health check cycles.

    Args:
        engine: Async SQLAlchemy engine
        base: Declarative base with ORM models
    """
    logger.info("Recreating gateway registry tables from ORM...")

    async with engine.begin() as conn:
        # Drop all tables
        await conn.run_sync(base.metadata.drop_all)
        logger.info("✅ Dropped existing tables")

        # Recreate from ORM
        await conn.run_sync(base.metadata.create_all)
        logger.info("✅ Created tables from ORM metadata")

    logger.info("✅ Schema recreated successfully")


async def migrate_schema_if_needed(engine: AsyncEngine, base: declarative_base):
    """
    Idempotent schema migration - recreate tables only if drift detected.

    This function is called on service startup and ensures the database schema
    matches the ORM model definitions. If drift is detected, it recreates the
    tables using DROP/CREATE strategy.

    Args:
        engine: Async SQLAlchemy engine
        base: Declarative base with ORM models

    Behavior:
        - No drift: No-op (idempotent restarts)
        - Schema drift: Recreate tables (safe for ephemeral data)
        - Missing tables: Create from ORM
    """
    logger.info("Running gateway registry schema migration check...")

    drift_detected = await detect_schema_drift(engine, base)

    if drift_detected:
        logger.warning(
            "Schema drift detected - recreating tables to match ORM. "
            "This is safe because gateway registration data is ephemeral "
            "(gateways re-register automatically)."
        )
        await recreate_tables(engine, base)
        logger.info("✅ Gateway registry schema is now current")
    else:
        logger.info("✅ Gateway registry schema is current (no migration needed)")
