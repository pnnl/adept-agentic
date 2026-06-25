"""
This module provides the database connection and session management for the
Gateway Registry service, using SQLAlchemy's asynchronous features.
"""
import os
import asyncio
from urllib.parse import urlparse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from ..logger_config import get_logger
from .schema_migrator import migrate_schema_if_needed

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://admin:password@localhost:5432/agentic_registry")
logger.info(f"Gateway Registry DATABASE_URL configured: {DATABASE_URL}")

# Declare engine and sessionmaker as global, but initialize them as None.
# They will be initialized once in `init_db`.
engine = None
AsyncSessionLocal = None
Base = declarative_base()

async def check_postgres_availability(host, port, retries=5, delay=5):
    """Checks if the PostgreSQL server is available."""
    logger.info(f"Checking for PostgreSQL availability at {host}:{port}...")
    for i in range(retries):
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
            writer.close()
            await writer.wait_closed()
            logger.info(f"PostgreSQL is available at {host}:{port}.")
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
            logger.warning(f"PostgreSQL not available at {host}:{port} (Attempt {i+1}/{retries}): {e}. Retrying in {delay} seconds...")
            await asyncio.sleep(delay)
    logger.error(f"Failed to connect to PostgreSQL at {host}:{port} after {retries} retries.")
    return False

async def get_db():
    """
    FastAPI dependency that provides an asynchronous database session.
    """
    if AsyncSessionLocal is None:
        raise RuntimeError("Database is not initialized. Call init_db during application startup.")
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    """
    Checks for database availability, initializes the SQLAlchemy engine,
    and creates all tables defined by the Base metadata.
    """
    global engine, AsyncSessionLocal

    # Only initialize if the engine hasn't been created yet.
    if engine is None:
        parsed_url = urlparse(DATABASE_URL)
        host = parsed_url.hostname
        port = parsed_url.port

        if not await check_postgres_availability(host, port):
            raise ConnectionError(f"Could not connect to PostgreSQL at {host}:{port} after multiple retries.")

        logger.info("PostgreSQL is available. Initializing SQLAlchemy engine...")
        logger.info(f"DATABASE_URL configured: {DATABASE_URL}")
        # Configure connection pool with better settings for async operations
        engine = create_async_engine(
            DATABASE_URL, 
            echo=True,
            pool_size=20,  # Increased from default 5
            max_overflow=10,  # Allow more overflow connections
            pool_timeout=30,  # Wait up to 30 seconds for a connection
            pool_recycle=3600,  # Recycle connections after 1 hour
            pool_pre_ping=True  # Test connections before using them
        )
        AsyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession)

    # Run idempotent schema migration (ORM as source of truth)
    # This will create tables if missing, or recreate if schema drift detected.
    # Safe for gateway registry since registration data is ephemeral.
    await migrate_schema_if_needed(engine, Base)
    logger.info("Database schema migration completed.")