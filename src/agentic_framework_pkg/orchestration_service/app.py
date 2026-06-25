"""
Main application file for the Orchestration Service.

This module initializes the FastAPI application for the orchestration service,
mounts all necessary routers, and defines the core agent invocation endpoint.

Architectural Role:
-   **Tier 2 (Orchestrator):** This service is the "brain" of the agentic
    framework. It is responsible for all stateful operations.
-   **Agent Logic:** It houses the `ScientificWorkflowAgent` and all associated
    logic for tool use, planning, and multi-agent orchestration.
-   **State Management:** It connects to the PostgreSQL database via the
    `AsyncPostgresSaver` to provide durable, persistent state for all agent
    conversations and sessions.
-   **Tool Management:** It exposes administrative endpoints (`/admin/tools/*`)
    for managing the registration and ACLs of all dynamic tools in the framework.
"""
import os
from fastapi import FastAPI, Request, HTTPException, Depends, APIRouter
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Dict, Any
from .scientific_workflow.langchain_agent import ScientificWorkflowAgent
from .persistence_v2 import AsyncPostgresSaver
from .auth import get_forwarded_user, require_role
from ..core.auth import AuthCredentials
from .external_tool_manager import tool_manager
from .hybrid_orchestration import hybrid_service
from ..logger_config import get_logger
from .lifespan import lifespan
from .routers.v1 import (
    models as models_router,
    assistants as assistants_router,
    threads as threads_router,
    runs as runs_router,
    files as files_router,
    beta_compatibility,
    responses as responses_router,
    knowledge_bases as knowledge_bases_router,
    agui as agui_router,
)
from .routers.internal import sessions as internal_sessions_router
from .openai_error_handler import (
    validation_exception_handler,
    http_exception_handler, 
    general_exception_handler
)

logger = get_logger(__name__)

app = FastAPI(
    title="Orchestration Service",
    description="Handles agentic workflow orchestration and state management.",
    version="1.0.0",
    lifespan=lifespan,
)

# --- OpenAI Compatible Endpoints ---
v1_router = FastAPI()
v1_router.include_router(models_router.router, prefix="/models", tags=["Models"])
v1_router.include_router(assistants_router.router, prefix="/assistants", tags=["Assistants"])
v1_router.include_router(threads_router.router, prefix="/threads", tags=["Threads"])
v1_router.include_router(runs_router.router, prefix="/threads/{thread_id}/runs", tags=["Runs"])
v1_router.include_router(files_router.router, prefix="/files", tags=["Files"])
v1_router.include_router(responses_router.router, prefix="/responses", tags=["Response API"])
v1_router.include_router(knowledge_bases_router.router, prefix="/knowledge_bases", tags=["Knowledge Bases"])

# AG-UI Protocol (real-time JSONL event streaming)
if os.getenv("AGUI_PROTOCOL_ENABLED", "true").lower() != "false":
    v1_router.include_router(agui_router.router, prefix="/ag-ui", tags=["AG-UI Protocol"])

# Include beta compatibility layer
v1_router.include_router(beta_compatibility.router, tags=["Beta Compatibility"])

app.mount("/v1", v1_router)

# --- Internal API for Service-to-Service Communication ---
app.include_router(internal_sessions_router.router, prefix="/internal", tags=["Internal API"])

# --- Add OpenAI-Compatible Error Handlers ---
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

from .persistence import AsyncSessionLocal
from .models import Assistant
from sqlalchemy.future import select
from typing import Optional, List

# ... (imports remain the same)

# --- Multi-Path Output Processing ---
async def process_agent_output(agent_result: Dict[str, Any], context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Process agent output with intelligent filtering and multi-path management.
    
    This handles:
    - Filtering out large base64 blobs
    - Extracting tool usage information
    - Managing different output formats based on context
    - Preserving important metadata while cleaning presentation
    """
    import re
    import base64
    from langchain_core.messages import AIMessage, ToolMessage
    
    logger.info(f"[OUTPUT_PROCESSING] Processing agent output with context: {context}")
    
    # Extract core output
    final_output = agent_result.get("output", "")
    full_graph_state = agent_result.get("full_graph_state", {})
    
    # Initialize processing result
    processed = {
        "final_output": final_output,
        "tool_outputs": [],
        "tools_used": [],
        "content_filtered": False,
        "filtered_content": {}
    }
    
    # Process messages from graph state to extract tool information
    if full_graph_state and "messages" in full_graph_state:
        messages = full_graph_state["messages"]
        
        for msg in messages:
            if isinstance(msg, ToolMessage):
                # Extract tool usage
                processed["tools_used"].append({
                    "tool_call_id": getattr(msg, 'tool_call_id', 'unknown'),
                    "name": getattr(msg, 'name', 'unknown_tool'),
                    "content_length": len(str(msg.content))
                })
                
                # Filter large base64 content
                if isinstance(msg.content, str) and len(msg.content) > 1000:
                    # Check if it's base64 data
                    if re.match(r'^[A-Za-z0-9+/]*={0,2}$', msg.content[:100]):
                        try:
                            base64.b64decode(msg.content[:100])
                            # It's base64, filter it
                            processed["content_filtered"] = True
                            processed["filtered_content"][f"tool_output_{msg.tool_call_id}"] = {
                                "type": "base64_data",
                                "size": len(msg.content),
                                "summary": "Large binary data filtered from output"
                            }
                            logger.info(f"[OUTPUT_PROCESSING] Filtered base64 content of {len(msg.content)} bytes")
                            continue
                        except:
                            pass  # Not base64, keep as is
                
                processed["tool_outputs"].append({
                    "tool_call_id": getattr(msg, 'tool_call_id', 'unknown'),
                    "output": str(msg.content)[:500] if len(str(msg.content)) > 500 else str(msg.content)  # Truncate long outputs
                })
    
    # Clean up final output if it contains large base64 blobs
    if len(final_output) > 2000:
        # Look for base64 patterns and replace with summaries
        base64_pattern = r'[A-Za-z0-9+/]{50,}={0,2}'
        matches = re.findall(base64_pattern, final_output)
        
        if matches:
            cleaned_output = final_output
            for match in matches:
                if len(match) > 100:  # Only filter long base64 strings
                    try:
                        base64.b64decode(match[:100])  # Verify it's base64
                        cleaned_output = cleaned_output.replace(match, f"[Base64 data: {len(match)} characters - filtered]")
                        processed["content_filtered"] = True
                        logger.info(f"[OUTPUT_PROCESSING] Filtered base64 blob of {len(match)} chars from final output")
                    except:
                        pass  # Not base64
            
            if processed["content_filtered"]:
                processed["final_output"] = cleaned_output
    
    # Add execution context information
    if context:
        processed["execution_context"] = context
    
    logger.info(f"[OUTPUT_PROCESSING] Processed output: {len(processed['final_output'])} chars, {len(processed['tools_used'])} tools used, filtered: {processed['content_filtered']}")
    
    return processed

# --- Enhanced Agent Invocation Core ---
async def enhanced_invoke_agent(
    user_input: str,
    thread_id: str, 
    assistant_id: str,
    user: AuthCredentials,
    chat_history: Optional[List] = None,
    context: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Enhanced core agent invocation function used by both /invoke and Assistant API.
    
    This is the single execution path for all agent operations, providing:
    - Synchronous execution (no background tasks)
    - Proper error handling and status management
    - Full conversation context support
    - Session persistence via checkpointing
    """
    logger.info(f"[ENHANCED_INVOKE] Starting agent execution for thread '{thread_id}', assistant '{assistant_id}'")
    
    try:
        # Fetch assistant configuration
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Assistant).where(Assistant.id == assistant_id))
            assistant_config = result.scalars().first()
            
            if not assistant_config:
                raise ValueError(f"Assistant with ID '{assistant_id}' not found.")
            
            logger.info(f"[ENHANCED_INVOKE] Assistant config: model={assistant_config.model}, instructions_len={len(assistant_config.instructions or '')}")

        # Create agent with proper checkpointing
        checkpointer = AsyncPostgresSaver()
        agent = await ScientificWorkflowAgent.create(
            mcp_session_id=thread_id,
            thread_id_override=thread_id,
            checkpointer=checkpointer,
            user_credentials=user,
            system_prompt_override=assistant_config.instructions
        )
        
        logger.info(f"[ENHANCED_INVOKE] Agent created successfully with {len(agent.tools)} tools")
        
        # Execute agent synchronously
        result = await agent.arun(
            user_input=user_input, 
            chat_history=chat_history or []
        )
        
        logger.info(f"[ENHANCED_INVOKE] Agent execution completed with output length: {len(result.get('output', ''))}")
        
        # Process multi-path output with intelligent filtering
        processed_output = await process_agent_output(result, context)
        
        return {
            "output": processed_output["final_output"],
            "session_id": thread_id,
            "assistant_id": assistant_id,
            "tool_outputs": processed_output.get("tool_outputs", []),
            "filtered_content": processed_output.get("filtered_content", {}),
            "metadata": {
                "model": assistant_config.model,
                "tools_available": len(agent.tools),
                "execution_type": "synchronous",
                "tools_used": processed_output.get("tools_used", []),
                "content_filtered": processed_output.get("content_filtered", False)
            }
        }
        
    except Exception as e:
        logger.error(f"[ENHANCED_INVOKE] Agent execution failed for thread '{thread_id}': {e}", exc_info=True)
        raise

# --- Agent Invocation Endpoint ---
@app.post("/invoke")
async def invoke_agent(request: Request, user: AuthCredentials = Depends(get_forwarded_user)):
    """
    The primary endpoint for executing agentic workflows.

    Enhanced to provide synchronous execution with full session support.
    """
    try:
        body = await request.json()
        logger.info(f"[ORCHESTRATION_SERVICE] Handling POST /invoke for thread_id: {body.get('thread_id')}")
        
        user_input = body.get("input")
        thread_id = body.get("thread_id")
        assistant_id = body.get("assistant_id")
        chat_history = body.get("chat_history", [])
        context = body.get("context", {})
        
        if not all([user_input, thread_id, assistant_id]):
            raise HTTPException(status_code=400, detail="Missing 'input', 'thread_id', or 'assistant_id'")

        # Use enhanced core execution
        result = await enhanced_invoke_agent(
            user_input=user_input,
            thread_id=thread_id,
            assistant_id=assistant_id,
            user=user,
            chat_history=chat_history,
            context=context
        )
        
        logger.info(f"Agent execution completed for thread '{thread_id}' via enhanced invoke.")
        return result

    except Exception as e:
        logger.error(f"Error invoking agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# --- Admin Tool Management Endpoints ---
tools_router = APIRouter()

@tools_router.get("/list", summary="List All Registered Tools", dependencies=[Depends(require_role("admin"))])
async def list_all_tools():
    """Lists all dynamically registered tools available in the framework."""
    logger.info("[ORCHESTRATION_SERVICE] Handling GET /v1/tools/list")
    try:
        tools = tool_manager.get_all_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "args_schema": tool.args_schema.schema() if tool.args_schema else {}
            }
            for tool in tools
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@tools_router.post("/register", summary="Register an External Tool", dependencies=[Depends(require_role("admin"))])
async def register_tool(config: Dict[str, Any]):
    """Registers a new external tool with the framework."""
    logger.info(f"[ORCHESTRATION_SERVICE] Handling POST /v1/tools/register for tool: {config.get('name')}")
    try:
        await tool_manager.register_tool(config)
        return {"status": "success", "message": f"Tool '{config.get('name')}' registered."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@tools_router.get("/{tool_name}", summary="Retrieve a Specific Tool", dependencies=[Depends(require_role("admin"))])
async def retrieve_tool(tool_name: str):
    """Retrieves the configuration of a registered external tool."""
    logger.info(f"[ORCHESTRATION_SERVICE] Handling GET /v1/tools/{tool_name}")
    try:
        tool_config = await tool_manager.get_tool_config(tool_name)
        if tool_config is None:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
        return tool_config
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving tool '{tool_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@tools_router.delete("/{tool_name}", summary="Delete an External Tool", dependencies=[Depends(require_role("admin"))])
async def delete_tool(tool_name: str):
    """Deletes a registered external tool."""
    logger.info(f"[ORCHESTRATION_SERVICE] Handling DELETE /v1/tools/{tool_name}")
    try:
        await tool_manager.delete_tool(tool_name)
        return {"status": "success", "message": f"Tool '{tool_name}' deleted."}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@tools_router.put("/{tool_name}/acl", summary="Update Tool ACL", dependencies=[Depends(require_role("admin"))])
async def update_tool_acl(tool_name: str, acl: Dict[str, Any]):
    """Updates the Access Control List (ACL) for a registered tool."""
    logger.info(f"[ORCHESTRATION_SERVICE] Handling PUT /v1/tools/{tool_name}/acl")
    try:
        await tool_manager.update_tool_acl(tool_name, acl)
        return {"status": "success", "message": f"ACL for tool '{tool_name}' updated."}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

v1_router.include_router(tools_router, prefix="/tools", tags=["Tools"])

# --- Legacy Admin Tool Management Endpoints (for backwards compatibility) ---
admin_tools_router = APIRouter()

@admin_tools_router.post("/register", summary="Register Tool (Admin Legacy)", dependencies=[Depends(require_role("admin"))])
async def admin_register_tool(config: Dict[str, Any]):
    """Legacy admin endpoint that forwards to the main tool registration."""
    return await register_tool(config)

@admin_tools_router.get("/list", summary="List Tools (Admin Legacy)", dependencies=[Depends(require_role("admin"))])
async def admin_list_tools():
    """Legacy admin endpoint that forwards to the main tool listing."""
    return await list_all_tools()

@admin_tools_router.delete("/{tool_name}", summary="Delete Tool (Admin Legacy)", dependencies=[Depends(require_role("admin"))])
async def admin_delete_tool(tool_name: str):
    """Legacy admin endpoint that forwards to the main tool deletion."""
    return await delete_tool(tool_name)

@admin_tools_router.put("/{tool_name}/acl", summary="Update Tool ACL (Admin Legacy)", dependencies=[Depends(require_role("admin"))])
async def admin_update_tool_acl(tool_name: str, acl_data: Dict[str, Any]):
    """Legacy admin endpoint that forwards to the main ACL update."""
    return await update_tool_acl(tool_name, acl_data)

app.include_router(admin_tools_router, prefix="/admin/tools", tags=["Admin Tools"])

@app.get("/health")
async def health_check():
    """Provides a simple health check endpoint for monitoring."""
    return {"status": "ok"}

@app.get("/admin/sessions/stats", dependencies=[Depends(require_role("admin"))])
async def get_session_stats():
    """Get comprehensive session and agent pool statistics from the hybrid service."""
    try:
        stats = hybrid_service.get_session_stats()
        return stats
    except Exception as e:
        logger.error(f"Error getting session stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/sessions/cleanup", dependencies=[Depends(require_role("admin"))])
async def cleanup_expired_sessions():
    """Manually trigger cleanup of expired sessions."""
    try:
        await hybrid_service.cleanup_expired_sessions()
        return {"status": "success", "message": "Session cleanup completed"}
    except Exception as e:
        logger.error(f"Error cleaning up sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
