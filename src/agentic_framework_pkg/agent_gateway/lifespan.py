"""
This module defines the lifespan manager for the Agent Gateway FastAPI application.

The lifespan manager handles logic that needs to run on application startup
and shutdown, such as initializing background tasks or performing service
registration.

Architectural Role:
-   **Startup Logic:** On startup, it initiates the `MeshHealthChecker` to begin
    periodically probing other gateways. It also triggers the gateway's
    self-registration process with the `GatewayRegistry` service.
-   **Shutdown Logic:** On shutdown, it gracefully stops the background health
    checker task.
"""
import os
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .mesh_health_checker import health_checker
from .registration import register_gateway_with_registry
from ..logger_config import get_logger

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Asynchronous context manager for the FastAPI application's lifespan.

    Args:
        app (FastAPI): The FastAPI application instance.
    """
    # --- Code to run on startup ---
    logger.info("Agent Gateway is starting up...")

    # Log A2A JWKS federation config
    from .auth import A2A_TRUSTED_PEER_JWKS_URLS
    if A2A_TRUSTED_PEER_JWKS_URLS:
        logger.info(f"[A2A_FEDERATION] Trusted peer JWKS endpoints: {A2A_TRUSTED_PEER_JWKS_URLS}")
    else:
        logger.info("[A2A_FEDERATION] No trusted peer JWKS endpoints configured (A2A_TRUSTED_PEER_JWKS_URLS not set)")

    # Start the background health checker
    await health_checker.start()

    # --- Gateway Self-Registration via Registry Service ---
    logger.info("LIFESPAN: Initiating gateway self-registration.")
    try:
        await register_gateway_with_registry()
        logger.info("LIFESPAN: Gateway self-registration process completed (or will retry via health checker if registry unavailable).")
    except Exception as e:
        logger.warning(f"Gateway self-registration encountered an unexpected error on startup: {e}", exc_info=True)
        logger.info("LIFESPAN: Health checker will retry registration on next cycle.")

    yield
    # --- Code to run on shutdown ---
    await health_checker.stop()
    logger.info("Agent Gateway is shutting down...")