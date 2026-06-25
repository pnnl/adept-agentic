"""
This module is the core of the multi-agent orchestration system.

It is responsible for creating, managing, and executing multi-agent teams.
It has been refactored from the `mcp_server` to the `orchestration_service`
to centralize stateful logic.

Architectural Role:
-   **Multi-Agent Logic:** Contains all the logic for creating supervisor and
    worker agents, defining their roles, and constructing the LangGraph graphs
    that govern their interactions (both for 'router' and 'graph' execution modes).
-   **State Persistence:** All multi-agent session state is now persisted in the
    `multi_agent_sessions` table in PostgreSQL. This module defines the
    `get_session`, `save_session`, and `delete_session` functions that handle
    the pickling and database interaction.
-   **Tool Provisioning:** The `create_worker_agent` function is responsible for
    provisioning worker agents with a toolset that is correctly scoped to the
    original user's permissions. It receives the authorized tool configurations
    and uses the `external_tool_manager`'s factories to create the tool instances.
"""

import asyncio
import operator
import uuid
import os
import httpx
import json
import yaml
from typing import Annotated, Dict, Any, Optional, List, Tuple, TypedDict, Union
from functools import partial
from sqlalchemy import text, bindparam
from sqlalchemy.types import JSON
from pydantic import BaseModel, Field, ValidationError, validator

from ..logger_config import get_logger
from ..core.llm_agnostic_layer import LLMAgnosticClient
from .scientific_workflow.langchain_agent import ScientificWorkflowAgent
from .persistence import AsyncSessionLocal
from .persistence_v2 import AsyncPostgresSaver
from .hybrid_orchestration import hybrid_service  # Phase 4: Import shared checkpointer
from ..core.auth import AuthCredentials
from .scientific_workflow.orphaned_tool_calls_llm_wrapper import (
    OrphanedToolCallsLLMWrapper,
)

# Observability imports (Phase 1: Multi-Agent Teams Instrumentation)
from ..core.observability import observe
from ..core.observability_factory import ObservabilityFactory
from ..core.observability_callback import ObservabilityCallbackHandler

# LangGraph and LangChain imports
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent

# Import tool creation factories
from .external_tool_manager import _create_stdio_tool_from_config, _create_http_tool

logger = get_logger(__name__)

_llm_agnostic_client_instance: Optional[LLMAgnosticClient] = None

_HARDCODED_ROLE_ALIASES: Dict[str, str] = {
    "coding_agent": "coding_agent",
    "coder": "coding_agent",
    "developer": "coding_agent",
    "programmer": "coding_agent",
    "python_developer": "coding_agent",
    "software_engineer": "coding_agent",
}


def _resolve_catalog_path() -> str:
    """Resolve MODEL_CATALOG_PATH, falling back to package-relative lookup."""
    catalog_path = os.getenv("MODEL_CATALOG_PATH", "config/model_catalog.yaml")
    if os.path.isabs(catalog_path) or os.path.exists(catalog_path):
        return catalog_path
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(os.path.dirname(pkg_root))
    candidate = os.path.join(repo_root, catalog_path)
    return candidate if os.path.exists(candidate) else catalog_path


def _load_role_aliases_from_catalog() -> Dict[str, str]:
    """Load role-to-purpose aliases from the YAML model catalog."""
    catalog_path = _resolve_catalog_path()
    if not os.path.exists(catalog_path):
        return {}
    try:
        with open(catalog_path) as f:
            catalog = yaml.safe_load(f) or {}
        aliases = catalog.get("role_aliases", {})
        if not isinstance(aliases, dict):
            logger.warning(f"role_aliases in {catalog_path} is not a dict, ignoring")
            return {}
        if aliases:
            logger.info(f"Model catalog loaded {len(aliases)} role aliases from {catalog_path}")
        return aliases
    except Exception as e:
        logger.warning(f"Failed to load role aliases from {catalog_path}: {e}")
        return {}


def _load_llm_config_role_aliases() -> Dict[str, str]:
    """Load role aliases from llm.yaml when YAML config is active (highest priority)."""
    try:
        from ..core.llm_config import LLMConfig
        config = LLMConfig.load()
        if config.source == "yaml" and config.role_aliases:
            logger.info(f"LLM YAML config loaded {len(config.role_aliases)} role aliases")
            return config.role_aliases
    except ImportError:
        pass
    except FileNotFoundError as e:
        logger.warning(f"LLM YAML config file not found: {e}")
    except (ValueError, OSError) as e:
        logger.warning(f"LLM YAML config role aliases failed to load: {e}")
    return {}


# Merged role-to-purpose mapping. Priority: llm.yaml > model_catalog.yaml > hardcoded.
# Roles NOT in this dict fall back to "agent_main" via RolePersona.effective_llm_purpose
# — the catalog is additive, not restrictive. Any arbitrary role name works without config.
ROLE_NAME_TO_LLM_PURPOSE: Dict[str, str] = {
    **_HARDCODED_ROLE_ALIASES,
    **_load_role_aliases_from_catalog(),
    **_load_llm_config_role_aliases(),
}


def _load_purpose_descriptions() -> Dict[str, str]:
    """Load purpose descriptions from the YAML model catalog for prompt injection."""
    catalog_path = _resolve_catalog_path()
    if not os.path.exists(catalog_path):
        return {}
    try:
        with open(catalog_path) as f:
            catalog = yaml.safe_load(f) or {}
        return {
            name: config.get("description", "")
            for name, config in catalog.get("purposes", {}).items()
            if config.get("description")
        }
    except Exception:
        return {}


_PURPOSE_DESCRIPTIONS: Dict[str, str] = _load_purpose_descriptions()


def _sanitize_prompt_field(value: str, max_length: int = 100) -> str:
    """Strip control characters and enforce length limits for prompt-interpolated fields."""
    import re
    sanitized = re.sub(r'[\n\r\t\x00-\x1f]', ' ', value)
    sanitized = sanitized.strip()
    return sanitized[:max_length]


def _build_role_context(role_name: str, llm_purpose: str) -> str:
    """Build a role context block for the worker agent system prompt."""
    safe_role = _sanitize_prompt_field(role_name)
    safe_purpose = _sanitize_prompt_field(llm_purpose, max_length=64)
    desc = _PURPOSE_DESCRIPTIONS.get(llm_purpose, "")
    lines = [
        f"ROLE CONTEXT: You are operating as '{safe_role}'",
        f"  LLM Purpose: {safe_purpose}",
    ]
    if desc:
        lines.append(f"  Domain: {desc}")
    lines.append("")
    return "\n".join(lines) + "\n"


class RolePersona(BaseModel):
    """Enhanced role configuration with LLM and prompt customization.

    Enables fine-grained control over multi-agent worker configuration:
    - Custom LLM model selection per role via llm_purpose
    - Domain-specific system prompts with template merging
    - Backward compatible with simple string role names
    """

    name: str = Field(
        description="Role name (e.g., 'python_developer', 'security_auditor')",
        max_length=100,
    )
    llm_purpose: Optional[str] = Field(
        default=None,
        description="LLM purpose for this role (e.g., 'coding_agent', 'agent_main'). Defaults to 'agent_main'.",
        max_length=64,
    )

    @validator("name")
    def sanitize_name(cls, v):
        import re
        return re.sub(r'[\n\r\x00-\x1f]', ' ', v).strip()

    @validator("llm_purpose")
    def sanitize_purpose(cls, v):
        if v is None:
            return v
        import re
        return re.sub(r'[\n\r\x00-\x1f]', ' ', v).strip()
    system_prompt_template: Optional[str] = Field(
        default=None,
        description="""System prompt template with merge placeholders:
        - {role}: Replaced with role name
        - {base_instruction}: Replaced with default tool usage instruction
        - Custom content: Your domain-specific expertise/constraints
        Example: 'You are a {role} specializing in {domain}. {base_instruction}'
        """,
    )

    @property
    def effective_llm_purpose(self) -> str:
        """Returns llm_purpose with fallback to agent_main (general-purpose LLM)."""
        return self.llm_purpose or "agent_main"

    def get_merged_system_prompt(
        self,
        base_instruction: str = "You must use the provided tools to complete the tasks assigned to you.",
    ) -> str:
        """Merge system prompt template with role and base instruction.

        Args:
            base_instruction: Default tool usage instruction

        Returns:
            Merged system prompt with placeholders replaced
        """
        if not self.system_prompt_template:
            # Fallback to simple default
            return f"You are a world-class expert {self.name}. {base_instruction}"

        # Merge template with placeholders
        merged = self.system_prompt_template.format(
            role=self.name, base_instruction=base_instruction
        )
        return merged


class PlanStep(BaseModel):
    """A single step in a graph-mode execution plan."""

    step_id: str = Field(description="Unique step identifier (e.g., 'step_1')")
    description: str = Field(description="What this step accomplishes")
    assigned_role: str = Field(
        description="Role name responsible for this step"
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="step_ids that must complete before this step starts",
    )
    tools_hint: Optional[List[str]] = Field(
        default=None,
        description="Tool names this step is expected to use (informational)",
    )


class StructuredPlan(BaseModel):
    """A structured plan whose dependency graph compiles into a LangGraph StateGraph."""

    task: str = Field(description="The original task description")
    steps: List[PlanStep] = Field(description="Plan steps forming a DAG")
    synthesis_instruction: str = Field(
        default="Synthesize all step outputs into a comprehensive final report."
    )


# --- Constants ---
MAX_ROLES_PER_CLUSTER = 8


class AgentState(TypedDict):
    """The state representation for a multi-agent graph."""

    messages: List[BaseMessage]
    next: str
    task: str
    agent_turn_count: Dict[str, int]


async def agent_node(
    state: AgentState, agent: Any, name: str, thread_id: str
) -> Dict[str, Any]:
    """A node in the LangGraph that executes a single worker agent."""
    state["agent_turn_count"][name] = state["agent_turn_count"].get(name, 0) + 1
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [ObservabilityCallbackHandler()],
    }
    result = await agent.ainvoke(state, config=config)
    return {
        "messages": [AIMessage(content=result["messages"][-1].content, name=name)],
        "agent_turn_count": state["agent_turn_count"],
    }


def create_supervisor_graph(
    worker_agents: List[Tuple[Any, str, str]], supervisor_llm: Any
) -> Any:
    """
    Creates a stateful graph for the supervisor in 'graph' execution mode.
    """
    # CRITICAL FIX: Wrap LLM with orphaned tool_calls repair for graph mode supervisor
    wrapped_supervisor_llm = OrphanedToolCallsLLMWrapper(llm=supervisor_llm)
    logger.info(
        f"[MULTI_AGENT_MGR] Wrapped graph mode supervisor LLM with OrphanedToolCallsLLMWrapper"
    )

    members = [role for _, role, _ in worker_agents]
    system_prompt = (
        "You are a supervisor tasked with managing a conversation between the following workers: {members}. "
        "Given the user's request, determine which worker should act next. Each worker will perform a task and respond with their results and status. "
        "When the user's request is fully addressed, respond with the word FINISH."
    ).format(members=", ".join(members))

    options = ["FINISH"] + members
    function_def = {
        "name": "route",
        "description": "Select the next worker to act.",
        "parameters": {
            "title": "routeSchema",
            "type": "object",
            "properties": {"next": {"title": "Next", "anyOf": [{"enum": options}]}},
            "required": ["next"],
        },
    }
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt)])
    supervisor_chain = prompt | wrapped_supervisor_llm.with_structured_output(
        function_def, include_raw=False
    )

    workflow = StateGraph(AgentState)
    for agent, name, thread_id in worker_agents:
        node_function = partial(agent_node, agent=agent, name=name, thread_id=thread_id)
        workflow.add_node(name, node_function)

    workflow.add_node("supervisor", supervisor_chain)
    for member in members:
        workflow.add_edge(member, "supervisor")
    conditional_map = {k: k for k in members}
    conditional_map["FINISH"] = END
    workflow.add_conditional_edges("supervisor", lambda x: x["next"], conditional_map)
    workflow.set_entry_point("supervisor")

    # CRITICAL FIX: Add checkpointer for graph mode supervisor observability
    # Phase 4: Uses hybrid_service.checkpointer (shared singleton)
    # Thread ID format: {multi_agent_session_id}::supervisor_graph
    # Must be passed during ainvoke() via config={"configurable": {"thread_id": ...}}
    return workflow.compile(checkpointer=hybrid_service.checkpointer)


def create_tool_from_config(config: Dict[str, Any]) -> BaseTool:
    """Dynamically creates a LangChain tool from a configuration dictionary."""
    logger.debug(
        f"[MULTI_AGENT_MGR] Creating tool from config: name={config.get('name')}, type={config.get('type')}"
    )

    # Handle MCP tools (discovered from MCP servers)
    if config.get("type") == "mcp" or config.get("tool_type") == "mcp":
        # Recreate MCPToolWrapper from stored configuration
        from .scientific_workflow.mcp_langchain_tools import MCPToolWrapper
        import os

        logger.info(
            f"[MULTI_AGENT_MGR] Recreating MCP tool from config: {config.get('name')}"
        )

        # Map server names to URLs
        server_name = config.get("server", "mcp_server")
        server_url_map = {
            "mcp_server": os.getenv(
                "DEFAULT_MCP_SERVER_URL", "http://mcp_server:8080/"
            ),
            "hpc_mcp_server": os.getenv(
                "HPC_MCP_SERVER_URL", "http://hpc_mcp_server:8081/"
            ),
            "sandbox_mcp_server": os.getenv(
                "SANDBOX_MCP_SERVER_URL", "http://sandbox_mcp_server:8082/"
            ),
        }
        server_url = server_url_map.get(server_name, server_url_map["mcp_server"])

        # The tool name from discovery IS the actual tool name on the MCP server
        # For discovered tools, name = actual_tool_name
        actual_name = config.get("actual_tool_name", config["name"])

        # Recreate MCPToolWrapper with session context
        tool = MCPToolWrapper(
            name=config["name"],
            description=config.get("description", "MCP tool"),
            mcp_client_url=server_url,
            actual_tool_name=actual_name,
            mcp_session_id=config.get("mcp_session_id"),
        )

        logger.info(
            f"[MULTI_AGENT_MGR] Successfully recreated MCP tool: {tool.name} (actual: {tool.actual_tool_name}) with session_id={tool.mcp_session_id}"
        )
        return tool

    protocol = config.get("invocation", {}).get("protocol")
    if protocol == "stdio":
        return _create_stdio_tool_from_config(config)
    elif protocol == "http":
        return _create_http_tool(config)
    elif protocol == "mcp":
        # External MCP tools (e.g., OpenTrons) registered via tool_manager
        from .external_tool_manager import _create_mcp_tool

        return _create_mcp_tool(config)
    else:
        if config.get("type") == "external" and not protocol:
            logger.warning(
                f"[MULTI_AGENT_MGR] External tool '{config.get('name')}' has no invocation config, skipping"
            )
        else:
            logger.warning(
                f"[MULTI_AGENT_MGR] Unsupported tool protocol for worker agents: {protocol}"
            )
        return None


@observe(name="create_worker_agent", capture_input=True, capture_output=False)
async def create_worker_agent(
    role_persona: Union[str, RolePersona, Dict],
    mcp_session_id: str,
    multi_agent_session_id: str,
    authorized_tool_configs: List[Dict[str, Any]],
    user_credentials: Optional[AuthCredentials] = None,
    llm: Optional[Any] = None,
    llm_purpose_override: Optional[str] = None,
) -> Tuple[Any, str, str]:
    """
    Creates a worker agent with a toolset scoped to the user's permissions.

    This function is used by the multi-agent orchestration service to create
    worker agents with support for enhanced role personas.

    Parameters:
        role_persona: Role name (string for backward compatibility) or RolePersona object with custom LLM/prompt configuration
        mcp_session_id: The session ID for the MCP
        multi_agent_session_id: The session ID for the multi-agent
        authorized_tool_configs: The list of authorized tool configurations
        user_credentials: The user credentials for the agent
        llm: The LLM model to use for the agent (if None, creates based on llm_purpose)
        llm_purpose_override: Optional explicit LLM purpose override

    Returns:
        Tuple of (agent_graph, role_name, thread_id)
    """
    # Normalize role_persona to RolePersona object
    if isinstance(role_persona, str):
        persona = RolePersona(name=role_persona)
    elif isinstance(role_persona, dict):
        persona = RolePersona(**role_persona)
    else:
        persona = role_persona

    role_name = persona.name
    llm_purpose = llm_purpose_override or persona.effective_llm_purpose

    logger.info(
        f"[MULTI_AGENT_MGR] Creating worker agent for role={role_name}, llm_purpose={llm_purpose}, mcp_session_id={mcp_session_id}"
    )
    logger.info(
        f"[MULTI_AGENT_MGR] [OBSERVABILITY] Worker agent metadata: role={role_name}, llm_purpose={llm_purpose}, external_tool_count={len(authorized_tool_configs)}, multi_agent_session_id={multi_agent_session_id}"
    )
    logger.debug(
        f"[MULTI_AGENT_MGR] External tool configs count: {len(authorized_tool_configs)}, Has credentials: {bool(user_credentials)}"
    )

    # ENHANCED: Include role_name in thread_id for better observability and uniqueness
    # Thread ID format: {mcp_session_id}::{multi_agent_session_id}::{role_name}
    thread_id = f"{mcp_session_id}::{multi_agent_session_id}::{role_name}"
    logger.debug(f"[MULTI_AGENT_MGR] Worker thread_id: {thread_id}")

    # CRITICAL FIX: Get built-in MCP tools (28 tools including ExecuteCode)
    # Workers need the same built-in tools as main agents for full capability (plot generation, calculations, etc.)
    # Note: ScientificWorkflowAgent already imported at module level (line 35)

    worker_session_hierarchy = None  # Initialize before try block for use in ScientificWorkflowAgent.create()
    try:
        logger.info(f"[MULTI_AGENT_MGR] Getting built-in MCP tools for worker")
        # Build session_hierarchy for ExecuteCode context
        from .session_hierarchy import SessionHierarchy

        worker_session_hierarchy = SessionHierarchy(
            session_id=multi_agent_session_id,  # Use multi-agent session as base session for workers
            gateway_session_id=None,  # Not needed for workers
            multi_agent_session_id=multi_agent_session_id,
            mcp_session_id=mcp_session_id,
        )

        builtin_tools = ScientificWorkflowAgent.get_builtin_mcp_tools(
            mcp_session_id=mcp_session_id,
            user_credentials=user_credentials,
            session_hierarchy=worker_session_hierarchy,
        )
        logger.info(
            f"[MULTI_AGENT_MGR] Got {len(builtin_tools)} built-in MCP tools (includes ExecuteCode)"
        )
    except Exception as e:
        logger.error(
            f"[MULTI_AGENT_MGR] Failed to get built-in tools: {e}", exc_info=True
        )
        # Fallback to empty list if built-in tools fail (worker will have reduced capability)
        builtin_tools = []

    try:
        logger.info(
            f"[MULTI_AGENT_MGR] Creating {len(authorized_tool_configs)} external tools from configs"
        )
        # Add mcp_session_id to each tool config if it's an MCP tool
        for config in authorized_tool_configs:
            if config.get("type") == "mcp" or config.get("tool_type") == "mcp":
                config["mcp_session_id"] = mcp_session_id
        external_tools = [
            tool
            for tool in [
                create_tool_from_config(config) for config in authorized_tool_configs
            ]
            if tool is not None
        ]
        logger.info(
            f"[MULTI_AGENT_MGR] Successfully created {len(external_tools)} external tools"
        )
    except Exception as e:
        logger.error(
            f"[MULTI_AGENT_MGR] Failed to create external tools from configs: {e}",
            exc_info=True,
        )
        raise

    # COMBINE built-in + external tools
    # This ensures workers have ExecuteCode and all other essential tools PLUS user's authorized external tools
    combined_tools = builtin_tools + external_tools
    logger.info(
        f"[MULTI_AGENT_MGR] Combined {len(combined_tools)} total tools for worker ({len(builtin_tools)} built-in + {len(external_tools)} external)"
    )

    try:
        logger.info(
            f"[MULTI_AGENT_MGR] Creating ScientificWorkflowAgent for worker with thread_id={thread_id}"
        )
        agent = await ScientificWorkflowAgent.create(
            mcp_session_id=mcp_session_id,
            thread_id_override=thread_id,
            additional_tools=combined_tools,  # FIXED: Now includes built-in + external tools!
            user_credentials=user_credentials,
            session_hierarchy=worker_session_hierarchy,  # FIXED: Propagate session hierarchy for observability and auto-injection
        )
        logger.info(
            f"[MULTI_AGENT_MGR] ScientificWorkflowAgent created successfully for role={role_name} with {len(combined_tools)} total tools"
        )
    except Exception as e:
        logger.error(
            f"[MULTI_AGENT_MGR] Failed to create ScientificWorkflowAgent: {e}",
            exc_info=True,
        )
        raise

    # Create LLM with role-specific purpose if not provided
    if llm is None:
        logger.info(f"[MULTI_AGENT_MGR] Getting LLM for purpose '{llm_purpose}'")
        global _llm_agnostic_client_instance
        if _llm_agnostic_client_instance is None:
            logger.info(
                "[MULTI_AGENT_MGR] Lazy-initializing LLM client for worker agent"
            )
            _llm_agnostic_client_instance = LLMAgnosticClient()
        llm = _llm_agnostic_client_instance.get_langchain_chat_model(
            llm_purpose=llm_purpose
        )
        logger.debug(f"[MULTI_AGENT_MGR] LLM created for purpose '{llm_purpose}'")

    # Generate merged system prompt from persona template
    # SOLUTION #1: Include core system prompt from main agent for tool awareness
    # Note: ScientificWorkflowAgent already imported at module level (line 34)

    core_prompt = ScientificWorkflowAgent.get_core_system_prompt(
        thread_id=thread_id, mcp_session_id=mcp_session_id
    )
    # Prefix with tool awareness reminder so it appears early in the context window.
    # The core prompt already documents all tools in detail, but at 1700+ lines the
    # sandbox/MCP tool details can be lost in long contexts. This prefix ensures the
    # model sees the key constraint immediately.
    tool_awareness_prefix = (
        "IMPORTANT: You have pre-configured tools available. Do NOT attempt to "
        "'set up', 'configure', or 'install' anything — just call the tools directly.\n"
        "Key tools: execute_code (Python/JS/shell sandbox with common packages), "
        "query_rag_index (query by index_id), list_rag_indexes, list_uploaded_files, "
        "perform_calculation.\n\n"
    )
    role_context = _build_role_context(role_name, llm_purpose)
    base_instruction = f"""{tool_awareness_prefix}{role_context}{core_prompt}

You must use the provided tools to complete the tasks assigned to you."""
    merged_prompt_text = persona.get_merged_system_prompt(base_instruction)
    prompt = SystemMessage(content=merged_prompt_text)

    logger.debug(
        f"[MULTI_AGENT_MGR] System prompt for {role_name}: {merged_prompt_text[:100]}..."
    )

    try:
        logger.info(
            f"[MULTI_AGENT_MGR] Creating react agent graph for role={role_name} with {len(agent.tools)} tools"
        )

        # CRITICAL FIX: Wrap LLM with orphaned tool_calls repair for react agents
        # React agents bypass graph_builder.py's call_model() fix, so we must wrap the LLM
        wrapped_llm = OrphanedToolCallsLLMWrapper(llm=llm)
        logger.info(
            f"[MULTI_AGENT_MGR] Wrapped LLM with OrphanedToolCallsLLMWrapper for role={role_name}"
        )

        agent_graph = create_react_agent(
            model=wrapped_llm, tools=agent.tools, prompt=prompt
        )
        logger.info(
            f"[MULTI_AGENT_MGR] Successfully created worker agent graph for role={role_name}"
        )
    except Exception as e:
        logger.error(
            f"[MULTI_AGENT_MGR] Failed to create react agent graph: {e}", exc_info=True
        )
        raise

    return agent_graph, role_name, thread_id


class AgentRunnerTool(BaseTool):
    """A tool that allows the supervisor to run a worker agent."""

    agent_executor: Any
    name: str
    description: str
    thread_id: str

    async def _arun(self, task: str) -> str:
        """Runs the agent with the given task asynchronously."""
        logger.info(f"Supervisor delegating task to {self.name}: {task}")
        try:
            final_state = {}
            config = {
                "configurable": {"thread_id": self.thread_id},
                "recursion_limit": 50,  # Explicit (default 25 ≈ 8 tool turns)
                "callbacks": [ObservabilityCallbackHandler()],
            }
            # Fix 8 (Session 60): Use stream_mode="values" to get full
            # accumulated state after each node, not incremental deltas.
            # Default "updates" mode yields only the messages added by each
            # node step, so final_state would contain only the last node's
            # output (1 message). "values" mode yields the complete message
            # history at each step, giving us the full execution trace.
            async for state in self.agent_executor.astream(
                {"messages": [HumanMessage(content=task)]},
                config=config,
                stream_mode="values",
            ):
                final_state = state

            # Fix 7 (Session 60): Extract messages from astream state.
            # create_react_agent().astream() yields state keyed by node name
            # (e.g., {'agent': {'messages': [...]}}) rather than by state field
            # ({'messages': [...]}). Try top-level first, then fall through to
            # node-keyed extraction.
            messages = final_state.get("messages", [])
            if not messages:
                for node_key in ("agent", "tools"):
                    node_state = final_state.get(node_key, {})
                    if isinstance(node_state, dict) and "messages" in node_state:
                        messages = node_state["messages"]
                        break
            logger.debug(
                f"[MULTI_AGENT_MGR] Worker '{self.name}' astream final_state: "
                f"keys={list(final_state.keys()) if final_state else '(empty)'}, "
                f"extracted_messages={len(messages)}"
            )

            # Fix 5 (Session 60): Tool-call observability logging + soft annotation
            # Placed BEFORE early return guard so it always fires
            tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
            tool_call_count = sum(
                len(getattr(m, "tool_calls", []))
                for m in messages
                if isinstance(m, AIMessage)
            )
            logger.info(
                f"[MULTI_AGENT_MGR] Worker '{self.name}' execution summary: "
                f"tool_calls_issued={tool_call_count}, tool_responses={len(tool_messages)}, "
                f"total_messages={len(messages)}, task='{task[:80]}...'"
            )

            if not messages or len(messages) <= 1:
                logger.warning(
                    f"[MULTI_AGENT_MGR] Worker '{self.name}' produced no meaningful "
                    f"output (messages={len(messages)}, state_keys={list(final_state.keys())})"
                )
                return (
                    f"The {self.name} agent produced no meaningful output for the task."
                )

            report_parts = [f"Execution trace for worker agent '{self.name}':"]
            last_tool_name = "unknown_tool"
            for msg in messages[1:]:
                if isinstance(msg, AIMessage):
                    if msg.content:
                        thought = msg.content.replace("\n", " ").strip()
                        if thought:
                            report_parts.append(f"  - Thought: {thought}")
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            last_tool_name = tc.get("name", "unknown_tool")
                            report_parts.append(
                                f"  - Action: Calling tool `{last_tool_name}` with arguments `{tc.get('args', {})}`."
                            )
                elif isinstance(msg, ToolMessage):
                    observation = str(msg.content).replace("\n", " ").strip()
                    if len(observation) > 300:
                        observation = observation[:300] + "..."
                    report_parts.append(
                        f"  - Observation from `{last_tool_name}`: {observation}"
                    )

            final_answer_msg = messages[-1]
            if isinstance(final_answer_msg, AIMessage) and (
                not hasattr(final_answer_msg, "tool_calls")
                or not final_answer_msg.tool_calls
            ):
                report_parts.append(
                    f"\nFinal Answer from worker: {final_answer_msg.content}"
                )

            if not tool_messages:
                logger.warning(
                    f"[MULTI_AGENT_MGR] Worker '{self.name}' completed with 0 tool invocations. "
                    f"Task: {task[:100]}..."
                )
                # Soft annotation — supervisor can factor this in, not a hard block
                report_parts.insert(
                    0,
                    f"[Note: Worker '{self.name}' responded without invoking any tools. "
                    f"If this step required data retrieval or code execution, "
                    f"the output may be unverified.]",
                )

            return "\n".join(report_parts)
        except Exception as e:
            logger.error(
                f"Worker agent {self.name} failed to execute task '{task[:50]}...'. Error: {e}",
                exc_info=True,
            )
            return f"The {self.name} agent FAILED to complete the task. Error: {e}"

    def _run(self, task: str) -> str:
        """Synchronous version of _run - calls the async version."""
        import asyncio

        try:
            # Use the existing event loop if available, otherwise create new one
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._arun(task))
        except RuntimeError:
            # If no event loop is running, create a new one
            return asyncio.run(self._arun(task))


def create_planner_agent(
    roles: List[str], llm: Optional[LLMAgnosticClient] = None
) -> Any:
    """Creates the planner agent for the 'router' execution mode."""
    if llm is None:
        llm_client = LLMAgnosticClient()
        llm = llm_client.get_langchain_chat_model(llm_purpose="agent_planner")

    # CRITICAL FIX: Wrap LLM with orphaned tool_calls repair for planner
    # Even though planner has no tools, wrap for consistency and safety
    wrapped_llm = OrphanedToolCallsLLMWrapper(llm=llm)
    logger.info(
        f"[MULTI_AGENT_MGR] Wrapped planner LLM with OrphanedToolCallsLLMWrapper"
    )

    role_descriptions = ", ".join(roles)
    planner_prompt = (
        "You are an expert planner. Your job is to create a detailed, step-by-step plan "
        "to answer a user's request.\n\n"
        "Available team members: {roles}\n\n"
        "CRITICAL CONTEXT — PRE-CONFIGURED TOOLS (NO setup needed):\n"
        "Each team member has these MCP tools ready to call immediately:\n"
        "- execute_code: Run Python/JS/shell code in an isolated sandbox. Pre-installed "
        "packages include matplotlib, seaborn, pandas, numpy, scipy, scikit-learn. "
        "Additional packages are installed automatically on first use. NO environment "
        "setup required — just call the tool with code.\n"
        "- query_rag_index(index_id, query): Query an existing RAG index by name. "
        "NO configuration needed — provide the index_id and a natural language query.\n"
        "- list_rag_indexes: List all available RAG indexes in the session.\n"
        "- list_uploaded_files: List files available in the current session.\n"
        "- register_local_file: Register a filesystem file for processing.\n"
        "- perform_calculation: Run mathematical calculations in the sandbox.\n"
        "- websearch, uniprot_search, pubchem_search, blastp_biopython, "
        "blastn_biopython: Domain-specific search and bioinformatics tools.\n\n"
        "PLANNING RULES:\n"
        "1. NEVER include steps to 'set up', 'configure', 'install', or 'prepare' "
        "the environment, tools, or dependencies. All tools are pre-configured.\n"
        "2. NEVER include steps to install Python packages. The sandbox handles this "
        "automatically.\n"
        "3. Start plans with the actual work — querying data, writing code, "
        "analyzing results — not with setup or configuration steps.\n"
        "4. Each step should directly produce work output (code, analysis, data) "
        "by calling tools, not configure infrastructure.\n\n"
        "For each step, specify which expert role should perform the task. "
        "If you are given feedback on a plan, you must refine the plan to address "
        "the feedback. The plan will be executed by a supervisor agent. Do not try "
        "to execute the plan yourself or generate a final answer. "
        "Your only output should be the plan."
    ).format(roles=role_descriptions)
    return create_react_agent(
        model=wrapped_llm, tools=[], prompt=SystemMessage(content=planner_prompt)
    )


def create_graph_planner_agent(
    roles: List[str],
    role_tool_descriptions: Optional[Dict[str, List[str]]] = None,
    llm: Optional[Any] = None,
) -> Any:
    """Creates a planner agent for graph execution mode that outputs StructuredPlan JSON.

    The planner generates a dependency-aware plan where each step specifies which role
    handles it and which prior steps it depends on. Independent steps (no dependencies)
    will be executed in parallel by the plan-to-graph compiler.

    Args:
        roles: Available role names for assignment.
        role_tool_descriptions: Optional mapping of role name -> list of tool description
            strings, used to inform the planner about each role's capabilities.
        llm: Optional pre-configured LLM. If None, creates one with agent_planner purpose.

    Returns:
        A runnable planner agent.
    """
    if llm is None:
        llm_client = LLMAgnosticClient()
        llm = llm_client.get_langchain_chat_model(llm_purpose="agent_planner")

    wrapped_llm = OrphanedToolCallsLLMWrapper(llm=llm)
    logger.info(
        "[MULTI_AGENT_MGR] Wrapped graph planner LLM with OrphanedToolCallsLLMWrapper"
    )

    # Build role descriptions block
    role_lines = []
    for role in roles:
        tools_desc = ""
        if role_tool_descriptions and role in role_tool_descriptions:
            tools_desc = f" (tools: {', '.join(role_tool_descriptions[role][:5])})"
        role_lines.append(f"  - {role}{tools_desc}")
    roles_block = "\n".join(role_lines)

    planner_prompt = f"""You are an expert task planner for multi-agent teams. Your job is to decompose a user's request into a structured execution plan.

Available roles:
{roles_block}

You MUST output a valid JSON object matching this schema:
{{
  "task": "<the original task description>",
  "steps": [
    {{
      "step_id": "step_1",
      "description": "What this step accomplishes",
      "assigned_role": "<one of the available roles>",
      "depends_on": [],
      "tools_hint": ["optional_tool_name"]
    }},
    {{
      "step_id": "step_2",
      "description": "Analyze results from step 1",
      "assigned_role": "<role>",
      "depends_on": ["step_1"],
      "tools_hint": null
    }}
  ],
  "synthesis_instruction": "How to combine all step outputs into a final report."
}}

CRITICAL RULES:
1. Each step MUST be assigned to exactly one of the available roles.
2. Use `depends_on` ONLY when a step truly needs another step's output. Steps with empty depends_on run in parallel.
3. Maximize parallelism: if two steps are independent, do NOT add artificial dependencies.
4. Step IDs must be unique strings (e.g., "step_1", "step_2", ...).
5. The dependency graph must be a DAG (no cycles).
6. Output ONLY the JSON object, no other text or markdown formatting.
7. If you are given feedback on a plan, refine it and output the updated JSON."""

    return create_react_agent(
        model=wrapped_llm,
        tools=[],
        prompt=SystemMessage(content=planner_prompt),
    )


def cluster_roles(
    personas: List[RolePersona],
    max_per: int = MAX_ROLES_PER_CLUSTER,
) -> List[List[RolePersona]]:
    """Group roles into clusters for hierarchical supervision.

    When a team has more roles than max_per, roles are split into sub-teams.
    Each sub-team gets its own sub-supervisor, and the top-level planner
    assigns work to teams rather than individual roles.

    Args:
        personas: List of role personas to cluster.
        max_per: Maximum roles per cluster (default: 8).

    Returns:
        List of clusters (each a list of RolePersona).
    """
    if len(personas) <= max_per:
        return [personas]
    return [personas[i : i + max_per] for i in range(0, len(personas), max_per)]


def build_plan_state_class(plan: StructuredPlan) -> type:
    """Dynamically build a TypedDict whose fields reflect the plan structure.

    Each plan step gets a dedicated result field (result_step_1, result_step_2, etc.)
    so that downstream nodes can read exactly the upstream outputs they need.

    Falls back to a fixed schema with step_results dict if dynamic TypedDict
    causes issues with LangGraph checkpointer serialization.
    """
    annotations = {
        "messages": Annotated[List[BaseMessage], operator.add],
        "task": str,
    }
    for step in plan.steps:
        annotations[f"result_{step.step_id}"] = Optional[str]

    # Create the TypedDict dynamically
    return TypedDict("PlanExecutionState", annotations)


def make_step_node(step: PlanStep, worker_agent: Any, worker_thread_id: str):
    """Create a node function for a single plan step, bound to its worker agent.

    The returned async callable:
    1. Gathers context from upstream dependency results in the state.
    2. Constructs a prompt combining the step description and upstream context.
    3. Invokes the worker agent (which carries its own tool set).
    4. Returns the result in both the messages list and a dedicated state field.
    """

    async def step_node(state: dict) -> dict:
        import time

        step_start = time.time()
        logger.info(
            f"[MULTI_AGENT_MGR] Step '{step.step_id}' ({step.assigned_role}) STARTING — "
            f"deps={step.depends_on}, thread={worker_thread_id}"
        )

        # Gather context from upstream dependencies
        context_parts = []
        for dep_id in step.depends_on:
            dep_result = state.get(f"result_{dep_id}")
            if dep_result:
                context_parts.append(f"[Output from {dep_id}]: {dep_result}")

        logger.info(
            f"[MULTI_AGENT_MGR] Step '{step.step_id}' gathered {len(context_parts)} upstream results "
            f"(total context: {sum(len(c) for c in context_parts)} chars)"
        )

        prompt = f"Your task: {step.description}"
        if context_parts:
            prompt += "\n\nContext from previous steps:\n" + "\n".join(
                context_parts
            )

        config = {
            "configurable": {"thread_id": worker_thread_id},
            "callbacks": [ObservabilityCallbackHandler()],
        }
        try:
            result = await worker_agent.ainvoke(
                {"messages": [HumanMessage(content=prompt)]}, config=config
            )
            result_content = result["messages"][-1].content
            step_duration_ms = int((time.time() - step_start) * 1000)
            logger.info(
                f"[MULTI_AGENT_MGR] Step '{step.step_id}' ({step.assigned_role}) COMPLETE — "
                f"{step_duration_ms}ms, result_length={len(result_content)}"
            )
        except Exception as e:
            step_duration_ms = int((time.time() - step_start) * 1000)
            logger.error(
                f"[MULTI_AGENT_MGR] Step '{step.step_id}' ({step.assigned_role}) FAILED — "
                f"{step_duration_ms}ms, error={e}",
                exc_info=True,
            )
            result_content = f"Step {step.step_id} failed with error: {e}"

        return {
            "messages": [
                AIMessage(content=result_content, name=step.assigned_role)
            ],
            f"result_{step.step_id}": result_content,
        }

    step_node.__name__ = f"step_node_{step.step_id}"
    return step_node


def make_synthesis_node(plan: StructuredPlan, supervisor_llm: Any):
    """Create the final synthesis node that combines all step outputs.

    The synthesis node reads per-step result fields from the state, assembles
    them with the original task and synthesis instruction, and invokes the
    supervisor LLM to produce a coherent final report.
    """

    async def synthesis_node(state: dict) -> dict:
        import time

        synth_start = time.time()
        logger.info(
            f"[MULTI_AGENT_MGR] Synthesis STARTING — "
            f"assembling {len(plan.steps)} step results"
        )

        parts = [f"Task: {state.get('task', plan.task)}\n"]
        step_output_lengths = {}
        for step in plan.steps:
            result = state.get(f"result_{step.step_id}", "(no output)")
            parts.append(
                f"--- {step.step_id} ({step.assigned_role}) ---\n{result}\n"
            )
            step_output_lengths[step.step_id] = (
                len(result) if result != "(no output)" else 0
            )
        parts.append(f"\n{plan.synthesis_instruction}")

        logger.info(
            f"[MULTI_AGENT_MGR] Synthesis assembled — "
            f"output lengths: {step_output_lengths}, "
            f"total prompt: {sum(len(p) for p in parts)} chars"
        )

        response = await supervisor_llm.ainvoke(
            [
                SystemMessage(
                    content="You are synthesizing results from a team of specialists into a comprehensive report."
                ),
                HumanMessage(content="\n".join(parts)),
            ]
        )

        synth_duration_ms = int((time.time() - synth_start) * 1000)
        logger.info(
            f"[MULTI_AGENT_MGR] Synthesis COMPLETE — "
            f"{synth_duration_ms}ms, report_length={len(response.content)}"
        )

        return {
            "messages": [AIMessage(content=response.content, name="supervisor")]
        }

    synthesis_node.__name__ = "synthesis_node"
    return synthesis_node


def compile_plan_to_graph(
    plan: StructuredPlan,
    workers: Dict[str, Tuple[Any, str]],
    supervisor_llm: Any,
) -> Any:
    """Compile a StructuredPlan into a LangGraph StateGraph.

    The plan's dependency DAG becomes the graph topology:
    - Each step -> a node (bound to its worker agent + tools)
    - depends_on -> edges
    - Steps with no deps -> edges from START (run in parallel)
    - Terminal steps (nothing depends on them) -> edges to synthesize node

    Args:
        plan: The structured plan defining steps and dependencies.
        workers: Mapping of role_name -> (agent, thread_id).
        supervisor_llm: LLM for the synthesis node.

    Returns:
        A compiled LangGraph graph ready for ainvoke().

    Raises:
        ValueError: If a step references an unknown role or dependency.
    """
    logger.info(
        f"[MULTI_AGENT_MGR] compile_plan_to_graph: "
        f"{len(plan.steps)} steps, {len(workers)} workers, "
        f"task='{plan.task[:80]}'"
    )

    PlanState = build_plan_state_class(plan)
    workflow = StateGraph(PlanState)

    # Validate and add step nodes
    step_ids = {s.step_id for s in plan.steps}
    for step in plan.steps:
        if step.assigned_role not in workers:
            raise ValueError(
                f"Plan step '{step.step_id}' assigned to unknown role '{step.assigned_role}'. "
                f"Available roles: {list(workers.keys())}"
            )
        agent, thread_id = workers[step.assigned_role]
        workflow.add_node(
            step.step_id, make_step_node(step, agent, thread_id)
        )
        logger.info(
            f"[MULTI_AGENT_MGR]   Added node '{step.step_id}' -> role='{step.assigned_role}'"
        )

    # Add synthesis node
    workflow.add_node("synthesize", make_synthesis_node(plan, supervisor_llm))

    # Wire edges from dependency graph
    for step in plan.steps:
        if not step.depends_on:
            # No dependencies -> run from START (parallel with other root nodes)
            workflow.add_edge(START, step.step_id)
            logger.info(
                f"[MULTI_AGENT_MGR]   Edge: START -> '{step.step_id}' (root node, parallel eligible)"
            )
        else:
            for dep_id in step.depends_on:
                if dep_id not in step_ids:
                    raise ValueError(
                        f"Step '{step.step_id}' depends on unknown step '{dep_id}'. "
                        f"Known steps: {step_ids}"
                    )
                workflow.add_edge(dep_id, step.step_id)
                logger.info(
                    f"[MULTI_AGENT_MGR]   Edge: '{dep_id}' -> '{step.step_id}'"
                )

    # Terminal steps (no other step depends on them) -> synthesize
    all_deps = {d for s in plan.steps for d in s.depends_on}
    terminals = [s.step_id for s in plan.steps if s.step_id not in all_deps]
    logger.info(
        f"[MULTI_AGENT_MGR]   Terminal nodes -> synthesize: {terminals}"
    )
    for t in terminals:
        workflow.add_edge(t, "synthesize")

    workflow.add_edge("synthesize", END)

    compiled = workflow.compile(checkpointer=hybrid_service.checkpointer)
    logger.info(
        f"[MULTI_AGENT_MGR] compile_plan_to_graph complete: "
        f"{len(plan.steps)} step nodes + synthesize, graph compiled"
    )
    return compiled


def parse_structured_plan(
    plan_text: str, session_data: Dict[str, Any]
) -> StructuredPlan:
    """Parse LLM-generated plan text into a StructuredPlan.

    Attempts JSON parsing first. If that fails, falls back to wrapping the
    free-text plan as a single sequential step assigned to the first role.

    Args:
        plan_text: Raw plan text from the planner LLM.
        session_data: Session data for fallback role extraction.

    Returns:
        A validated StructuredPlan instance.
    """
    logger.info(
        f"[MULTI_AGENT_MGR] parse_structured_plan: "
        f"input_length={len(plan_text)}, "
        f"starts_with_fence={'```' in plan_text[:10]}"
    )

    # Try to extract JSON from markdown code blocks if present
    cleaned = plan_text.strip()
    if cleaned.startswith("```"):
        # Strip markdown code fences
        lines = cleaned.split("\n")
        # Remove first line (```json or ```) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        cleaned = "\n".join(lines).strip()

    try:
        plan_dict = json.loads(cleaned)
        plan = StructuredPlan(**plan_dict)
        logger.info(
            f"[MULTI_AGENT_MGR] Parsed structured plan from JSON: "
            f"{len(plan.steps)} steps, "
            f"roles={[s.assigned_role for s in plan.steps]}"
        )
        return plan
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning(
            f"[MULTI_AGENT_MGR] Failed to parse structured plan JSON ({e}), "
            "falling back to single-step plan"
        )
        # Fallback: wrap free-text plan as a single step
        role_personas = session_data.get("role_personas", [])
        roles = session_data.get("roles", [])
        first_role = (
            role_personas[0].get("name", roles[0])
            if role_personas
            else (roles[0] if roles else "worker")
        )
        return StructuredPlan(
            task=session_data.get("pending_plan", {}).get("task", ""),
            steps=[
                PlanStep(
                    step_id="step_1",
                    description=plan_text,
                    assigned_role=first_role,
                    depends_on=[],
                )
            ],
        )


def create_router_supervisor_agent(
    worker_agents: List[Tuple[Any, str, str]],
    session_id: str,
    llm: Optional[LLMAgnosticClient] = None,
) -> Any:
    """Creates the supervisor agent for the 'router' execution mode."""
    if llm is None:
        llm_client = LLMAgnosticClient()
        llm = llm_client.get_langchain_chat_model(llm_purpose="agent_main")

    # CRITICAL FIX: Wrap LLM with orphaned tool_calls repair for router supervisor
    # Router supervisor uses create_react_agent which bypasses graph_builder.py's fix
    wrapped_llm = OrphanedToolCallsLLMWrapper(llm=llm)
    logger.info(
        f"[MULTI_AGENT_MGR] Wrapped supervisor LLM with OrphanedToolCallsLLMWrapper for session={session_id}"
    )

    worker_tools = [
        AgentRunnerTool(
            name=f"run_{role.lower().replace(' ', '_')}_agent",
            description=f"Use this tool to delegate a specific task to the {role} expert. Provide a clear and complete description of the task for the expert.",
            agent_executor=executor,
            thread_id=thread_id,
        )
        for executor, role, thread_id in worker_agents
    ]
    system_prompt = (
        "You are a supervisor agent. Your job is to orchestrate a team of expert agents to complete a user's request. "
        "You have two primary modes: plan execution and plan review. "
        "If you are given a plan to execute, you must delegate each step to the appropriate expert agent using your tools. Do not deviate from the plan. After executing all steps, synthesize the results into a single, comprehensive final report. "
        "If you are asked to review a plan, you must delegate the review task to each of the worker agents to get their feedback. Synthesize their feedback into a single, coherent review. "
        "If a worker agent returns a message indicating it FAILED, you must acknowledge this failure. "
        "Analyze the error message. If the error suggests missing information that the user could provide (e.g., an ambiguous term, a missing file ID), "
        "your final report should clearly state the failure and ask the user for the specific information needed to resolve the issue. "
        "Otherwise, simply report the failure as part of the final results. "
        "Do not use your own knowledge; rely solely on the outputs of the worker agents."
    )
    # CRITICAL FIX: Supervisor uses shared PostgreSQL checkpointer with dedicated thread_id
    # Phase 4: Uses hybrid_service.checkpointer (shared singleton) instead of creating
    # new AsyncPostgresSaver() instances. State isolation is achieved via unique thread_ids,
    # not separate checkpointer instances. This reduces DB connections by 4 per multi-agent
    # session (2 supervisors × 2 connections each).
    # Thread ID format: {multi_agent_session_id}::supervisor
    # NOTE: thread_id is passed during ainvoke() via config, not during agent creation
    return create_react_agent(
        model=wrapped_llm,  # Use wrapped LLM
        tools=worker_tools,
        prompt=SystemMessage(content=system_prompt),
        checkpointer=hybrid_service.checkpointer,  # Phase 4: Shared singleton
    )


# --- New PostgreSQL based Session Management ---


async def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a session object from the PostgreSQL database (JSON format)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT session_data FROM multi_agent_sessions WHERE session_id = :session_id"
            ),
            {"session_id": session_id},
        )
        row = result.fetchone()
        if row:
            # Handle both cases: dict (already deserialized by asyncpg) or string/bytes
            data = row[0]
            if isinstance(data, dict):
                return data
            elif isinstance(data, (str, bytes)):
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                return json.loads(data)
            else:
                logger.error(f"Unexpected data type for session_data: {type(data)}")
                return None
    return None


async def save_session(session_id: str, session_data: Dict[str, Any]):
    """Saves (upserts) a session object to the PostgreSQL database (JSON format stored as BYTEA)."""
    async with AsyncSessionLocal() as session:
        # Convert dict to JSON string
        # asyncpg will automatically handle the conversion to BYTEA
        import json

        json_str = json.dumps(session_data)

        await session.execute(
            text("""
                INSERT INTO multi_agent_sessions (session_id, session_data)
                VALUES (:session_id, :session_data)
                ON CONFLICT (session_id) DO UPDATE SET session_data = EXCLUDED.session_data;
            """),
            {"session_id": session_id, "session_data": json_str},
        )
        await session.commit()


async def delete_session(session_id: str):
    """Deletes a session object from the PostgreSQL database."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM multi_agent_sessions WHERE session_id = :session_id"),
            {"session_id": session_id},
        )
        await session.commit()


# --- Refactored Tool Implementations ---
# These will be called by the ScientificWorkflowAgent's new local tools.


@observe(name="create_multi_agent_session", capture_input=True, capture_output=True)
async def create_multi_agent_session_impl(
    roles: Union[List[str], List[Union[str, RolePersona]]],
    mcp_session_id: str,
    authorized_tool_configs: List[Dict[str, Any]],
    execution_mode: str,
    user_credentials: AuthCredentials,
) -> Dict[str, Any]:
    """
    Core implementation for creating a new multi-agent session.

    Args:
        roles: List of roles (strings for simple usage) or RolePersona objects with custom LLM/prompt configuration
        mcp_session_id: MCP session ID for tool execution (will be generated if None)
        authorized_tool_configs: List of authorized tool configurations
        execution_mode: Execution mode ('router' or 'graph')
        user_credentials: User authentication credentials

    Returns:
        Dict with status and multi_agent_session_id
    """
    session_id = f"multi-agent:{uuid.uuid4()}"

    # Use session_id if mcp_session_id not provided (e.g., when called without parent session)
    # CRITICAL: Phase 1 E2E fix - ensure mcp_session_id is always present for observability
    if not mcp_session_id:
        mcp_session_id = session_id
        logger.info(
            f"[MULTI_AGENT_MGR] Using session_id as mcp_session_id: {mcp_session_id} (no parent session)"
        )

    # Normalize roles to RolePersona objects for backward compatibility
    # Auto-map well-known role names to LLM purposes when llm_purpose is not explicit
    normalized_personas = []
    for role in roles:
        if isinstance(role, str):
            auto_purpose = ROLE_NAME_TO_LLM_PURPOSE.get(role)
            if auto_purpose:
                logger.info(
                    f"[MULTI_AGENT_MGR] Auto-mapped role '{role}' to llm_purpose='{auto_purpose}'"
                )
            normalized_personas.append(
                {"name": role, "llm_purpose": auto_purpose, "system_prompt_template": None}
            )
        elif isinstance(role, dict):
            # Auto-map if dict has no explicit llm_purpose
            if not role.get("llm_purpose"):
                auto_purpose = ROLE_NAME_TO_LLM_PURPOSE.get(role.get("name", ""))
                if auto_purpose:
                    role = {**role, "llm_purpose": auto_purpose}
                    logger.info(
                        f"[MULTI_AGENT_MGR] Auto-mapped role '{role['name']}' to llm_purpose='{auto_purpose}'"
                    )
            normalized_personas.append(role)
        elif isinstance(role, RolePersona):
            dumped = role.model_dump()
            # Auto-map if RolePersona has no explicit llm_purpose
            if not dumped.get("llm_purpose"):
                auto_purpose = ROLE_NAME_TO_LLM_PURPOSE.get(dumped.get("name", ""))
                if auto_purpose:
                    dumped["llm_purpose"] = auto_purpose
                    logger.info(
                        f"[MULTI_AGENT_MGR] Auto-mapped role '{dumped['name']}' to llm_purpose='{auto_purpose}'"
                    )
            normalized_personas.append(dumped)
        else:
            logger.warning(
                f"[MULTI_AGENT_MGR] Unexpected role type: {type(role)}, converting to string"
            )
            role_str = str(role)
            auto_purpose = ROLE_NAME_TO_LLM_PURPOSE.get(role_str)
            normalized_personas.append(
                {"name": role_str, "llm_purpose": auto_purpose, "system_prompt_template": None}
            )

    role_names = [p["name"] for p in normalized_personas]
    logger.info(
        f"[MULTI_AGENT_MGR] Creating new {execution_mode} session {session_id} for roles: {role_names}"
    )
    logger.info(
        f"[MULTI_AGENT_MGR] MCP session: {mcp_session_id}, External tool configs: {len(authorized_tool_configs)}, Has credentials: {bool(user_credentials)}"
    )

    # NOTE: Built-in MCP tools (28 tools including ExecuteCode) will be added dynamically
    # when creating worker agents in create_worker_agent(). We don't store them in session_data
    # because they're not serializable and should be created fresh for each worker.

    # Track session creation event (Phase 1: Multi-Agent Teams Instrumentation)
    try:
        logger.info(
            f"[MULTI_AGENT_MGR] Starting observability tracking for session {session_id}"
        )
        obs_factory = ObservabilityFactory()
        logger.debug(
            f"[MULTI_AGENT_MGR] ObservabilityFactory created, calling track_session..."
        )
        await obs_factory.track_session(
            session_id=session_id,
            mcp_session_id=mcp_session_id,
            multi_agent_session_id=session_id,  # This IS the multi-agent session
            metadata={
                "session_type": f"multi_agent_{execution_mode}",  # Moved to metadata
                "execution_mode": execution_mode,  # Promoted to top-level
                "mcp_session_id": mcp_session_id,  # Promoted to top-level (explicit)
                "user_id": user_credentials.user_id if user_credentials else None,
                "groups": user_credentials.groups if user_credentials else [],
                "roles": role_names,  # Promoted to top-level
                "role_count": len(role_names),  # Promoted to top-level
                "authorized_tools_count": len(
                    authorized_tool_configs
                ),  # External tools (built-in added per-worker)
                "personas": normalized_personas,  # Promoted to top-level
                # Keep nested for backward compatibility
                "team_composition": {
                    "roles": role_names,
                    "execution_mode": execution_mode,
                    "role_count": len(role_names),
                    "authorized_tools_count": len(authorized_tool_configs),
                    "personas": normalized_personas,
                },
            },
        )
        logger.debug(f"[MULTI_AGENT_MGR] track_session completed, calling flush...")
        # Flush traces immediately after session creation to ensure they reach the database
        await obs_factory.flush()
        logger.info(
            f"[MULTI_AGENT_MGR] Observability tracking and flush completed for session {session_id}"
        )
    except Exception as obs_error:
        # Observability errors should not crash the application
        logger.warning(
            f"[MULTI_AGENT_MGR] Observability tracking failed: {obs_error}",
            exc_info=True,
        )

    # Store ONLY serializable configuration data, not live objects
    # Do NOT create agents during session creation - they will be created on-demand
    session_data = {
        "role_personas": normalized_personas,  # NEW: Store full persona config
        "roles": role_names,  # LEGACY: Keep for backward compatibility
        "execution_mode": execution_mode,
        "mcp_session_id": mcp_session_id,
        "authorized_tool_configs": authorized_tool_configs,  # External tools only (built-in added dynamically)
        "user_credentials_dict": (
            user_credentials.model_dump() if user_credentials else None
        ),
        "chat_history": [],
        "pending_plan": None,
    }

    # All agents (worker, supervisor, planner) will be created on-demand when needed
    # This completely eliminates the pickle serialization issue

    # Save session data using JSON serialization (no pickle needed)
    # Only storing serializable configuration data, not live objects
    logger.info(
        f"[MULTI_AGENT_MGR] Saving multi-agent session with JSON serialization: {list(session_data.keys())}"
    )
    logger.debug(
        f"[MULTI_AGENT_MGR] Session data structure: roles={len(roles)}, tool_configs={len(session_data['authorized_tool_configs'])}"
    )

    try:
        await save_session(session_id, session_data)
        logger.info(
            f"[MULTI_AGENT_MGR] Successfully saved session {session_id} to database"
        )
    except Exception as e:
        logger.error(
            f"[MULTI_AGENT_MGR] Failed to save session {session_id}: {e}", exc_info=True
        )
        return {"status": "error", "message": f"Failed to save session: {e}"}

    return {"status": "success", "multi_agent_session_id": session_id}


async def _recreate_session_runnables(
    session_data: Dict[str, Any], multi_agent_session_id: str
) -> Dict[str, Any]:
    """Recreate live agent objects from stored configuration data with persona support."""
    logger.info(
        f"[MULTI_AGENT_MGR] Recreating runnables for session {multi_agent_session_id}"
    )

    # Reconstruct user credentials if available
    user_creds_dict = session_data.get("user_credentials_dict")
    user_credentials = (
        AuthCredentials.model_validate(user_creds_dict) if user_creds_dict else None
    )
    logger.debug(
        f"[MULTI_AGENT_MGR] Reconstructed credentials: {bool(user_credentials)}"
    )

    # Backward compatibility: check for role_personas (new) or roles (old)
    role_personas_data = session_data.get("role_personas")
    if not role_personas_data:
        # Fallback to old "roles" format — apply auto-mapping for well-known role names
        old_roles = session_data.get("roles", [])
        role_personas_data = [
            {"name": r, "llm_purpose": ROLE_NAME_TO_LLM_PURPOSE.get(r), "system_prompt_template": None}
            for r in old_roles
        ]
        logger.info(
            f"[MULTI_AGENT_MGR] Using legacy roles format, converted {len(old_roles)} roles to personas (with auto-mapping)"
        )
    else:
        # Apply auto-mapping to existing personas that lack explicit llm_purpose
        for p in role_personas_data:
            if isinstance(p, dict) and not p.get("llm_purpose"):
                auto_purpose = ROLE_NAME_TO_LLM_PURPOSE.get(p.get("name", ""))
                if auto_purpose:
                    p["llm_purpose"] = auto_purpose
                    logger.info(
                        f"[MULTI_AGENT_MGR] Auto-mapped persisted role '{p['name']}' to llm_purpose='{auto_purpose}'"
                    )
        logger.info(
            f"[MULTI_AGENT_MGR] Using new role_personas format with {len(role_personas_data)} personas"
        )

    # Reconstruct role personas
    role_personas = [
        (
            RolePersona(**persona_dict)
            if isinstance(persona_dict, dict)
            else RolePersona(name=persona_dict)
        )
        for persona_dict in role_personas_data
    ]

    mcp_session_id = session_data["mcp_session_id"]
    authorized_tool_configs = session_data["authorized_tool_configs"]

    logger.info(
        f"[MULTI_AGENT_MGR] Creating {len(role_personas)} worker agents with {len(authorized_tool_configs)} tool configs"
    )

    try:
        worker_creation_tasks = (
            create_worker_agent(
                role_persona=persona,  # Pass full persona object
                mcp_session_id=mcp_session_id,
                multi_agent_session_id=multi_agent_session_id,
                authorized_tool_configs=authorized_tool_configs,
                user_credentials=user_credentials,
                llm=None,  # Let worker create its own LLM per persona.llm_purpose
            )
            for persona in role_personas
        )
        worker_agents_list = await asyncio.gather(*worker_creation_tasks)
        logger.info(
            f"[MULTI_AGENT_MGR] Successfully created {len(worker_agents_list)} worker agents"
        )
    except Exception as e:
        logger.error(
            f"[MULTI_AGENT_MGR] Failed to create worker agents: {e}", exc_info=True
        )
        raise

    runnables = {}
    execution_mode = session_data["execution_mode"]

    logger.info(
        f"[MULTI_AGENT_MGR] Creating runnables for execution_mode={execution_mode}"
    )

    # Extract role names for planner agent
    role_names = [persona.name for persona in role_personas]

    try:
        if execution_mode == "router":
            runnables["supervisor"] = create_router_supervisor_agent(
                worker_agents_list, mcp_session_id
            )
            runnables["planner"] = create_planner_agent(role_names)
            logger.info(
                f"[MULTI_AGENT_MGR] Created router-mode runnables: supervisor and planner"
            )
        elif execution_mode == "graph":
            # Lazy-initialize the module-level LLM client if not set
            global _llm_agnostic_client_instance
            if not _llm_agnostic_client_instance:
                logger.info(
                    "[MULTI_AGENT_MGR] Lazy-initializing LLM client for graph-mode runnables"
                )
                _llm_agnostic_client_instance = LLMAgnosticClient()
            supervisor_llm = _llm_agnostic_client_instance.get_langchain_chat_model(
                llm_purpose="agent_main"
            )
            # Legacy hub-and-spoke supervisor graph (backward compatibility)
            runnables["supervisor_graph"] = create_supervisor_graph(
                worker_agents_list, supervisor_llm
            )
            # Graph-mode planner for plan-as-graph execution
            runnables["planner"] = create_graph_planner_agent(role_names)
            # Store worker agents for plan-to-graph compilation
            runnables["_worker_agents_list"] = worker_agents_list
            runnables["_supervisor_llm"] = supervisor_llm
            logger.info(
                f"[MULTI_AGENT_MGR] Created graph-mode runnables: supervisor_graph, planner"
            )
    except Exception as e:
        logger.error(
            f"[MULTI_AGENT_MGR] Failed to create runnables: {e}", exc_info=True
        )
        raise

    return runnables


@observe(name="generate_multi_agent_plan", capture_input=True, capture_output=True)
async def generate_plan_for_multi_agent_task_impl(
    multi_agent_session_id: str, task: str
) -> Dict[str, Any]:
    """Core implementation for generating a plan for a multi-agent task."""
    logger.info(
        f"[MULTI_AGENT_MGR] Generating plan for session {multi_agent_session_id}, task: '{task[:100]}...'"
    )

    session_data = await get_session(multi_agent_session_id)
    if not session_data:
        logger.error(
            f"[MULTI_AGENT_MGR] Session {multi_agent_session_id} not found in database"
        )
        return {"status": "error", "message": "Session not found."}

    execution_mode = session_data.get("execution_mode")
    if execution_mode not in ("router", "graph"):
        return {
            "status": "error",
            "message": f"Unsupported execution mode: {execution_mode}",
        }

    # Recreate the planner agent on-demand
    logger.info(
        f"[MULTI_AGENT_MGR] Recreating planner agent for session {multi_agent_session_id} (mode={execution_mode})"
    )
    try:
        runnables = await _recreate_session_runnables(
            session_data, multi_agent_session_id
        )
        planner = runnables.get("planner")
        if not planner:
            logger.error(
                f"[MULTI_AGENT_MGR] No planner in runnables: {list(runnables.keys())}"
            )
            return {
                "status": "error",
                "message": "Could not recreate planner for this session.",
            }
        logger.info(f"[MULTI_AGENT_MGR] Planner agent recreated successfully")
    except Exception as e:
        logger.error(
            f"[MULTI_AGENT_MGR] Failed to recreate planner: {e}", exc_info=True
        )
        return {"status": "error", "message": f"Failed to recreate planner: {e}"}

    chat_history = session_data.get("chat_history", [])
    try:
        planner_messages = chat_history + [HumanMessage(content=task)]

        # ENHANCED: Use dedicated planner thread_id for observability
        # Thread ID format: {multi_agent_session_id}::planner
        planner_thread_id = f"{multi_agent_session_id}::planner"
        logger.info(
            f"[MULTI_AGENT_MGR] Invoking planner with thread_id: {planner_thread_id}"
        )

        plan_result = await planner.ainvoke(
            {"messages": planner_messages},
            config={"configurable": {"thread_id": planner_thread_id}},
        )
        generated_plan = plan_result.get("messages", [])[-1].content
        session_data["pending_plan"] = {"task": task, "plan": generated_plan}
        await save_session(multi_agent_session_id, session_data)
        return {"status": "plan_generated_for_approval", "plan": generated_plan}
    except Exception as e:
        logger.error(f"Error during plan generation: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@observe(name="execute_graph_plan", capture_input=True, capture_output=True)
async def _execute_graph_plan(
    plan_text: str,
    session_data: Dict[str, Any],
    runnables: Dict[str, Any],
    multi_agent_session_id: str,
    task: str,
) -> str:
    """Execute a plan using the plan-as-graph architecture.

    Parses the structured plan, compiles it into a LangGraph StateGraph where
    each step is a node and dependencies are edges, then executes it.
    Independent steps run in parallel natively via LangGraph.

    Args:
        plan_text: Raw plan text from the planner (JSON or free-text).
        session_data: Full session data dict.
        runnables: Dict from _recreate_session_runnables with worker agents.
        multi_agent_session_id: Session identifier.
        task: The original user task.

    Returns:
        The final synthesized response string.
    """
    # Parse the structured plan (with fallback to single-step)
    structured_plan = parse_structured_plan(plan_text, session_data)
    logger.info(
        f"[MULTI_AGENT_MGR] Parsed structured plan: {len(structured_plan.steps)} steps, "
        f"task='{structured_plan.task[:80]}...'"
    )
    for step in structured_plan.steps:
        logger.info(
            f"[MULTI_AGENT_MGR]   {step.step_id}: role={step.assigned_role}, "
            f"depends_on={step.depends_on}"
        )

    # Build workers dict from the recreated worker agents
    worker_agents_list = runnables.get("_worker_agents_list", [])
    supervisor_llm = runnables.get("_supervisor_llm")

    if not worker_agents_list or not supervisor_llm:
        raise RuntimeError(
            "Graph-mode execution requires worker agents and supervisor LLM. "
            "Ensure session was created with execution_mode='graph'."
        )

    # Map role_name -> (agent, thread_id)
    workers: Dict[str, Tuple[Any, str]] = {}
    for agent, role_name, thread_id in worker_agents_list:
        workers[role_name] = (agent, thread_id)

    # Compile the plan into a LangGraph graph
    plan_graph = compile_plan_to_graph(structured_plan, workers, supervisor_llm)
    logger.info(
        f"[MULTI_AGENT_MGR] Compiled plan-as-graph with {len(structured_plan.steps)} step nodes + synthesis"
    )

    # Build initial state
    initial_state = {"messages": [], "task": task}
    for step in structured_plan.steps:
        initial_state[f"result_{step.step_id}"] = None

    # Execute
    thread_id = f"{multi_agent_session_id}::plan_execution"
    logger.info(
        f"[MULTI_AGENT_MGR] Executing plan-as-graph with thread_id: {thread_id}"
    )
    result = await plan_graph.ainvoke(
        initial_state, config={"configurable": {"thread_id": thread_id}}
    )
    final_response = result["messages"][-1].content
    logger.info(
        f"[MULTI_AGENT_MGR] Plan-as-graph execution complete, response length: {len(final_response)}"
    )
    return final_response


@observe(name="execute_multi_agent_plan", capture_input=True, capture_output=True)
async def execute_approved_plan_in_session_impl(
    multi_agent_session_id: str,
) -> Dict[str, Any]:
    """Core implementation for executing an approved plan."""
    import time

    start_time = time.time()

    session_data = await get_session(multi_agent_session_id)
    if not session_data:
        return {"status": "error", "message": "Session not found."}

    execution_mode = session_data.get("execution_mode")
    if execution_mode not in ("router", "graph"):
        return {
            "status": "error",
            "message": f"Unsupported execution mode: {execution_mode}",
        }
    if "pending_plan" not in session_data:
        return {
            "status": "error",
            "message": "No pending plan to execute. Please generate a plan first using GeneratePlan.",
        }

    # Get the pending plan without removing it yet (in case of errors)
    pending_plan = session_data.get("pending_plan")
    if not pending_plan:
        return {
            "status": "error",
            "message": "Pending plan is empty. Please generate a plan first using GeneratePlan.",
        }

    # Recreate agents on-demand
    runnables = await _recreate_session_runnables(session_data, multi_agent_session_id)

    # Now safely extract the plan details
    task = pending_plan.get("task")
    generated_plan = pending_plan.get("plan")

    if not task or not generated_plan:
        return {
            "status": "error",
            "message": "Invalid plan structure. Missing task or plan content.",
        }
    chat_history = session_data.get("chat_history", [])
    worker_roles = session_data.get("roles", [])

    # Track execution start (Phase 1: Multi-Agent Teams Instrumentation)
    try:
        obs_factory = ObservabilityFactory()
        await obs_factory.track_session(
            session_id=multi_agent_session_id,
            metadata={
                "session_type": f"multi_agent_{execution_mode}_execution_start",
                "task": task,
                "plan_preview": (
                    generated_plan[:200] + "..."
                    if len(generated_plan) > 200
                    else generated_plan
                ),
                "worker_count": len(worker_roles),
                "worker_roles": worker_roles,
                "execution_mode": execution_mode,
                "supervisor_thread_id": f"{multi_agent_session_id}::supervisor",
            },
        )
    except Exception as obs_error:
        logger.warning(
            f"[MULTI_AGENT_MGR] Observability tracking failed at execution start: {obs_error}"
        )

    try:
        if execution_mode == "graph":
            # --- Plan-as-Graph execution path ---
            final_response = await _execute_graph_plan(
                generated_plan, session_data, runnables,
                multi_agent_session_id, task,
            )
        else:
            # --- Router execution path (existing behavior) ---
            supervisor = runnables.get("supervisor")
            if not supervisor:
                return {
                    "status": "error",
                    "message": "Could not recreate supervisor for this session.",
                }

            supervisor_task_with_plan = (
                f"Here is the user's overall task: '{task}'\n\n"
                f"Here is the plan you must follow:\n{generated_plan}\n\n"
                "Execute this plan and provide a final report."
            )

            supervisor_thread_id = f"{multi_agent_session_id}::supervisor"
            logger.info(
                f"[MULTI_AGENT_MGR] Executing plan with supervisor thread_id: {supervisor_thread_id}"
            )
            logger.info(
                f"[MULTI_AGENT_MGR] [OBSERVABILITY] Router execution metadata: session={multi_agent_session_id}, worker_count={len(worker_roles)}, execution_mode=router"
            )

            result = await supervisor.ainvoke(
                {"messages": [HumanMessage(content=supervisor_task_with_plan)]},
                config={"configurable": {"thread_id": supervisor_thread_id}},
            )
            final_response = result.get("messages", [])[-1].content

        # Update session data: add only the final response
        ai_message = AIMessage(content=final_response)
        session_data["chat_history"].append(ai_message.model_dump())
        # Remove the pending plan after successful execution
        session_data.pop("pending_plan", None)

        await save_session(multi_agent_session_id, session_data)

        # Track execution completion
        execution_time_ms = int((time.time() - start_time) * 1000)
        try:
            obs_factory = ObservabilityFactory()
            await obs_factory.track_session(
                session_id=multi_agent_session_id,
                metadata={
                    "session_type": f"multi_agent_{execution_mode}_execution_complete",
                    "status": "success",
                    "execution_time_ms": execution_time_ms,
                    "response_length": len(final_response),
                    "worker_count": len(worker_roles),
                    "execution_mode": execution_mode,
                },
            )
        except Exception as obs_error:
            logger.warning(
                f"[MULTI_AGENT_MGR] Observability tracking failed at execution complete: {obs_error}"
            )

        return {"status": "success", "report": final_response}
    except Exception as e:
        logger.error(f"Error during plan execution: {e}", exc_info=True)

        # Track execution failure
        execution_time_ms = int((time.time() - start_time) * 1000)
        try:
            obs_factory = ObservabilityFactory()
            await obs_factory.track_session(
                session_id=multi_agent_session_id,
                metadata={
                    "session_type": f"multi_agent_{execution_mode}_execution_failed",
                    "status": "error",
                    "error_message": str(e),
                    "execution_time_ms": execution_time_ms,
                    "worker_count": len(session_data.get("roles", [])),
                    "execution_mode": execution_mode,
                },
            )
        except Exception as obs_error:
            logger.warning(
                f"[MULTI_AGENT_MGR] Observability tracking failed at execution failure: {obs_error}"
            )

        return {"status": "error", "message": str(e)}


async def terminate_multi_agent_session_impl(
    multi_agent_session_id: str,
) -> Dict[str, Any]:
    """Core implementation for terminating a multi-agent session."""
    try:
        await delete_session(multi_agent_session_id)
        return {
            "status": "success",
            "message": f"Session {multi_agent_session_id} terminated.",
        }
    except Exception as e:
        logger.error(
            f"Error terminating session {multi_agent_session_id}: {e}", exc_info=True
        )
        return {
            "status": "error",
            "message": "Session not found or could not be deleted.",
        }


async def update_pending_plan_impl(
    multi_agent_session_id: str, edited_plan: str
) -> Dict[str, Any]:
    """Core implementation for updating a pending plan with user feedback."""
    session_data = await get_session(multi_agent_session_id)
    if not session_data:
        return {"status": "error", "message": "Session not found."}
    if "pending_plan" not in session_data:
        return {"status": "error", "message": "No pending plan to update."}

    session_data["pending_plan"]["plan"] = edited_plan
    await save_session(multi_agent_session_id, session_data)
    return {"status": "plan_updated", "plan": edited_plan}


async def list_active_multi_agent_sessions_impl() -> Dict[str, Any]:
    """Core implementation for listing all active multi-agent sessions."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT session_id FROM multi_agent_sessions")
            )
            session_ids = [row[0] for row in result.fetchall()]
        return {"status": "success", "active_sessions": session_ids}
    except Exception as e:
        logger.error(f"Error listing active multi-agent sessions: {e}", exc_info=True)
        return {
            "status": "error",
            "message": "Failed to retrieve active sessions from the database.",
        }


async def generate_and_review_plan_for_multi_agent_task_impl(
    multi_agent_session_id: str, task: str
) -> Dict[str, Any]:
    """Core implementation for generating a plan and having it reviewed by the agent team."""
    session_data = await get_session(multi_agent_session_id)
    if not session_data:
        return {"status": "error", "message": "Session not found."}

    execution_mode = session_data.get("execution_mode")
    if execution_mode not in ("router", "graph"):
        return {
            "status": "error",
            "message": f"Unsupported execution mode: {execution_mode}",
        }

    # Recreate the planner and supervisor agents on-demand
    runnables = await _recreate_session_runnables(session_data, multi_agent_session_id)
    planner = runnables.get("planner")
    if not planner:
        return {
            "status": "error",
            "message": "Could not recreate planner for this session.",
        }

    # For router mode, we also need a supervisor for the review step
    # For graph mode, the review is done by the planner alone (no supervisor review)
    supervisor = runnables.get("supervisor")
    if execution_mode == "router" and not supervisor:
        return {
            "status": "error",
            "message": "Could not recreate supervisor for this session.",
        }

    chat_history = session_data.get("chat_history", [])

    try:
        # 1. Generate the initial plan
        logger.info(
            f"Session {multi_agent_session_id}: Generating initial plan for task: '{task}'"
        )
        planner_messages = chat_history + [HumanMessage(content=task)]

        # ENHANCED: Use dedicated planner thread_id for observability
        # Thread ID format: {multi_agent_session_id}::planner
        planner_thread_id = f"{multi_agent_session_id}::planner"
        logger.info(
            f"[MULTI_AGENT_MGR] Plan review: invoking planner with thread_id: {planner_thread_id}"
        )

        plan_result = await planner.ainvoke(
            {"messages": planner_messages},
            config={"configurable": {"thread_id": planner_thread_id}},
        )
        initial_plan = plan_result.get("messages", [])[-1].content
        logger.info(
            f"Session {multi_agent_session_id}: Initial plan generated:\n{initial_plan}"
        )

        # 2. Have the supervisor orchestrate a review of the plan (router mode only)
        # For graph mode, the plan is structural JSON — supervisor review is skipped
        if execution_mode == "router" and supervisor:
            logger.info(
                f"Session {multi_agent_session_id}: Initiating supervisor review of the plan."
            )
            review_task = (
                f"Please review the following plan for the task '{task}'. "
                "Delegate the review to each of your worker agents to get their feedback on the plan's feasibility and correctness. "
                "Synthesize all feedback into a final, reviewed plan. If the plan is good, you can present it as is. If it needs changes, incorporate the feedback into the final version.\n\n"
                f"--- Initial Plan ---\n{initial_plan}"
            )

            supervisor_thread_id = f"{multi_agent_session_id}::supervisor"
            logger.info(
                f"[MULTI_AGENT_MGR] Plan review: invoking supervisor with thread_id: {supervisor_thread_id}"
            )

            review_result = await supervisor.ainvoke(
                {"messages": [HumanMessage(content=review_task)]},
                config={"configurable": {"thread_id": supervisor_thread_id}},
            )
            reviewed_plan = review_result.get("messages", [])[-1].content
            logger.info(
                f"Session {multi_agent_session_id}: Plan review complete. Final plan:\n{reviewed_plan}"
            )
        else:
            # Graph mode: planner output is the final plan (JSON structure)
            reviewed_plan = initial_plan
            logger.info(
                f"Session {multi_agent_session_id}: Graph mode — skipping supervisor review, using planner output directly"
            )

        # 3. Save the reviewed plan as the new pending plan
        session_data["pending_plan"] = {"task": task, "plan": reviewed_plan}
        await save_session(multi_agent_session_id, session_data)

        return {"status": "plan_generated_for_approval", "plan": reviewed_plan}
    except Exception as e:
        logger.error(f"Error during plan generation and review: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
