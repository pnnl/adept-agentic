"""FastAPI application factory for the ChatGPT Actions connector.

Creates a FastAPI app with:
- AdeptFacade (core) for all ADEPT interactions
- ChatGPTImageRenderer for image proxy URLs
- BearerTokenMiddleware for Keycloak token validation
- REST routes for chat, sessions, files, tools, images, and OAuth2 auth

Usage:
    # Development
    uvicorn adept_connectors.connectors.chatgpt.app:create_app --factory --port 8090

    # Or programmatically
    from adept_connectors.connectors.chatgpt.app import create_app
    app = create_app()
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from ...core.auth import AuthManager
from ...core.clients.base import BaseAdeptClient
from ...core.facade import AdeptFacade
from ...core.session import SessionManager
from .config import ChatGPTConnectorConfig
from .middleware.auth import BearerTokenMiddleware
from .rendering import ChatGPTImageRenderer, ImageCache
from .routes import create_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and tear down shared resources."""
    config = app.state.config

    # Core components
    auth = AuthManager(config)
    session_mgr = SessionManager(persist=config.session_persistence)
    client = BaseAdeptClient(config, auth, client_source="chatgpt-connector")

    # Image cache + renderer
    image_cache = ImageCache(
        max_size=config.chatgpt_max_cached_images,
        ttl_seconds=config.chatgpt_image_ttl,
    )
    renderer = ChatGPTImageRenderer(
        cache=image_cache,
        base_url=config.public_base_url,
    )

    # Facade
    facade = AdeptFacade(
        config=config,
        auth=auth,
        client=client,
        session_mgr=session_mgr,
        renderer=renderer,
    )

    # Attach to app state
    app.state.facade = facade
    app.state.image_cache = image_cache
    app.state.renderer = renderer

    await client._ensure_client()
    logger.info(
        "ChatGPT connector started — %s auth, target: %s, image proxy: %s",
        config.auth_method.value,
        config.base_url,
        config.public_base_url,
    )

    try:
        yield
    finally:
        await facade.close()
        logger.info("ChatGPT connector stopped")


def create_app(config: ChatGPTConnectorConfig | None = None) -> FastAPI:
    """Create the ChatGPT Actions FastAPI application.

    Args:
        config: Optional config override. If None, loads from env vars.

    Returns:
        Configured FastAPI application.
    """
    if config is None:
        config = ChatGPTConnectorConfig()

    app = FastAPI(
        title="ADEPT ChatGPT Connector",
        description=(
            "REST API bridge from ChatGPT custom GPTs to the ADEPT "
            "Agentic Discovery and Exploration Platform for Tools. "
            "Provides chat, file upload, tool discovery, and session management."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store config before lifespan runs
    app.state.config = config

    # Auth middleware
    app.add_middleware(
        BearerTokenMiddleware,
        keycloak_url=config.keycloak_url or "http://localhost:8180",
        realm=config.keycloak_realm,
        verify_ssl=config.verify_ssl,
    )

    # Routes
    app.include_router(create_router())

    return app
