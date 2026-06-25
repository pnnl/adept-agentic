"""
Main application file for the Gateway Registry Service.

This module initializes the FastAPI application for the registry service and
defines all of its API endpoints for managing gateway registrations.

Architectural Role:
-   **Service Discovery:** This service acts as the central, authoritative
    source of truth for discovering agent gateways in the mesh.
-   **Lifecycle Management:** It provides endpoints for gateways to self-register
    on startup and for health checkers to post status updates.
-   **Security:** Access to the registry is protected by Keycloak. Gateways must
    present a valid service-to-service (S2S) JWT to register, and clients
    (like the Management UI) must have the appropriate roles to view or manage
    registrations.
-   **Persistence:** All gateway registration data is persisted in a dedicated
    PostgreSQL database.
"""
import uvicorn
import os
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

# Reverted: from .routers import services as services_router
from . import models, schemas
from .database import engine, get_db, init_db
from .auth import require_role, require_any_role
from ..logger_config import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="Gateway Registry Service",
    description="A central service for managing the registration and discovery of Agent Gateways.",
    version="1.0.0",
)

@app.on_event("startup")
async def on_startup():
    """Initializes the database schema on application startup."""
    logger.info("Initializing database...")
    await init_db()
    if schemas.ALLOWED_PEER_NETWORKS:
        logger.info(f"[GATEWAY_REGISTRY] ALLOWED_PEER_CIDRS: {[str(n) for n in schemas.ALLOWED_PEER_NETWORKS]}")
    else:
        logger.warning("[GATEWAY_REGISTRY] ALLOWED_PEER_CIDRS not configured - private IP peer registration will be blocked")

@app.post("/v1/gateways", response_model=schemas.Gateway, dependencies=[Depends(require_any_role(["admin", "gateway-service"]))])
async def create_or_update_gateway(gateway: schemas.GatewayCreate, db: AsyncSession = Depends(get_db)):
    """
    Creates a new gateway registration or updates an existing one (upsert).
    """
    logger.info(f"[GATEWAY_REGISTRY] Handling POST /v1/gateways for alias: {gateway.alias}")
    # This is an upsert operation
    db_gateway = await db.get(models.Gateway, gateway.alias)
    if db_gateway:
        db_gateway.public_url = gateway.public_url
        db_gateway.internal_url = gateway.internal_url
        db_gateway.capabilities = gateway.capabilities
    else:
        db_gateway = models.Gateway(**gateway.dict())
        db.add(db_gateway)
    await db.commit()
    await db.refresh(db_gateway)
    return db_gateway

@app.get("/v1/gateways/", response_model=List[schemas.Gateway], dependencies=[Depends(require_any_role(["admin", "gateway-service"]))])
async def list_gateways(db: AsyncSession = Depends(get_db)):
    """Lists all registered gateways."""
    logger.info("[GATEWAY_REGISTRY] Handling GET /v1/gateways")
    result = await db.execute(select(models.Gateway))
    return result.scalars().all()

@app.get("/v1/gateways/{alias}", response_model=schemas.Gateway, dependencies=[Depends(require_any_role(["admin", "gateway-service"]))])
async def get_gateway(alias: str, db: AsyncSession = Depends(get_db)):
    """Retrieves a specific gateway registration by its alias."""
    logger.info(f"[GATEWAY_REGISTRY] Handling GET /v1/gateways/{alias}")
    db_gateway = await db.get(models.Gateway, alias)
    if db_gateway is None:
        raise HTTPException(status_code=404, detail="Gateway not found")
    return db_gateway

@app.delete("/v1/gateways/{alias}", status_code=204, dependencies=[Depends(require_role("admin"))])
async def delete_gateway(alias: str, db: AsyncSession = Depends(get_db)):
    """Deletes a gateway registration by its alias."""
    logger.info(f"[GATEWAY_REGISTRY] Handling DELETE /v1/gateways/{alias}")
    db_gateway = await db.get(models.Gateway, alias)
    if db_gateway:
        await db.delete(db_gateway)
        await db.commit()
    return

@app.post("/v1/gateways/{alias}/health", dependencies=[Depends(require_any_role(["admin", "gateway-service"]))])
async def update_health_status(alias: str, health_update: schemas.GatewayHealthUpdate, db: AsyncSession = Depends(get_db)):
    """Updates the health status of a specific gateway."""
    logger.info(f"[GATEWAY_REGISTRY] Handling POST /v1/gateways/{alias}/health")
    db_gateway = await db.get(models.Gateway, alias)
    if db_gateway is None:
        raise HTTPException(status_code=404, detail="Gateway not found")
    db_gateway.health_status = health_update.status
    await db.commit()
    return {"status": "ok"}



@app.get("/health", summary="Health Check")
async def health_check():
    """Provides a simple health check endpoint for monitoring."""
    return {"status": "ok"}

def start_server_cli():
    """CLI entry point to start the Gateway Registry server."""
    port = int(os.getenv("GATEWAY_REGISTRY_PORT", "8086"))
    host = os.getenv("GATEWAY_REGISTRY_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    start_server_cli()
