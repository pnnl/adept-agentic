"""
This module provides the LangChain Tool wrappers for multi-agent and
multi-gateway communication.

These tools are the primary interface through which the `ScientificWorkflowAgent`
can delegate complex tasks to a team of specialized agents or to other gateways
in the mesh.

Architectural Role:
-   **Agent Tool Interface:** Exposes high-level tools (e.g., `CreateMultiAgentSession`,
    `DelegateTaskToGatewayTool`, `ListRegisteredGateways`) to the main agent's toolset.
-   **Facade for Complex Logic:** These tools act as a facade, hiding the
    underlying complexity of session management, A2A communication, and state
    propagation from the agent. The agent simply calls a tool, and this module
    handles the interaction with the appropriate backend manager or protocol.
-   **Context Propagation:** The tool factory functions (e.g.,
    `get_delegate_task_to_gateway_tool`) accept the parent agent instance. This
    allows the tools to access the agent's state, most importantly the original
    user's credentials (`user_token`), which is essential for securely propagating
    the user's identity across the gateway mesh.
-   **Gateway Introspection:** The `list_registered_gateways` tool allows the
    agent to discover which peer gateways have established mutual trust, enabling
    informed delegation decisions.
"""
import json
import os
import time
import uuid
import httpx
import asyncio
import traceback
from typing import Type, Optional, Dict, Any, TYPE_CHECKING
from functools import partial
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

# Correctly import from the python-a2a library
from a2a.client import A2AClient, AuthInterceptor, CredentialService
from a2a.client.middleware import ClientCallContext
from a2a.types import (
    Message, Part, DataPart, Role, TextPart, AgentCard,
    SendMessageRequest, MessageSendParams, SendMessageSuccessResponse, Task,
)

from ...logger_config import get_logger
from ...core.observability.smart_logger import create_trace
from ..external_tool_manager import tool_manager

if TYPE_CHECKING:
    from ..scientific_workflow.langchain_agent import ScientificWorkflowAgent

logger = get_logger(__name__)

# Asynchronous credential service to fetch Keycloak tokens
class KeycloakCredentialService(CredentialService):
    """
    An A2A CredentialService that fetches S2S tokens from Keycloak.
    """
    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
        self._keycloak_realm = os.getenv("KEYCLOAK_REALM", "master")

    async def get_credentials(self, security_scheme_name: str, context: ClientCallContext | None) -> str | None:
        """
        Fetches a client credentials token from Keycloak.
        """
        if not self._client_id or not self._client_secret:
            raise ValueError("AGENT_GATEWAY_CLIENT_ID and AGENT_GATEWAY_CLIENT_SECRET must be set.")

        token_url = f"{self._keycloak_url}/realms/{self._keycloak_realm}/protocol/openid-connect/token"
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(token_url, data=payload)
                response.raise_for_status()
                return response.json()["access_token"]
        except Exception as e:
            logger.error(f"Failed to get access token from Keycloak: {e}")
            return None

class DelegateTaskToGatewayLLMInput(BaseModel):
    """Input schema exposed to the LLM — mcp_session_id is auto-injected."""
    target_gateway_alias: str = Field(description="The registered alias of the target agent gateway (e.g., 'aws-gateway').")
    task: str = Field(description="The specific task or question to delegate to the target gateway.")


class DelegateTaskToGatewayInput(BaseModel):
    """Full input schema for the DelegateTaskToGatewayTool (internal use)."""
    target_gateway_alias: str = Field(description="The registered alias of the target agent gateway (e.g., 'aws-gateway').")
    task: str = Field(description="The specific task or question to delegate to the target gateway.")
    mcp_session_id: str = Field(description="The current MCP session ID for context and state tracking.")

class DelegateTaskToGatewayTool(BaseTool):
    """
    A LangChain tool for securely delegating tasks to other agent gateways.
    """
    name: str = "delegate_task_to_gateway"
    description: str = "Delegates a task to another agent gateway. Use this when a task requires capabilities that another gateway possesses."
    args_schema: Type[BaseModel] = DelegateTaskToGatewayInput
    user_token: str # This will be set dynamically

    def _run(self, **kwargs: Any) -> str:
        """
        Synchronous execution - DEPRECATED and DISABLED.
        This method should never be called. Use get_delegate_task_to_gateway_tool() factory function instead.
        """
        logger.error("DelegateTaskToGatewayTool._run() called - this should NEVER happen!")
        logger.error("The synchronous _run() method is disabled to prevent asyncio event loop conflicts.")
        logger.error(f"Call stack:\n{traceback.format_stack()}")
        
        # Always return an error instead of trying to execute
        return "ERROR: Synchronous execution of delegate_task_to_gateway is disabled. This tool must be used via the async factory function get_delegate_task_to_gateway_tool()."

    async def _arun(self, target_gateway_alias: str, task: str, mcp_session_id: str) -> str:
        """
        Asynchronously delegates a task to another gateway.
        """
        # Generate multi_gateway_session_id early so it's available for trace correlation
        multi_gateway_session_id = f"mg-{uuid.uuid4()}"
        registry_url = os.getenv("GATEWAY_REGISTRY_URL", "http://gateway_registry:8086")

        logger.info(
            f"[A2A_DELEGATION] Starting: target={target_gateway_alias}, "
            f"session={multi_gateway_session_id}, mcp_session={mcp_session_id}"
        )

        with create_trace(
            logger, "a2a_delegation",
            session_id=multi_gateway_session_id,
            metadata={"target_gateway": target_gateway_alias, "mcp_session_id": mcp_session_id},
        ) as t:
            try:
                # --- Get Service Token (used for registry lookup and A2A call) ---
                with t.span("service_token_acquisition") as s:
                    cred_service = KeycloakCredentialService(
                        client_id=os.getenv("AGENT_GATEWAY_CLIENT_ID"),
                        client_secret=os.getenv("AGENT_GATEWAY_CLIENT_SECRET")
                    )
                    service_token = await cred_service.get_credentials("bearer", None)
                    if not service_token:
                        return "Error: Failed to obtain service token from Keycloak for gateway registry lookup."
                    auth_headers = {"Authorization": f"Bearer {service_token}"}
                    token_ms = s.end()

                logger.info(f"[A2A_DELEGATION] service_token_acquisition: token_ms={token_ms:.1f}")

                # --- Service Discovery & Capability Negotiation ---
                with t.span("service_discovery", input={"target_alias": target_gateway_alias}) as s:
                    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
                        # 1. Discover the gateway's public URL from the registry
                        gateway_info_url = f"{registry_url}/v1/gateways/{target_gateway_alias}"
                        response = await client.get(gateway_info_url, headers=auth_headers)
                        if response.status_code == 404:
                            return f"Error: Discovery failed. No gateway with alias '{target_gateway_alias}' is registered."
                        response.raise_for_status()
                        target_url = response.json().get("public_url")
                        if not target_url:
                            return f"Error: Registered gateway '{target_gateway_alias}' does not have a public URL."

                        # 2. Fetch its AgentCard
                        agent_card_url = f"{target_url.rstrip('/')}/.well-known/agent-card.json"
                        card_response = await client.get(agent_card_url)
                        card_response.raise_for_status()
                        agent_card_data = card_response.json()
                        agent_card = AgentCard.model_validate(agent_card_data)

                        # Ensure AgentCard URL has trailing slash to avoid 301 redirect
                        # (HTTP 301 converts POST to GET, breaking JSONRPC calls)
                        if agent_card.url and not agent_card.url.endswith("/"):
                            agent_card.url = agent_card.url + "/"

                    discovery_ms = s.end(output={"target_url": target_url, "agent_card_url": agent_card.url})

                logger.info(
                    f"[A2A_DELEGATION] service_discovery: target_url={target_url}, discovery_ms={discovery_ms:.1f}"
                )

                # --- A2A Client Setup and Call ---
                with t.span("a2a_send_message", input={"agent_card_url": agent_card.url}) as s:
                    auth_interceptor = AuthInterceptor(credential_service=cred_service)
                    async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=300.0) as a2a_httpx_client:
                        remote_gateway_client = A2AClient(
                            httpx_client=a2a_httpx_client,
                            agent_card=agent_card,
                            interceptors=[auth_interceptor],
                        )

                        # NOTE: user_token is embedded in the message body because the A2A SDK
                        # does not support custom HTTP headers on JSONRPC calls.
                        custom_data = {
                            "task": task,
                            "user_token": self.user_token,
                            "multi_gateway_session_id": multi_gateway_session_id,
                        }

                        message_to_send = Message(
                            role=Role.user,
                            parts=[Part(root=DataPart(data=custom_data))],
                            message_id=str(uuid.uuid4())
                        )

                        request_id = str(uuid.uuid4())
                        send_request = SendMessageRequest(
                            id=request_id,
                            params=MessageSendParams(message=message_to_send),
                        )

                        response = await remote_gateway_client.send_message(request=send_request)
                    send_ms = s.end()

                logger.info(f"[A2A_DELEGATION] a2a_send_message: send_ms={send_ms:.1f}")

                # --- Extract result from JSONRPC response ---
                with t.span("response_extraction") as s:
                    if isinstance(response.root, SendMessageSuccessResponse):
                        result = response.root.result
                        if isinstance(result, Message):
                            response_text = " ".join(
                                part.root.text for part in result.parts
                                if isinstance(part.root, TextPart)
                            )
                            final_result = f"Task successfully delegated. Response from {target_gateway_alias}: {response_text}"
                        elif isinstance(result, Task):
                            task_status = result.status.state if result.status else "unknown"
                            if result.artifacts:
                                artifact_texts = []
                                for artifact in result.artifacts:
                                    for part in artifact.parts:
                                        if isinstance(part.root, TextPart):
                                            artifact_texts.append(part.root.text)
                                if artifact_texts:
                                    final_result = f"Task delegated to {target_gateway_alias} (status: {task_status}). Result: {' '.join(artifact_texts)}"
                                else:
                                    final_result = f"Task delegated to {target_gateway_alias}. Status: {task_status}, Task ID: {result.id}"
                            else:
                                final_result = f"Task delegated to {target_gateway_alias}. Status: {task_status}, Task ID: {result.id}"
                        else:
                            final_result = f"Task delegated to {target_gateway_alias}. Unexpected result type: {type(result).__name__}"
                    else:
                        error = response.root.error if hasattr(response.root, "error") else response.root
                        final_result = f"Error: Remote gateway '{target_gateway_alias}' returned an error: {error}"
                    extract_ms = s.end(output={"result_length": len(final_result)})

                total_ms = token_ms + discovery_ms + send_ms + extract_ms
                logger.info(
                    f"[A2A_DELEGATION] Completed: session={multi_gateway_session_id}, "
                    f"total_ms={total_ms:.1f}, token_ms={token_ms:.1f}, "
                    f"discovery_ms={discovery_ms:.1f}, send_ms={send_ms:.1f}, extract_ms={extract_ms:.1f}"
                )
                return final_result

            except Exception as e:
                logger.error(f"[A2A_DELEGATION] Failed: target={target_gateway_alias}, error={e}", exc_info=True)
                return f"Error: Failed to communicate with gateway '{target_gateway_alias}'. Reason: {e}"

def get_delegate_task_to_gateway_tool(agent: 'ScientificWorkflowAgent') -> BaseTool:
    """
    Factory function to create the DelegateTaskToGatewayTool.

    Uses StructuredTool (not Tool) to support multiple keyword arguments.
    Auto-injects mcp_session_id from the agent so the LLM only needs to
    provide target_gateway_alias and task.
    """
    logger.info("Creating delegate_task_to_gateway tool via factory function (proper async approach)")

    async def _arun_with_context(target_gateway_alias: str, task: str) -> str:
        logger.info("Factory function _arun_with_context() called - this is the CORRECT execution path")
        logger.info(f"Current event loop: {asyncio.get_running_loop()}")

        if not agent.user_credentials or not agent.user_credentials.token:
            raise ValueError("User token not available in agent credentials for multi-gateway task.")

        # Auto-inject mcp_session_id from the agent's session context
        mcp_session_id = getattr(agent, "mcp_session_id", None) or "auto"
        logger.info(f"Auto-injected mcp_session_id: {mcp_session_id}")

        # Phase 0a: S2S token substitution for service API key callers (Session 80)
        # Service API keys (sk-service-*) are Redis-validated bearer tokens that
        # cannot be JWT-validated by peer gateways. When delegating via A2A, we
        # substitute an S2S client-credentials JWT (from AGENT_GATEWAY_CLIENT_ID)
        # so the peer can validate it. The original user identity is preserved
        # separately via X-Forwarded-User-Token in the delegation request.
        user_token = agent.user_credentials.token
        auth_type = getattr(agent.user_credentials, "auth_type", "jwt")
        if auth_type == "service_api_key":
            logger.info(
                f"[A2A_TOKEN_EXCHANGE] Service API key detected for user "
                f"'{agent.user_credentials.username}' — substituting S2S JWT for delegation"
            )
            credential_service = KeycloakCredentialService(
                client_id=os.getenv("AGENT_GATEWAY_CLIENT_ID", ""),
                client_secret=os.getenv("AGENT_GATEWAY_CLIENT_SECRET", ""),
            )
            exchanged_token = await credential_service.get_credentials("bearer", None)
            if not exchanged_token:
                raise ValueError(
                    "Failed to exchange service API key for Keycloak JWT. "
                    "Check AGENT_GATEWAY_CLIENT_ID and AGENT_GATEWAY_CLIENT_SECRET."
                )
            user_token = exchanged_token
            logger.info("[A2A_TOKEN_EXCHANGE] Successfully exchanged service API key for JWT")

        tool_instance = DelegateTaskToGatewayTool(user_token=user_token)

        return await tool_instance._arun(
            target_gateway_alias=target_gateway_alias,
            task=task,
            mcp_session_id=mcp_session_id
        )

    return StructuredTool.from_function(
        name="delegate_task_to_gateway",
        description="Delegates a task to another agent gateway. Use this when a task requires capabilities that another gateway possesses. You must provide the target_gateway_alias (e.g., 'aws-gateway') and the task description.",
        func=None,  # No sync version
        coroutine=_arun_with_context,
        args_schema=DelegateTaskToGatewayLLMInput,
    )


# ---------------------------------------------------------------------------
# Gateway Introspection: list_registered_gateways
# ---------------------------------------------------------------------------

class ListRegisteredGatewaysLLMInput(BaseModel):
    """Input schema exposed to the LLM — no required parameters."""
    filter_healthy: bool = Field(
        default=False,
        description="If true, only return gateways with health_status 'Healthy'.",
    )


def get_list_registered_gateways_tool(agent: 'ScientificWorkflowAgent') -> BaseTool:
    """
    Factory function to create the list_registered_gateways tool.

    Queries the Gateway Registry to return all peer gateways that have
    established mutual trust in the A2A mesh. The agent can use this to
    discover available gateways before delegating tasks.
    """
    logger.info("Creating list_registered_gateways tool via factory function")

    async def _arun_list_gateways(filter_healthy: bool = False) -> str:
        registry_url = os.getenv("GATEWAY_REGISTRY_URL", "http://gateway_registry:8086")
        mcp_session_id = getattr(agent, "mcp_session_id", None) or "unknown"

        logger.info(
            f"[GATEWAY_INTROSPECTION] Listing registered gateways, "
            f"filter_healthy={filter_healthy}, mcp_session={mcp_session_id}"
        )

        try:
            # Obtain a service token for registry access
            cred_service = KeycloakCredentialService(
                client_id=os.getenv("AGENT_GATEWAY_CLIENT_ID"),
                client_secret=os.getenv("AGENT_GATEWAY_CLIENT_SECRET"),
            )
            service_token = await cred_service.get_credentials("bearer", None)
            if not service_token:
                return json.dumps({
                    "error": "Failed to obtain service token from Keycloak for gateway registry lookup.",
                    "total_gateways": 0,
                    "gateways": [],
                })

            auth_headers = {"Authorization": f"Bearer {service_token}"}

            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                response = await client.get(
                    f"{registry_url}/v1/gateways/",
                    headers=auth_headers,
                )
                response.raise_for_status()
                raw_gateways = response.json()

            # Parse capabilities into structured tags and descriptions
            gateways = []
            for gw in raw_gateways:
                capabilities = gw.get("capabilities") or []
                tags = []
                description = None
                for cap in capabilities:
                    if isinstance(cap, str):
                        if cap.startswith("description:"):
                            description = cap[len("description:"):]
                        elif cap.startswith("tag:"):
                            tags.append(cap[len("tag:"):])
                        else:
                            tags.append(cap)

                entry = {
                    "alias": gw.get("alias"),
                    "public_url": gw.get("public_url"),
                    "health_status": gw.get("health_status", "Unknown"),
                    "description": description,
                    "tags": tags,
                    "created_at": gw.get("created_at"),
                    "last_health_check": gw.get("last_health_check"),
                }
                gateways.append(entry)

            # Apply health filter if requested
            if filter_healthy:
                gateways = [g for g in gateways if g["health_status"] == "Healthy"]

            result = {
                "total_gateways": len(gateways),
                "gateways": gateways,
            }

            logger.info(
                f"[GATEWAY_INTROSPECTION] Found {len(gateways)} gateways "
                f"(filter_healthy={filter_healthy})"
            )
            return json.dumps(result, indent=2, default=str)

        except httpx.HTTPStatusError as e:
            logger.error(f"[GATEWAY_INTROSPECTION] Registry HTTP error: {e.response.status_code}")
            return json.dumps({
                "error": f"Gateway registry returned HTTP {e.response.status_code}",
                "total_gateways": 0,
                "gateways": [],
            })
        except Exception as e:
            logger.error(f"[GATEWAY_INTROSPECTION] Error: {e}", exc_info=True)
            return json.dumps({
                "error": f"Failed to list gateways: {str(e)}",
                "total_gateways": 0,
                "gateways": [],
            })

    return StructuredTool.from_function(
        name="list_registered_gateways",
        description=(
            "Lists all peer agent gateways registered in the A2A mesh. "
            "Use this to discover which gateways are available before delegating tasks. "
            "Returns each gateway's alias, public URL, health status, description, and tags. "
            "Set filter_healthy=true to only see healthy gateways."
        ),
        func=None,
        coroutine=_arun_list_gateways,
        args_schema=ListRegisteredGatewaysLLMInput,
    )