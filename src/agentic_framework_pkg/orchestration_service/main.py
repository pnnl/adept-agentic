"""
Main entry point for running the Orchestration Service.

This script provides a CLI command to initialize the database and start the
Uvicorn server for the orchestration service application.
"""
import uvicorn
import os
import asyncio
from .app import app
from .persistence import init_db
from ..logger_config import get_logger
from ..core.observability_factory import ObservabilityFactory

logger = get_logger(__name__)

async def main():
    """Initializes the database and starts the Uvicorn server."""
    logger.info("Initializing Orchestration Service database...")
    await init_db()

    # Initialize observability backend (abstracted via ObservabilityFactory)
    logger.info("Initializing observability backend via ObservabilityFactory...")
    try:
        obs_factory = ObservabilityFactory()
        # Get provider (LangFuse, LangSmith, or NoOp based on OBSERVABILITY_BACKEND env var)
        provider = obs_factory.get_provider()
        logger.info(f"✅ Observability backend initialized: {type(provider).__name__}")

        # For LangFuse backend with @observe decorator support, the global client
        # is initialized automatically via environment variables (LANGFUSE_PUBLIC_KEY, etc.)
        # No direct LangFuse imports needed - ObservabilityFactory handles the abstraction
    except Exception as e:
        logger.warning(f"Failed to initialize observability backend: {e}")

    port = int(os.getenv("ORCHESTRATION_SERVICE_PORT", "8084"))
    host = os.getenv("ORCHESTRATION_SERVICE_HOST", "0.0.0.0")
    num_workers = int(os.getenv("ORCHESTRATION_UVICORN_WORKERS", "4"))

    logger.info(f"Starting Orchestration Service on {host}:{port} with {num_workers} worker(s)")

    config = uvicorn.Config(app, host=host, port=port, log_level="info", workers=num_workers)
    server = uvicorn.Server(config)
    await server.serve()

def start_orchestration_service_cli():
    """CLI entry point to start the Orchestration Service."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Orchestration Service shutting down.")
    except Exception as e:
        logger.critical(f"Orchestration Service failed: {e}", exc_info=True)

if __name__ == "__main__":
    start_orchestration_service_cli()