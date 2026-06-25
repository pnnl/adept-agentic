"""ChatGPT connector route aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from . import auth, chat, files, health, images, sessions, tools


def create_router() -> APIRouter:
    """Create the aggregated API router with all ChatGPT connector routes."""
    router = APIRouter()
    router.include_router(health.router, tags=["health"])
    router.include_router(auth.router, prefix="/auth", tags=["auth"])
    router.include_router(chat.router, prefix="/v1", tags=["chat"])
    router.include_router(sessions.router, prefix="/v1", tags=["sessions"])
    router.include_router(files.router, prefix="/v1", tags=["files"])
    router.include_router(tools.router, prefix="/v1", tags=["tools"])
    router.include_router(images.router, prefix="/v1", tags=["images"])
    return router
