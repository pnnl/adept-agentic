"""
Main application file for the Agent Gateway.

This module initializes the FastAPI application, configures CORS middleware,
and mounts all the necessary routers for the three-tier architecture.

Architectural Role:
- Tier 1 (Ingress): This service acts as the primary, user-facing entry point.
- Authentication: It is responsible for validating end-user JWTs via Keycloak.
- Secure Proxy: It securely proxies validated requests to the orchestration_service,
  forwarding the original user's JWT in a secure header.
- A2A Communication: It mounts the A2A (Agent-to-Agent) sub-application to handle
  secure, standardized communication with other gateways in the mesh.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables from .env file at the very beginning
load_dotenv()

from .lifespan import lifespan
from .routers.v1 import chat, models, assistants, threads, files, embeddings, gateways, runs, files_static, responses, tools, knowledge_bases, agui
from .routers import management, mcp
from .multi_agent.a2a.main import create_a2a_app

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Agent Gateway",
    description="A unified, multi-protocol entry point supporting OpenAI API and Model Context Protocol (MCP) for interacting with various agentic framework configurations.",
    version="1.0.0",
    lifespan=lifespan
)

# --- CORS Configuration ---
origins = [
    "http://localhost", "http://localhost:3000", "http://localhost:8080", "http://localhost:8081",
    "http://localhost:8083", "http://localhost:8902", "http://127.0.0.1", "http://127.0.0.1:8902",
    "http://127.0.0.1:3000", "http://127.0.0.1:8080", "http://127.0.0.1:8081", "http://127.0.0.1:8082",
    "http://host.docker.internal", "http://host.docker.internal:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Mount the A2A Application ---
a2a_app = create_a2a_app()
app.mount("/a2a", a2a_app)

# --- Include OpenAI-Compatible Routers (Version 1) ---
v1_router = FastAPI()
v1_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
v1_router.include_router(models.router, prefix="/models", tags=["Models"])
v1_router.include_router(assistants.router, prefix="/assistants", tags=["Assistants"])
v1_router.include_router(threads.router, prefix="/threads", tags=["Threads"])
v1_router.include_router(runs.router, prefix="/threads/{thread_id}/runs", tags=["Runs"])

# CRITICAL: Register files.router BEFORE files_static.router to prevent catch-all route conflicts
# files.router has specific /files/{file_id}/download endpoint (with prefix="/files")
# files_static.router has /files/{file_path:path} catch-all which matches EVERYTHING after /files/
# FastAPI matches routes in registration order, so specific routes must come first
v1_router.include_router(files.router, prefix="/files", tags=["Files"])

v1_router.include_router(embeddings.router, prefix="/embeddings", tags=["Embeddings"])
v1_router.include_router(gateways.router, prefix="/gateways", tags=["Gateways"])
v1_router.include_router(responses.router, prefix="/responses", tags=["Response API"])
v1_router.include_router(tools.router, prefix="/tools", tags=["Tools"])
v1_router.include_router(knowledge_bases.router, prefix="/knowledge_bases", tags=["Knowledge Bases"])
v1_router.include_router(agui.router, prefix="/ag-ui", tags=["AG-UI Protocol"])

# Add secure file serving AFTER files.router (no prefix to maintain /v1/files/ and /v1/plots/ paths)
# This catch-all must be registered LAST to avoid intercepting specific file operation routes
v1_router.include_router(files_static.router, tags=["Secure File Access"])

# Include the /invoke endpoint directly under /v1 (not under /responses)
from .routers.v1.responses import invoke_agent
v1_router.add_api_route("/invoke", invoke_agent, methods=["POST"], tags=["Agent Invocation"])

app.mount("/v1", v1_router)

# --- Include Management Endpoints ---
app.include_router(management.router, tags=["Management"])

# --- Include MCP Protocol Support ---
app.include_router(mcp.router, tags=["Model Context Protocol"])

# --- Health Check ---
@app.get("/health", summary="Health Check", tags=["Health"])
async def health_check():
    """Provides a simple health check endpoint for monitoring."""
    return {"status": "ok"}