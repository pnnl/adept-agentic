"""
This module is the main entry point for the A2A (Agent-to-Agent) server.

It uses a factory function, `create_a2a_app`, to construct and configure the
A2A-compliant FastAPI sub-application.

Architectural Role:
-   **A2A Server Factory:** Provides a clean, centralized factory for creating
    the A2A server, encapsulating all its required components.
-   **AgentCard Publication:** It is responsible for generating the gateway's
    `AgentCard`, which is a public manifest of its capabilities and security
    requirements. This card is crucial for service discovery.
-   **Component Wiring:** It wires together all the necessary A2A components:
    -   `A2AExecutor`: The business logic layer.
    -   `KeycloakContextBuilder`: The security middleware.
    -   `InMemoryTaskStore`: A simple, non-persistent task store.
    -   `DefaultRequestHandler`: The default A2A request handler.
-   **Sub-Application Mounting:** The main `agent_gateway/app.py` module imports
    `create_a2a_app` and mounts the returned FastAPI application at the `/a2a`
    path, creating a dedicated, protocol-compliant namespace for inter-gateway
    communication.
"""
import os
from typing import Dict, Any
from fastapi import FastAPI
from a2a.server.apps.jsonrpc import A2AFastAPIApplication
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.types import AgentCard

from agentic_framework_pkg.logger_config import get_logger
from .a2a_executor import A2AExecutor
from .keycloak_context_builder import KeycloakContextBuilder

logger = get_logger(__name__)

def get_agent_card() -> Dict[str, Any]:
    """
    Generates the AgentCard for this gateway.

    The AgentCard is a standardized, self-describing manifest that advertises
    the gateway's capabilities, its A2A endpoint URL, and, most importantly,
    its security requirements. Other gateways fetch this card to learn how to
    communicate securely.

    Returns:
        A dictionary representing the AgentCard.
    """
    public_gateway_url = os.getenv("PUBLIC_GATEWAY_URL", "http://localhost:8083")
    keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
    keycloak_realm = os.getenv("KEYCLOAK_REALM", "master")

    # A2A endpoint URL - strip /v1 suffix if present since A2A is a separate protocol
    base_url = public_gateway_url.rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]  # Remove /v1 suffix

    agent_card = {
        "name": os.getenv("AGENT_GATEWAY_ALIAS", "agent-gateway"),
        "version": "1.0.0",
        "description": "An agent gateway that orchestrates scientific workflows and can delegate tasks.",
        "url": f"{base_url}/a2a/",
        "capabilities": {
            # A2A SDK AgentCapabilities fields (optional protocol capabilities)
            # NOT custom workflow capabilities - use 'skills' for agent capabilities
            "streaming": False,
            "push_notifications": False,
            "state_transition_history": True,
            "extensions": None
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": [
            "application/json", "text/json", "text/plain", "text/yaml", "text/xml", "text/csv",
            "application/xml", "application/yaml", "application/csv", "application/x-www-form-urlencoded",
            "application/octet-stream", "application/pdf",
            "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/tiff"
        ],
        "preferredTransport": "JSONRPC",
        "securitySchemes": {
            "keycloak_oauth": {
                "type": "oauth2",
                "flows": {
                    "clientCredentials": {
                        "tokenUrl": f"{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/token",
                        "scopes": {}
                    }
                }
            }
        },
        "security": [{"keycloak_oauth": []}],
        "skills": [
            {
                "id": "delegate-task",
                "name": "Delegate Task",
                "description": "Accepts a delegated task from another authenticated and authorized agent gateway for processing.",
                "tags": ["delegation", "gateway", "scientific workflow orchestration"],
            }
        ]
    }
    return agent_card

def create_a2a_app() -> FastAPI:
    """
    Creates and configures the A2A FastAPI sub-application.

    This factory function wires together all the components required by the
    `a2a-sdk` to create a compliant server.

    Returns:
        The configured FastAPI application for A2A communication.
    """
    agent_card_data = get_agent_card()
    
    # The AgentExecutor is our bridge to the ScientificWorkflowAgent
    agent_executor = A2AExecutor()
    
    # The RequestHandler orchestrates the A2A lifecycle
    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=InMemoryTaskStore()
    )
    
    # The A2A Application handles the protocol and server logic
    agent_card = AgentCard.model_validate(agent_card_data)
    a2a_app = A2AFastAPIApplication(
        agent_card=agent_card,
        http_handler=request_handler,
        context_builder=KeycloakContextBuilder()
    ).build()
    
    @a2a_app.get("/health", summary="A2A Health Check", tags=["A2A"])
    async def a2a_health_check():
        """Provides a simple health check for the A2A sub-application."""
        return {"status": "ok"}
        
    return a2a_app