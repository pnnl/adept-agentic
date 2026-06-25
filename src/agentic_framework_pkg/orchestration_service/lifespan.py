"""
This module defines the lifespan manager for the Orchestration Service FastAPI app.

It handles essential startup logic to ensure that the service's dependencies,
such as the database and the tool manager, are properly initialized before the
application starts accepting requests.

Architectural Role:
-   **Initialization Orchestrator:** Ensures that critical, asynchronous setup
    tasks are completed in the correct order during application startup.
-   **Database Schema:** It calls `init_db` to create the necessary PostgreSQL
    tables (`checkpoints`, `multi_agent_sessions`) if they don't already exist.
-   **Tool Loading:** It calls `tool_manager.initialize()` to connect to Redis
    and load all dynamic tool configurations into memory.
"""

import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import text

from ..core.mcp_tool_discovery import mcp_discovery
from ..core.service_credentials_manager import credentials_manager
from ..logger_config import get_logger
from .external_tool_manager import tool_manager
from .hybrid_orchestration import hybrid_service
from .persistence import init_db
from .persistence.checkpointing import get_async_engine

logger = get_logger(__name__)


async def run_alembic_migrations_with_lock():
    """
    Run Alembic migrations with PostgreSQL advisory lock for multi-pod safety.

    Uses advisory lock to ensure only one pod runs migrations in K8s.
    Safe for single-container deployments (Docker Compose, single VM).

    Returns:
        bool: True if migrations ran, False if locked (another pod running)
    """
    MIGRATION_LOCK_ID = 987654321  # Arbitrary but consistent

    logger.info("Attempting to acquire migration lock...")
    engine = await get_async_engine()

    try:
        async with engine.begin() as conn:
            # Try to acquire advisory lock (non-blocking)
            result = await conn.execute(
                text(f"SELECT pg_try_advisory_lock({MIGRATION_LOCK_ID})")
            )
            lock_acquired = result.scalar()

            if not lock_acquired:
                logger.info("⏳ Migration lock held by another pod, skipping")
                return False

            logger.info("✅ Migration lock acquired, running Alembic...")

            # Find alembic.ini (Docker: /app/scripts/migrations, Local: scripts/migrations)
            alembic_dir = Path("/app/scripts/migrations")
            if not alembic_dir.exists():
                alembic_dir = Path("scripts/migrations")

            if not (alembic_dir / "alembic.ini").exists():
                raise FileNotFoundError(f"alembic.ini not found at {alembic_dir}")

            # Run alembic upgrade head
            result = subprocess.run(
                ["alembic", "upgrade", "head"],
                cwd=str(alembic_dir),
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )

            if result.returncode == 0:
                logger.info("✅ Alembic migrations completed successfully")
                logger.info(f"Output:\n{result.stdout}")
                return True
            else:
                logger.error(f"❌ Alembic failed: {result.stderr}")
                raise Exception(f"Alembic migration failed: {result.stderr}")

    except subprocess.TimeoutExpired:
        logger.error("❌ Alembic timed out after 120 seconds")
        raise
    except Exception as e:
        logger.error(f"❌ Migration error: {e}", exc_info=True)
        raise
    finally:
        # Release advisory lock (auto-releases on connection close)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_ID})"))
                logger.info("Migration lock released")
        except Exception as e:
            logger.warning(f"Failed to release lock (may auto-release): {e}")


async def check_and_bootstrap_langfuse_credentials():
    """
    Check if Langfuse credentials exist and attempt bootstrap if missing.

    This implements the healthcheck-based approach:
    - Check if observability is configured for Langfuse
    - Check if credentials exist
    - Attempt bootstrap if missing
    - Continue without observability if bootstrap fails
    """
    # Check if observability is configured for Langfuse
    observability_backend = os.getenv("OBSERVABILITY_BACKEND", "none")

    if observability_backend != "langfuse":
        logger.info(
            f"Observability backend is '{observability_backend}', skipping Langfuse credential check"
        )
        return

    logger.info("Checking Langfuse credentials for observability...")

    # Check if credentials exist
    langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if langfuse_public_key and langfuse_secret_key:
        logger.info("✅ Langfuse credentials found, observability enabled")

        # Validate credentials through the observability factory
        try:
            # Try to use the observability factory to validate
            from agentic_framework_pkg.core.observability import SmartLogger

            test_logger = SmartLogger("credential_test", enable_tracing=True)
            if test_logger.langfuse:
                logger.info(
                    "✅ Observability factory initialized successfully with Langfuse"
                )
            else:
                logger.warning(
                    "Observability factory initialized but Langfuse client not available"
                )
        except ImportError:
            logger.warning(
                "Observability factory not available, continuing without tracing"
            )
        except Exception as e:
            logger.warning(f"Observability factory initialization failed: {e}")
            logger.warning("Continuing with standard logging only")

        return

    # Credentials missing - attempt bootstrap
    logger.warning("⚠️  Langfuse credentials not found, attempting bootstrap...")

    try:
        # Find the bootstrap script
        script_path = Path("/app/scripts/langfuse/bootstrap_langfuse_credentials.py")
        if not script_path.exists():
            # Try relative path for local development
            script_path = Path("scripts/langfuse/bootstrap_langfuse_credentials.py")

        if not script_path.exists():
            logger.error(f"Bootstrap script not found at {script_path}")
            raise FileNotFoundError(f"Bootstrap script not found")

        # Run the bootstrap script
        logger.info(f"Running bootstrap script: {script_path}")
        result = subprocess.run(
            ["python", str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
            env=os.environ.copy(),  # Pass current environment
        )

        if result.returncode == 0:
            logger.info("✅ Bootstrap completed successfully")
            logger.info(f"Bootstrap output: {result.stdout}")

            # Reload environment variables
            load_dotenv(override=True)

            # Verify credentials now exist
            langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
            langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")

            if langfuse_public_key and langfuse_secret_key:
                logger.info("✅ Langfuse credentials loaded after bootstrap")
                logger.info(f"Public key: {langfuse_public_key}")
            else:
                raise Exception("Credentials not found after bootstrap")

        else:
            logger.error(f"Bootstrap failed with return code {result.returncode}")
            logger.error(f"Error output: {result.stderr}")
            raise Exception(f"Bootstrap script failed: {result.stderr}")

    except subprocess.TimeoutExpired:
        logger.error("Bootstrap script timed out after 30 seconds")
        # Fall through to disable observability

    except Exception as e:
        logger.error(f"Failed to bootstrap Langfuse credentials: {e}")
        # Fall through to disable observability

    # Bootstrap failed - disable observability for this session
    logger.warning("⚠️  Disabling observability due to missing credentials")
    logger.warning("To enable observability, run: make langfuse-bootstrap")
    os.environ["OBSERVABILITY_BACKEND"] = "none"

    # Log instructions for manual bootstrap
    logger.info("Manual bootstrap instructions:")
    logger.info("1. Run: make langfuse-bootstrap")
    logger.info("2. Restart the orchestration service")
    logger.info("3. Or set OBSERVABILITY_BACKEND=none to disable this check")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Asynchronous context manager for the FastAPI application's lifespan.

    Startup Order:
    1. Run Alembic migrations (creates/updates checkpoint tables)
    2. Initialize database (creates other tables via ORM)
    3. Initialize tool manager, credentials manager, hybrid service

    Args:
        app (FastAPI): The FastAPI application instance.
    """
    logger.info("Orchestration Service is starting up...")

    # STEP 1: Run database migrations (deployment-agnostic)
    try:
        migration_success = await run_alembic_migrations_with_lock()
        if migration_success:
            logger.info("Schema migrations applied successfully")
        else:
            logger.info("Schema migrations skipped (handled by another pod)")
    except Exception as e:
        logger.error(f"Migration failed during startup: {e}")
        logger.error("Service continuing but schema may be outdated")
        # Continue startup - don't block service if migrations fail

    # STEP 2: Initialize database (creates non-checkpoint tables)
    await init_db()

    # STEP 3: Initialize tool manager
    await tool_manager.initialize()

    # Initialize service credentials manager for auth resilience
    creds_initialized = await credentials_manager.initialize()
    if not creds_initialized:
        logger.warning(
            "Service credentials manager failed to initialize - some services may have auth issues"
        )

    # Warm up MCP tool discovery cache
    try:
        discovered_tools = await mcp_discovery.discover_all_tools()
        logger.info(
            f"Pre-warmed MCP tool discovery: {len(discovered_tools)} tools cached"
        )
    except Exception as e:
        logger.warning(f"MCP tool discovery warm-up failed: {e}")

    await hybrid_service.start()
    logger.info("Hybrid orchestration service started with agent pool management")

    # Check and bootstrap Langfuse credentials if needed (healthcheck-based approach)
    await check_and_bootstrap_langfuse_credentials()

    yield
    logger.info("Orchestration Service is shutting down...")
    await hybrid_service.stop()
