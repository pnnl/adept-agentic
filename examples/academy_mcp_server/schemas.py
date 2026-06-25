"""
Academy MCP Server — Pydantic Schemas

Input validation models for Academy agent lifecycle tools.
These schemas are the single source of truth for tool registration.
Use ``export_registration_schema()`` to generate ADEPT-compatible args_schema JSON.
"""

import json
import sys
from typing import Dict, Any, Optional, Literal

from pydantic import BaseModel, Field


class LaunchAgentInput(BaseModel):
    """Input schema for launch_academy_agent tool."""

    agent_type: Literal["echo", "counter", "compute"] = Field(
        ...,
        description=(
            "Type of Academy agent to launch: "
            "'echo' (message echo + call counting), "
            "'counter' (stateful increment/decrement), "
            "'compute' (factorial, fibonacci, primality)"
        ),
    )
    agent_config: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Agent-specific configuration passed as kwargs to agent constructor. "
            "For counter: {'initial_value': 10}. For compute: {}. For echo: {}."
        ),
    )
    mcp_session_id: Optional[str] = Field(
        default=None,
        description="MCP session ID for resource isolation across concurrent users.",
    )


class InvokeActionInput(BaseModel):
    """Input schema for invoke_agent_action tool."""

    agent_id: str = Field(
        ...,
        description="Agent ID returned by launch_academy_agent.",
    )
    action_name: str = Field(
        ...,
        description=(
            "Name of the action to invoke. "
            "Echo: 'echo' (needs action_args={\"message\": \"...\"}), 'get_call_count' (no args). "
            "Counter: 'increment'/'decrement' (action_args={\"value\": N}), 'get_count', 'reset'. "
            "Compute: 'factorial'/'fibonacci'/'is_prime' (action_args={\"n\": N}), 'get_computation_count'."
        ),
    )
    action_args: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "A JSON object containing the keyword arguments for the action. "
            "You MUST pass action-specific parameters inside this object — "
            "do NOT pass them as top-level arguments. "
            "Examples: For echo: {\"message\": \"hello world\"}. "
            "For increment: {\"value\": 5}. For factorial: {\"n\": 7}. "
            "For fibonacci: {\"n\": 10}. For is_prime: {\"n\": 17}. "
            "For get_count, get_call_count, reset: {}."
        ),
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Timeout in seconds for the action (1-300, default 30).",
    )
    mcp_session_id: Optional[str] = Field(
        default=None,
        description="MCP session ID for resource isolation.",
    )


class ListAgentsInput(BaseModel):
    """Input schema for list_academy_agents tool."""

    mcp_session_id: Optional[str] = Field(
        default=None,
        description="MCP session ID to list agents for.",
    )


class ShutdownAgentInput(BaseModel):
    """Input schema for shutdown_academy_agent tool."""

    agent_id: str = Field(
        ...,
        description="Agent ID to shut down.",
    )
    blocking: bool = Field(
        default=True,
        description="If true, wait for agent shutdown to complete before returning.",
    )
    mcp_session_id: Optional[str] = Field(
        default=None,
        description="MCP session ID for resource isolation.",
    )


# ---------------------------------------------------------------------------
# Globus Transfer Schemas
# ---------------------------------------------------------------------------


class GlobusListDirectoryInput(BaseModel):
    endpoint_id: str = Field(..., description="UUID of the Globus collection or endpoint.")
    path: str = Field(default="/", description="Directory path to list.")
    show_hidden: bool = Field(default=False, description="Include hidden files.")
    mcp_session_id: Optional[str] = None


class GlobusMkdirInput(BaseModel):
    endpoint_id: str = Field(..., description="UUID of the Globus collection.")
    path: str = Field(..., description="Full path of directory to create.")
    mcp_session_id: Optional[str] = None


class GlobusRenameInput(BaseModel):
    endpoint_id: str = Field(..., description="UUID of the Globus collection.")
    old_path: str = Field(..., description="Current path of the file/directory.")
    new_path: str = Field(..., description="New path for the file/directory.")
    mcp_session_id: Optional[str] = None


class GlobusStatInput(BaseModel):
    endpoint_id: str = Field(..., description="UUID of the Globus collection.")
    path: str = Field(..., description="Path to the file or directory.")
    mcp_session_id: Optional[str] = None


class GlobusSubmitTransferInput(BaseModel):
    source_endpoint: str = Field(..., description="Source collection UUID.")
    destination_endpoint: str = Field(..., description="Destination collection UUID.")
    transfer_items: list = Field(
        ..., description="List of {source_path, destination_path, recursive?} dicts."
    )
    label: str = Field(default="", description="Human-readable label for the transfer.")
    sync_level: Optional[int] = Field(
        default=None, description="Sync level: 0=exists, 1=size, 2=mtime, 3=checksum."
    )
    mcp_session_id: Optional[str] = None


class GlobusSubmitDeleteInput(BaseModel):
    endpoint_id: str = Field(..., description="UUID of the Globus collection.")
    paths: list = Field(..., description="List of file/directory paths to delete.")
    recursive: bool = Field(default=True, description="Recursively delete directories.")
    label: str = Field(default="", description="Human-readable label.")
    mcp_session_id: Optional[str] = None


class GlobusGetTaskInput(BaseModel):
    task_id: str = Field(..., description="Globus task ID.")
    mcp_session_id: Optional[str] = None


class GlobusListTasksInput(BaseModel):
    filter_status: Optional[str] = Field(
        default=None, description="Filter by status: ACTIVE, SUCCEEDED, FAILED."
    )
    limit: int = Field(default=10, description="Maximum number of tasks to return.")
    mcp_session_id: Optional[str] = None


class GlobusCancelTaskInput(BaseModel):
    task_id: str = Field(..., description="Task ID to cancel.")
    mcp_session_id: Optional[str] = None


class GlobusWaitForTaskInput(BaseModel):
    task_id: str = Field(..., description="Task ID to wait for.")
    timeout: int = Field(default=300, description="Maximum wait time in seconds.")
    polling_interval: int = Field(default=5, description="Seconds between polls.")
    mcp_session_id: Optional[str] = None


class GlobusSearchEndpointsInput(BaseModel):
    filter_fulltext: str = Field(..., description="Text to search for in endpoint names.")
    filter_scope: str = Field(
        default="all", description="Scope: all, my-endpoints, shared-with-me."
    )
    limit: int = Field(default=10, description="Maximum results to return.")
    mcp_session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Globus Search Schemas
# ---------------------------------------------------------------------------


class GlobusSearchQueryInput(BaseModel):
    index_id: str = Field(..., description="UUID of the Globus Search index.")
    q: str = Field(..., description="Search query string (Lucene syntax).")
    limit: int = Field(default=10, description="Maximum results.")
    offset: int = Field(default=0, description="Result offset for pagination.")
    filters: Optional[list] = Field(
        default=None, description="List of filter dicts ({field, values, type})."
    )
    mcp_session_id: Optional[str] = None


class GlobusSearchScrollInput(BaseModel):
    index_id: str = Field(..., description="UUID of the Globus Search index.")
    q: str = Field(default="*", description="Search query (default: all).")
    limit: int = Field(default=100, description="Results per page.")
    marker: Optional[str] = Field(
        default=None, description="Pagination marker from previous scroll."
    )
    mcp_session_id: Optional[str] = None


class GlobusIngestEntriesInput(BaseModel):
    index_id: str = Field(..., description="UUID of the Globus Search index.")
    entries: list = Field(
        ..., description="List of {subject, content, visible_to?} dicts."
    )
    mcp_session_id: Optional[str] = None


class GlobusGetSearchSubjectInput(BaseModel):
    index_id: str = Field(..., description="UUID of the Globus Search index.")
    subject: str = Field(..., description="Subject URI to retrieve.")
    mcp_session_id: Optional[str] = None


class GlobusDeleteSearchSubjectInput(BaseModel):
    index_id: str = Field(..., description="UUID of the Globus Search index.")
    subject: str = Field(..., description="Subject URI to delete.")
    mcp_session_id: Optional[str] = None


class GlobusListSearchIndicesInput(BaseModel):
    mcp_session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Globus Compute Schemas
# ---------------------------------------------------------------------------


class GlobusComputeSubmitInput(BaseModel):
    endpoint_id: str = Field(..., description="UUID of the Globus Compute endpoint.")
    function_id: str = Field(..., description="UUID of a registered function.")
    args: Optional[list] = Field(default=None, description="Positional arguments.")
    kwargs: Optional[dict] = Field(default=None, description="Keyword arguments.")
    mcp_session_id: Optional[str] = None


class GlobusComputeGetTaskInput(BaseModel):
    task_id: str = Field(..., description="Compute task ID.")
    mcp_session_id: Optional[str] = None


class GlobusComputeGetEndpointInput(BaseModel):
    endpoint_id: str = Field(..., description="UUID of the Globus Compute endpoint.")
    mcp_session_id: Optional[str] = None


class GlobusComputeListEndpointsInput(BaseModel):
    mcp_session_id: Optional[str] = None


class GlobusComputeRegisterFunctionInput(BaseModel):
    function_code: str = Field(..., description="Python source code defining the function.")
    function_name: str = Field(default="", description="Display name.")
    description: str = Field(default="", description="Human-readable description.")
    mcp_session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Globus Flows Schemas
# ---------------------------------------------------------------------------


class GlobusListFlowsInput(BaseModel):
    filter_role: str = Field(default="flow_owner", description="Role filter.")
    limit: int = Field(default=10, description="Maximum flows to return.")
    mcp_session_id: Optional[str] = None


class GlobusRunFlowInput(BaseModel):
    flow_id: str = Field(..., description="UUID of the Globus Flow.")
    flow_input: dict = Field(..., description="Input parameters for the flow.")
    label: str = Field(default="", description="Human-readable label.")
    mcp_session_id: Optional[str] = None


class GlobusGetFlowRunInput(BaseModel):
    run_id: str = Field(..., description="Run ID from run_flow.")
    mcp_session_id: Optional[str] = None


class GlobusCancelFlowRunInput(BaseModel):
    run_id: str = Field(..., description="Run ID to cancel.")
    mcp_session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Globus Groups Schemas
# ---------------------------------------------------------------------------


class GlobusListGroupsInput(BaseModel):
    mcp_session_id: Optional[str] = None


class GlobusGetGroupInput(BaseModel):
    group_id: str = Field(..., description="UUID of the Globus group.")
    mcp_session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Schema export utility
# ---------------------------------------------------------------------------


def _resolve_property(prop: dict, defs: dict) -> dict:
    """Resolve $ref and allOf references in a JSON Schema property."""
    if "$ref" in prop:
        ref_name = prop["$ref"].rsplit("/", 1)[-1]
        return defs.get(ref_name, prop)
    if "allOf" in prop:
        merged = {}
        for sub in prop["allOf"]:
            merged.update(_resolve_property(sub, defs))
        # Preserve top-level description/default which Pydantic puts outside allOf
        if "description" in prop:
            merged["description"] = prop["description"]
        if "default" in prop:
            merged["default"] = prop["default"]
        return merged
    return prop


def export_registration_schema(model_class: type) -> dict:
    """Export Pydantic model fields as ADEPT registration args_schema dict.

    Uses Pydantic's native model_json_schema() and reshapes properties
    into the flat {field: {type, description, default?, enum?}} format
    consumed by ``agentic tools register --args-schema``.

    Usage::

        from academy_mcp_server.schemas import InvokeActionInput, export_registration_schema
        import json
        print(json.dumps(export_registration_schema(InvokeActionInput)))
    """
    json_schema = model_class.model_json_schema()
    properties = json_schema.get("properties", {})
    defs = json_schema.get("$defs", {})
    fields = model_class.model_fields
    result = {}

    for name, prop in properties.items():
        entry = {}

        # Resolve $ref or anyOf (Optional types)
        resolved = _resolve_property(prop, defs)

        # type
        if "type" in resolved:
            entry["type"] = resolved["type"]
        elif "anyOf" in resolved:
            # Optional[X] → pick the non-null type
            types = [s["type"] for s in resolved["anyOf"] if s.get("type") != "null"]
            entry["type"] = types[0] if types else "string"
            entry["nullable"] = True

        # description
        if "description" in resolved:
            entry["description"] = resolved["description"]

        # default — JSON schema includes it for static defaults; for
        # default_factory (e.g. dict) Pydantic omits it, so fall back
        # to invoking the factory via model_fields.
        if "default" in resolved:
            entry["default"] = resolved["default"]
        elif name in fields and fields[name].default_factory is not None:
            entry["default"] = fields[name].default_factory()

        # enum
        if "enum" in resolved:
            entry["enum"] = resolved["enum"]

        result[name] = entry

    return result


if __name__ == "__main__":
    # CLI entry point: python -m academy_mcp_server.schemas [ModelName]
    models = {
        "LaunchAgentInput": LaunchAgentInput,
        "InvokeActionInput": InvokeActionInput,
        "ListAgentsInput": ListAgentsInput,
        "ShutdownAgentInput": ShutdownAgentInput,
        # Globus Transfer
        "GlobusListDirectoryInput": GlobusListDirectoryInput,
        "GlobusMkdirInput": GlobusMkdirInput,
        "GlobusRenameInput": GlobusRenameInput,
        "GlobusStatInput": GlobusStatInput,
        "GlobusSubmitTransferInput": GlobusSubmitTransferInput,
        "GlobusSubmitDeleteInput": GlobusSubmitDeleteInput,
        "GlobusGetTaskInput": GlobusGetTaskInput,
        "GlobusListTasksInput": GlobusListTasksInput,
        "GlobusCancelTaskInput": GlobusCancelTaskInput,
        "GlobusWaitForTaskInput": GlobusWaitForTaskInput,
        "GlobusSearchEndpointsInput": GlobusSearchEndpointsInput,
        # Globus Search
        "GlobusSearchQueryInput": GlobusSearchQueryInput,
        "GlobusSearchScrollInput": GlobusSearchScrollInput,
        "GlobusIngestEntriesInput": GlobusIngestEntriesInput,
        "GlobusGetSearchSubjectInput": GlobusGetSearchSubjectInput,
        "GlobusDeleteSearchSubjectInput": GlobusDeleteSearchSubjectInput,
        "GlobusListSearchIndicesInput": GlobusListSearchIndicesInput,
        # Globus Compute
        "GlobusComputeSubmitInput": GlobusComputeSubmitInput,
        "GlobusComputeGetTaskInput": GlobusComputeGetTaskInput,
        "GlobusComputeGetEndpointInput": GlobusComputeGetEndpointInput,
        "GlobusComputeListEndpointsInput": GlobusComputeListEndpointsInput,
        "GlobusComputeRegisterFunctionInput": GlobusComputeRegisterFunctionInput,
        # Globus Flows
        "GlobusListFlowsInput": GlobusListFlowsInput,
        "GlobusRunFlowInput": GlobusRunFlowInput,
        "GlobusGetFlowRunInput": GlobusGetFlowRunInput,
        "GlobusCancelFlowRunInput": GlobusCancelFlowRunInput,
        # Globus Groups
        "GlobusListGroupsInput": GlobusListGroupsInput,
        "GlobusGetGroupInput": GlobusGetGroupInput,
    }
    model_name = sys.argv[1] if len(sys.argv) > 1 else "InvokeActionInput"
    if model_name not in models:
        print(f"Unknown model: {model_name}. Choose from: {list(models.keys())}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(export_registration_schema(models[model_name])))
