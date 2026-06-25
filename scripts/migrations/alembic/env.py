"""
Alembic Environment Configuration

This module configures Alembic to use SQLAlchemy ORM models as the source of truth
for database schema migrations. It supports both online (async) and offline migration modes.

Key Features:
- Async PostgreSQL connection via asyncpg
- ORM model imports for autogenerate support
- Environment variable override for DATABASE_URL
- Offline SQL script generation support
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import ORM Base and all models for autogenerate detection
from agentic_framework_pkg.orchestration_service.models.base import Base
from agentic_framework_pkg.orchestration_service.models.session_models import (
    UserSession,
    SessionMessage,
    ToolOutput,
    ContextArchive,
)

# Import checkpoint models for autogenerate detection
from agentic_framework_pkg.orchestration_service.models.checkpoint_schema import (
    Checkpoint,
    CheckpointBlob,
    CheckpointMigration,
    CheckpointWrite,
)

# This is the Alembic Config object, which provides access to the .ini file values
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata

# Override database URL from environment variable if present
if os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine, though an
    Engine is acceptable here as well. By skipping the Engine creation we don't
    even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    Run migrations with an established database connection.

    Args:
        connection: Active SQLAlchemy connection
    """
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations in 'online' mode with async PostgreSQL connection.

    In this scenario we need to create an async Engine and associate a
    connection with the context.
    """
    # Convert SQLAlchemy-style URL format if needed
    url = config.get_main_option("sqlalchemy.url")
    if url and "+asyncpg://" not in url and "postgresql://" in url:
        # Convert postgresql:// to postgresql+asyncpg:// for async support
        url = url.replace("postgresql://", "postgresql+asyncpg://")
        config.set_main_option("sqlalchemy.url", url)

    # Create async engine
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode (default).

    Uses async engine for PostgreSQL connection via asyncpg driver.
    """
    asyncio.run(run_async_migrations())


# Determine which mode to run in
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
