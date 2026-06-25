"""
This module provides the OpenAI-compatible `/v1/models` endpoint for the
Orchestration Service.

Architectural Role (in Three-Tier Model):
-   **Tier 2 (Orchestrator):** This router is part of the orchestration service.
-   **Single Source of Truth:** It reads the `AGENT_CONFIGURATIONS` dictionary
    from `orchestration_service/config.py` and serves it to any client that
    inquires, including the Agent Gateway which proxies requests to this endpoint.
    This makes the orchestrator the definitive source for available agent
    "models" (configurations).
"""
import os
import time
import html
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

from ...config import AGENT_CONFIGURATIONS
from ....logger_config import get_logger
from ...auth import get_forwarded_user
from ...external_tool_manager import tool_manager
from ....core.auth import AuthCredentials

router = APIRouter()
logger = get_logger(__name__)

@router.get("", summary="List Available Agent Models")
async def list_models(user: AuthCredentials = Depends(get_forwarded_user)):
    """
    Lists all available agent model configurations defined in the service.

    Returns both native format (agentic-framework:scientific-agent-v1) and
    LiteLLM-compatible aliases (adept/scientific-agent-v1) for compatibility.
    """
    logger.info("[ORCHESTRATION_SERVICE] Handling GET /v1/models/")

    # Build model list with native IDs
    model_list = []
    for model_id, config in AGENT_CONFIGURATIONS.items():
        # Add native model ID
        model_list.append({
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "AgenticFramework",
            "description": config.get("description"),
        })

        # Add LiteLLM-compatible alias (Session 48)
        # Convert "agentic-framework:scientific-agent-v1" -> "adept/scientific-agent-v1"
        if model_id.startswith("agentic-framework:"):
            alias_id = model_id.replace("agentic-framework:", "adept/")
            model_list.append({
                "id": alias_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "AgenticFramework",
                "description": f"{config.get('description')} (LiteLLM-compatible alias)",
            })

    response_data = {"object": "list", "data": model_list}
    return JSONResponse(content=response_data)

# IMPORTANT: Register specific routes BEFORE greedy :path route (Session 48 fix)
@router.get("/{model_id}/tools", summary="List Tools for a specific agent model")
async def get_tools_for_model(model_id: str, user: AuthCredentials = Depends(get_forwarded_user)):
    """
    Retrieves the list of tools for a specific agent model configuration.
    Includes both static tools from configuration and dynamically registered tools.

    Note: Registered before /{model_id:path} to ensure /tools suffix is matched correctly.
    """
    logger.info(f"[ORCHESTRATION_SERVICE] Handling GET /v1/models/{model_id}/tools")

    # Resolve alias format if needed
    resolved_model_id = model_id
    if model_id.startswith("adept/"):
        resolved_model_id = model_id.replace("adept/", "agentic-framework:")

    if resolved_model_id not in AGENT_CONFIGURATIONS:
        # Escape model_id to prevent XSS in error messages (Session 48 security fix)
        safe_model_id = html.escape(model_id)
        raise HTTPException(status_code=404, detail=f"Model '{safe_model_id}' not found.")

    config = AGENT_CONFIGURATIONS[resolved_model_id]
    static_tools_config = config.get("stdio_tools", [])

    # Get static tools and serialize them
    serialized_tools = []
    for tool in static_tools_config:
        serialized_tool = tool.copy()
        if "args_schema" in serialized_tool and hasattr(serialized_tool["args_schema"], 'model_json_schema'):
            serialized_tool["args_schema"] = serialized_tool["args_schema"].model_json_schema()
        serialized_tools.append(serialized_tool)

    # Get dynamically registered tools from external tool manager
    try:
        # Get user-authorized tools (filtered by ACL)
        dynamic_tools = await tool_manager.get_authorized_tools(
            user_id=user.user_id if user else None,
            user_groups=user.groups if user else []
        )

        # Convert LangChain Tools to serializable format
        for tool in dynamic_tools:
            tool_dict = {
                "name": tool.name,
                "description": tool.description,
                "args_schema": tool.args_schema.model_json_schema() if hasattr(tool.args_schema, 'model_json_schema') else {}
            }
            # Add metadata if available
            if hasattr(tool, 'metadata') and tool.metadata:
                tool_dict.update(tool.metadata)
            serialized_tools.append(tool_dict)

        logger.info(f"[ORCHESTRATION_SERVICE] Returning {len(static_tools_config)} static + {len(dynamic_tools)} dynamic tools for model {resolved_model_id}")

    except Exception as e:
        logger.error(f"[ORCHESTRATION_SERVICE] Error getting dynamic tools: {e}")
        # Continue with just static tools if dynamic tool retrieval fails

    return JSONResponse(content={"tools": serialized_tools})

@router.get("/{model_id:path}", summary="Retrieve a specific agent model")
async def get_model(model_id: str, user: AuthCredentials = Depends(get_forwarded_user)):
    """
    Retrieves the details for a specific agent model configuration.

    Accepts both native format (agentic-framework:scientific-agent-v1) and
    LiteLLM-compatible aliases (adept/scientific-agent-v1).

    Note: Uses :path to support model IDs with slashes (e.g., adept/scientific-agent-v1).
    Handles /tools suffix for model IDs containing slashes (FastAPI routing limitation).
    """
    logger.info(f"[ORCHESTRATION_SERVICE] Handling GET /v1/models/{model_id}")

    # Check if this is a /tools request for a model ID with slashes (Session 48 fix)
    # FastAPI's /{model_id}/tools route doesn't match when model_id contains slashes
    if model_id.endswith("/tools"):
        actual_model_id = model_id[:-6]  # Remove "/tools" suffix
        logger.info(f"[ORCHESTRATION_SERVICE] Redirecting {model_id} to tools handler")
        return await get_tools_for_model(actual_model_id, user)

    # Resolve LiteLLM alias to native format (Session 48)
    # Convert "adept/scientific-agent-v1" -> "agentic-framework:scientific-agent-v1"
    resolved_model_id = model_id
    if model_id.startswith("adept/"):
        resolved_model_id = model_id.replace("adept/", "agentic-framework:")
        logger.debug(f"[ORCHESTRATION_SERVICE] Resolved LiteLLM alias: {model_id} -> {resolved_model_id}")

    if resolved_model_id not in AGENT_CONFIGURATIONS:
        # Escape model_id to prevent XSS in error messages (Session 48 security fix)
        safe_model_id = html.escape(model_id)
        raise HTTPException(status_code=404, detail=f"Model '{safe_model_id}' not found.")

    config = AGENT_CONFIGURATIONS[resolved_model_id]
    model_entry = {
        "id": model_id,  # Return the requested ID (alias or native)
        "object": "model",
        "created": int(time.time()),
        "owned_by": "AgenticFramework",
        "description": config.get("description"),
    }
    return JSONResponse(content=model_entry)