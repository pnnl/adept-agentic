#!/usr/bin/env python3
"""
LangGraph Integration with ADEPT OpenAI-Compatible API
=======================================================

This example demonstrates how to integrate the ADEPT framework's OpenAI-compatible
API into a LangGraph application using litellm as the client library.

Key Features:
- Keycloak JWT authentication
- Session management for Langfuse telemetry
- Multi-agent LangGraph workflow
- Seamless integration with existing LangGraph applications

Prerequisites:
- ADEPT framework running (make start)
- Valid Keycloak user credentials
- litellm installed: pip install litellm
- langgraph installed: pip install langgraph langchain-core
"""

import json
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
# AUTHENTICATION: Keycloak JWT Token Management
# =============================================================================


class ADEPTAuthenticator:
    """Handles Keycloak authentication for ADEPT API access."""

    def __init__(
        self,
        keycloak_url: str = None,
        keycloak_realm: str = "master",
        agent_gateway_url: str = None,
        username: str = None,
        password: str = None,
        client_id: str = "validation-runner-client",
        client_secret: str = None,
    ):
        """
        Initialize ADEPT authenticator.

        Args:
            keycloak_url: Keycloak base URL (default: derived from AGENT_GATEWAY_URL)
            keycloak_realm: Keycloak realm name (default: master - ADEPT uses master realm)
            agent_gateway_url: ADEPT API base URL (default: from AGENT_GATEWAY_URL env var)
            username: Keycloak username (or set KEYCLOAK_USERNAME env var)
            password: Keycloak password (or set KEYCLOAK_PASSWORD env var)
            client_id: OAuth2 client ID (default: validation-runner-client)
            client_secret: OAuth2 client secret (optional, for confidential clients)
        """
        # Use AGENT_GATEWAY_URL config if not explicitly provided
        self.agent_gateway_url = agent_gateway_url or AGENT_GATEWAY_URL
        # Keycloak is on port 8180, not 8083 (agent gateway)
        # Default to http://localhost:8180 or use KEYCLOAK_URL env var
        default_keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
        self.keycloak_url = keycloak_url or default_keycloak_url
        self.keycloak_realm = keycloak_realm
        self.username = username or os.getenv("KEYCLOAK_USERNAME", "notebook-user")
        self.password = password or os.getenv("KEYCLOAK_PASSWORD", "notebook-password")
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.refresh_token = None

    def authenticate(self) -> str:
        """
        Authenticate with Keycloak and return access token.

        Returns:
            str: JWT access token

        Raises:
            Exception: If authentication fails
        """
        token_url = f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/token"

        data = {
            "grant_type": "password",
            "client_id": self.client_id,
            "username": self.username,
            "password": self.password,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret

        response = httpx.post(token_url, data=data, verify=False)
        response.raise_for_status()

        token_data = response.json()
        self.access_token = token_data["access_token"]
        self.refresh_token = token_data["refresh_token"]

        return self.access_token

    def get_auth_headers(self) -> dict:
        """
        Get authentication headers for API requests.

        Returns:
            dict: Headers with Bearer token
        """
        if not self.access_token:
            self.authenticate()

        return {"Authorization": f"Bearer {self.access_token}"}


# =============================================================================
# SESSION MANAGEMENT: Langfuse Telemetry Integration
# =============================================================================


class ADEPTSessionManager:
    """
    Manages ADEPT session IDs and user context for Langfuse telemetry.

    IMPORTANT: Session IDs are NOT managed manually by the client.
    The ADEPT orchestration service automatically creates and tracks sessions
    when you use the /v1/responses/chat/completions endpoint.

    Your Langfuse telemetry is automatically associated with:
    - user_id: Extracted from JWT token
    - thread_id: LangGraph conversation thread
    - session_id: ADEPT internal session (auto-created)
    """

    def __init__(self, authenticator: ADEPTAuthenticator, thread_id: str = None):
        """
        Initialize session manager.

        Args:
            authenticator: ADEPTAuthenticator instance
            thread_id: LangGraph thread ID (optional, will be auto-generated if not provided)
        """
        self.authenticator = authenticator
        self.thread_id = thread_id or f"langgraph-thread-{os.urandom(8).hex()}"

    def get_session_context(self) -> dict:
        """
        Get session context for API requests.

        Returns:
            dict: Session metadata for ADEPT API
        """
        return {
            "thread_id": self.thread_id,
            # user_id is automatically extracted from JWT by ADEPT
            # session_id is automatically created by ADEPT orchestration service
        }

    def get_langfuse_trace_url(self, agent_gateway_url: str) -> str:
        """
        Get Langfuse trace URL for this session.

        Args:
            agent_gateway_url: ADEPT API base URL

        Returns:
            str: Langfuse UI URL for viewing traces
        """
        # Langfuse is automatically configured by ADEPT
        # Access Langfuse UI at: https://api.agentic.local/langfuse
        return f"{agent_gateway_url}/langfuse"


# =============================================================================
# LITELLM CLIENT: ADEPT OpenAI-Compatible API Integration
# =============================================================================


class ADEPTLiteLLMClient:
    """
    LiteLLM client configured for ADEPT OpenAI-compatible API.

    This client abstracts the complexity of:
    - Authentication (Keycloak JWT)
    - Session management (thread_id propagation)
    - Error handling and retries
    """

    def __init__(
        self,
        authenticator: ADEPTAuthenticator,
        session_manager: ADEPTSessionManager,
        model: str = "adept/scientific-agent-v1",
        base_url: str = None,
    ):
        """
        Initialize ADEPT LiteLLM client.

        IMPORTANT: ADEPT is NOT an LLM proxy - it implements its own model.
        Use 'adept/scientific-agent-v1' (LiteLLM-compatible alias) or
        'agentic-framework:scientific-agent-v1' (native format) as the model name.

        Args:
            authenticator: ADEPTAuthenticator instance
            session_manager: ADEPTSessionManager instance
            model: Model name (default: adept/scientific-agent-v1)
            base_url: ADEPT API base URL (default: from AGENT_GATEWAY_URL)
        """
        self.authenticator = authenticator
        self.session_manager = session_manager
        self.model = model
        self.base_url = base_url or AGENT_GATEWAY_URL

    def chat_completion(
        self,
        messages: list,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs,
    ):
        """
        Call ADEPT chat completion endpoint using litellm.

        Args:
            messages: List of message dicts [{"role": "user", "content": "..."}]
            stream: Enable streaming responses (default: False)
            temperature: Sampling temperature (default: 0.7)
            max_tokens: Max response tokens (default: 1000)
            **kwargs: Additional litellm parameters

        Returns:
            litellm.ModelResponse: Completion response
        """
        # Get fresh auth token
        auth_headers = self.authenticator.get_auth_headers()
        session_context = self.session_manager.get_session_context()

        # LiteLLM configuration for ADEPT
        # Extract token from Authorization header (remove "Bearer " prefix)
        auth_value = auth_headers["Authorization"]
        token = auth_value.replace("Bearer ", "") if auth_value.startswith("Bearer ") else auth_value

        response = completion(
            model=self.model,
            messages=messages,
            base_url=self.base_url,
            api_key=token,  # Pass raw token - LiteLLM adds Bearer prefix automatically
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_headers={
                "X-Thread-Id": session_context[
                    "thread_id"
                ],  # Pass thread_id for session tracking
            },
            **kwargs,
        )

        return response


# =============================================================================
# LANGGRAPH INTEGRATION: Multi-Agent Workflow
# =============================================================================


class AgentState(TypedDict):
    """State for multi-agent LangGraph workflow."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    next_agent: str


def create_adept_agent(
    name: str,
    system_prompt: str,
    adept_client: ADEPTLiteLLMClient,
):
    """
    Create a LangGraph agent node that uses ADEPT API.

    Args:
        name: Agent name
        system_prompt: System prompt for the agent
        adept_client: ADEPTLiteLLMClient instance

    Returns:
        callable: Agent node function
    """

    def agent_node(state: AgentState) -> AgentState:
        """Agent node that calls ADEPT API."""
        messages = state["messages"]

        # Convert LangChain messages to litellm format
        litellm_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            if isinstance(msg, HumanMessage):
                litellm_messages.append({"role": "user", "content": msg.content})
            else:
                litellm_messages.append({"role": "assistant", "content": msg.content})

        # Call ADEPT API via litellm
        response = adept_client.chat_completion(
            messages=litellm_messages, temperature=0.7, max_tokens=500
        )

        # Extract response
        assistant_message = response.choices[0].message.content

        # Determine next agent (simple routing logic)
        next_agent = "end"
        if "researcher" in name and "need data" in assistant_message.lower():
            next_agent = "data_analyst"
        elif "data_analyst" in name and "need visualization" in assistant_message.lower():
            next_agent = "visualizer"

        return {
            "messages": messages + [HumanMessage(content=assistant_message)],
            "next_agent": next_agent,
        }

    return agent_node


def create_multi_agent_workflow(adept_client: ADEPTLiteLLMClient) -> StateGraph:
    """
    Create a multi-agent LangGraph workflow using ADEPT API.

    This example demonstrates:
    - Multiple specialized agents (researcher, data analyst, visualizer)
    - Conditional routing between agents
    - Seamless ADEPT integration via litellm

    Args:
        adept_client: ADEPTLiteLLMClient instance

    Returns:
        StateGraph: Compiled LangGraph workflow
    """
    # Create agent nodes
    researcher = create_adept_agent(
        name="researcher",
        system_prompt="You are a scientific researcher. Analyze the user's question and provide research insights.",
        adept_client=adept_client,
    )

    data_analyst = create_adept_agent(
        name="data_analyst",
        system_prompt="You are a data analyst. Process data and provide statistical insights.",
        adept_client=adept_client,
    )

    visualizer = create_adept_agent(
        name="visualizer",
        system_prompt="You are a data visualizer. Create visualization recommendations.",
        adept_client=adept_client,
    )

    # Build workflow graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("researcher", researcher)
    workflow.add_node("data_analyst", data_analyst)
    workflow.add_node("visualizer", visualizer)

    # Add edges (routing logic)
    def route_next(state: AgentState) -> str:
        """Route to next agent based on state."""
        next_agent = state.get("next_agent", "end")
        if next_agent == "end":
            return END
        return next_agent

    workflow.set_entry_point("researcher")
    workflow.add_conditional_edges("researcher", route_next, ["data_analyst", "visualizer", END])
    workflow.add_conditional_edges("data_analyst", route_next, ["visualizer", END])
    workflow.add_conditional_edges("visualizer", route_next, [END])

    return workflow.compile()


# =============================================================================
# EXAMPLE USAGE
# =============================================================================


def main():
    """Example: Multi-agent workflow with ADEPT API."""
    print("=" * 80)
    print("LangGraph + ADEPT Integration Example")
    print("=" * 80)

    # 1. Setup authentication
    print("\n[1/4] Setting up authentication...")
    authenticator = ADEPTAuthenticator(
        username=os.getenv("KEYCLOAK_USERNAME", "notebook-user"),
        password=os.getenv("KEYCLOAK_PASSWORD"),
    )

    try:
        token = authenticator.authenticate()
        print(f"✓ Authenticated successfully (token: {token[:20]}...)")
    except Exception as e:
        print(f"✗ Authentication failed: {e}")
        return

    # 2. Setup session management
    print("\n[2/4] Setting up session management...")
    session_manager = ADEPTSessionManager(
        authenticator=authenticator, thread_id="langgraph-example-thread"
    )
    session_context = session_manager.get_session_context()
    print(f"✓ Session context: {json.dumps(session_context, indent=2)}")
    gateway_base = AGENT_GATEWAY_URL.rsplit("/v1", 1)[0]
    print(
        f"✓ Langfuse traces available at: {session_manager.get_langfuse_trace_url(gateway_base)}"
    )

    # 3. Create ADEPT LiteLLM client
    print("\n[3/4] Creating ADEPT LiteLLM client...")
    adept_client = ADEPTLiteLLMClient(
        authenticator=authenticator,
        session_manager=session_manager,
        model="gpt-4",  # ADEPT will route to available model
    )
    print(f"✓ ADEPT client initialized (base_url: {adept_client.base_url})")

    # 4. Create and run multi-agent workflow
    print("\n[4/4] Creating multi-agent LangGraph workflow...")
    workflow = create_multi_agent_workflow(adept_client)
    print("✓ Workflow compiled")

    # Run workflow with user query
    print("\n" + "=" * 80)
    print("Running Multi-Agent Workflow")
    print("=" * 80)

    user_query = "Analyze the Iris dataset and recommend visualizations"
    print(f"\nUser Query: {user_query}")

    initial_state = {
        "messages": [HumanMessage(content=user_query)],
        "next_agent": "researcher",
    }

    print("\nWorkflow Execution:")
    print("-" * 80)

    try:
        final_state = workflow.invoke(initial_state)

        print("\n✓ Workflow completed successfully!")
        print("\nFinal Messages:")
        for i, msg in enumerate(final_state["messages"]):
            print(f"\n[Message {i+1}]")
            print(f"Content: {msg.content[:200]}...")

    except Exception as e:
        print(f"\n✗ Workflow execution failed: {e}")
        import traceback

        traceback.print_exc()

    gateway_base = AGENT_GATEWAY_URL.rsplit("/v1", 1)[0]
    print("\n" + "=" * 80)
    print("Integration Example Complete")
    print("=" * 80)
    print(
        f"\n📊 View telemetry in Langfuse: {session_manager.get_langfuse_trace_url(gateway_base)}"
    )
    print(f"🔍 Session thread_id: {session_context['thread_id']}")
    print(f"🌐 Gateway URL: {AGENT_GATEWAY_URL}")


if __name__ == "__main__":
    main()
