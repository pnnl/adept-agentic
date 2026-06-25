"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """Health check for load balancers and ChatGPT Actions validation."""
    return {"status": "ok", "service": "adept-chatgpt-connector"}
