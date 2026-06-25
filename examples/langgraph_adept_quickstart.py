#!/usr/bin/env python3
"""
LangGraph + ADEPT Quick Start Example
======================================

Minimal example showing how to integrate ADEPT API into a LangGraph application.

Usage:
    export KEYCLOAK_USERNAME="notebook-user"
    export KEYCLOAK_PASSWORD="your_password"
    python examples/langgraph_adept_quickstart.py
"""

import os
from typing import Annotated, Sequence, TypedDict

import httpx
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from litellm import completion
import litellm


# =============================================================================
# CONFIGURATION
# =============================================================================

# Agent Gateway URL - defaults to localhost HTTP for out-of-the-box functionality
# Override with AGENT_GATEWAY_URL environment variable for other access patterns:
#   - Development (default): http://localhost:8083/v1
#   - Production SSL: https://api.agentic.local/v1 (requires SSL cert trust)
#   - Internal (container): http://agent_gateway:8081/v1
AGENT_GATEWAY_URL = os.getenv("AGENT_GATEWAY_URL", "http://localhost:8083/v1")


# =============================================================================
# LITELLM ADEPT PROVIDER REGISTRATION (Session 48)
# =============================================================================

# Register ADEPT as a custom LiteLLM provider
# This allows litellm to recognize "adept/model-name" format
litellm.register_model({
    "adept/scientific-agent-v1": {
        "max_tokens": 4096,
        "max_input_tokens": 100000,
        "max_output_tokens": 4096,
        "input_cost_per_token": 0.00001,  # $0.01 per 1K tokens
        "output_cost_per_token": 0.00003,  # $0.03 per 1K tokens
        "litellm_provider": "openai",
        "mode": "chat",
        "supports_function_calling": True,
        "supports_parallel_function_calling": True,
        "supports_vision": False,
    },
    "adept/n8n-summary-agent": {
        "max_tokens": 4096,
        "max_input_tokens": 100000,
        "max_output_tokens": 4096,
        "input_cost_per_token": 0.00001,
        "output_cost_per_token": 0.00003,
        "litellm_provider": "openai",
        "mode": "chat",
        "supports_function_calling": True,
        "supports_parallel_function_calling": True,
        "supports_vision": False,
    },
})


# =============================================================================
# STEP 1: AUTHENTICATE WITH KEYCLOAK
# =============================================================================


def get_adept_token(username: str, password: str, client_id: str = "validation-runner-client", client_secret: str = None) -> str:
    """
    Get JWT token from Keycloak.

    Note: ADEPT uses the 'master' realm for all authentication.
    Uses validation-runner-client by default (confidential client with direct access grants enabled).
    """
    # Keycloak is on port 8180, not 8083 (agent gateway)
    # Use KEYCLOAK_URL env var or default to localhost:8180
    keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
    token_url = f"{keycloak_url}/realms/master/protocol/openid-connect/token"

    auth_data = {
        "grant_type": "password",
        "client_id": client_id,
        "username": username,
        "password": password,
    }
    if client_secret:
        auth_data["client_secret"] = client_secret

    response = httpx.post(
        token_url,
        data=auth_data,
        verify=False,  # For local development
    )
    response.raise_for_status()
    return response.json()["access_token"]


# =============================================================================
# STEP 2: CALL ADEPT API WITH LITELLM
# =============================================================================


def call_adept_api(
    messages: list,
    token: str,
    thread_id: str = "quickstart-thread",
    model: str = "adept/scientific-agent-v1",
) -> str:
    """
    Call ADEPT API using litellm.

    IMPORTANT: ADEPT is NOT an LLM proxy - it implements its own model.
    Use 'adept/scientific-agent-v1' (LiteLLM-compatible alias) or
    'agentic-framework:scientific-agent-v1' (native format) as the model name.
    """
    response = completion(
        model=model,
        messages=messages,
        base_url=AGENT_GATEWAY_URL,
        api_key=token,  # LiteLLM adds Bearer prefix automatically
        extra_headers={"X-Thread-Id": thread_id},
        temperature=0.7,
        max_tokens=500,
    )
    return response.choices[0].message.content


# =============================================================================
# STEP 3: CREATE LANGGRAPH WORKFLOW
# =============================================================================


class State(TypedDict):
    """Simple state for LangGraph."""

    messages: Annotated[Sequence[BaseMessage], add_messages]


def create_workflow(token: str, thread_id: str) -> StateGraph:
    """Create a simple LangGraph workflow using ADEPT."""

    def agent_node(state: State) -> State:
        """Agent node that calls ADEPT API."""
        messages = state["messages"]

        # Convert to litellm format
        litellm_messages = [
            {"role": msg.type, "content": msg.content} for msg in messages
        ]

        # Call ADEPT API
        response_text = call_adept_api(litellm_messages, token, thread_id)

        return {"messages": [HumanMessage(content=response_text)]}

    # Build graph
    workflow = StateGraph(State)
    workflow.add_node("agent", agent_node)
    workflow.set_entry_point("agent")
    workflow.add_edge("agent", END)

    return workflow.compile()


# =============================================================================
# STEP 4: RUN EXAMPLE
# =============================================================================


def main():
    """Run quick start example."""
    print("=" * 60)
    print("LangGraph + ADEPT Quick Start")
    print("=" * 60)

    # 1. Authenticate
    username = os.getenv("KEYCLOAK_USERNAME", "notebook-user")
    password = os.getenv("KEYCLOAK_PASSWORD")

    if not password:
        print("Error: Set KEYCLOAK_PASSWORD environment variable")
        return

    print(f"\n[1/3] Authenticating as {username}...")
    token = get_adept_token(username, password)
    print(f"✓ Token: {token[:30]}...")

    # 2. Create workflow
    print("\n[2/3] Creating LangGraph workflow...")
    thread_id = "quickstart-demo"
    workflow = create_workflow(token, thread_id)
    print("✓ Workflow ready")

    # 3. Run query
    print("\n[3/3] Running query...")
    query = "What is the capital of France?"
    print(f"Query: {query}")

    result = workflow.invoke({"messages": [HumanMessage(content=query)]})

    print("\nResponse:")
    print("-" * 60)
    print(result["messages"][-1].content)
    print("-" * 60)

    gateway_base = AGENT_GATEWAY_URL.rsplit("/v1", 1)[0]
    print(f"\n✓ View traces: {gateway_base}/langfuse")
    print(f"✓ Thread ID: {thread_id}")
    print(f"✓ Gateway URL: {AGENT_GATEWAY_URL}")
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
