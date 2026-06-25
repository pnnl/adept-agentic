"""
This module registers general-purpose utility tools with the MCP server.

These tools provide foundational capabilities that can be used across various
workflows, such as performing calculations, managing session notes, and
retrieving the current time.
"""
from fastmcp import FastMCP, Context
from ..state_manager import get_session_context, update_session_context, create_session_if_not_exists
import datetime
from typing import Dict, Any, List
import re
import uuid

# Use the centralized logger
from ...logger_config import get_logger
logger = get_logger(__name__)

def get_stable_session_id(ctx: Context) -> str:
    """
    Retrieves a stable session ID from the MCP context.

    This function is crucial for stateful tools. It attempts to find a
    persistent session identifier from the context provided by FastMCP.
    """
    if hasattr(ctx, 'session_id') and ctx.session_id: # Ideal if FastMCP provides this directly
        return ctx.session_id
    if ctx.request_id: # Fallback, assuming request_id is stable for the session
        return ctx.request_id
    
    # If no session ID can be reliably determined, this is a problem for stateful tools.
    # For this example, we'll generate one if missing, but this means state might not persist
    # correctly across different physical requests if the transport doesn't maintain session.
    # This part is highly dependent on how FastMCP exposes transport-level session IDs.
    logger.warning("Could not determine a stable session ID from ctx.request_id or ctx.session_id. Generating a new one.")
    # This is NOT ideal for true session persistence if the client doesn't resend this ID.
    # A better approach is for the client to manage and send a session_id if the transport doesn't.
    return str(uuid.uuid4())


async def ensure_session_initialized(ctx: Context):
    """
    Helper function to ensure a session exists in the state manager.
    """
    session_id = get_stable_session_id(ctx)
    client_id = ctx.client_id if hasattr(ctx, 'client_id') else None
    await create_session_if_not_exists(session_id, client_id)
    return session_id


def register_tools(mcp: FastMCP):
    """Registers the general-purpose tools with the MCP server."""
    @mcp.tool()
    async def get_current_datetime(ctx: Context, mcp_session_id: str = None) -> str:
        """Returns the current date and time in ISO format."""
        await ensure_session_initialized(ctx)
        await ctx.info("Fetching current date and time.")
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    @mcp.tool()
    async def perform_calculation(expression: str, ctx: Context, mcp_session_id: str = None) -> str:
        """
        Evaluates a simple mathematical expression.
        
        WARNING: Uses a restricted `eval`. For production, use a dedicated
        math expression parser like `asteval` or `numexpr`.
        """
        session_id = await ensure_session_initialized(ctx)
        await ctx.info(f"Session {session_id}: Performing calculation for: {expression}")
        
        # Basic sanitization: allow only numbers, operators, parentheses, and spaces.
        if not re.fullmatch(r"^[0-9\.\+\-\*\/\(\)\s]+$", expression):
            await ctx.error("Invalid characters in expression.")
            return "Error: Invalid characters in expression."
        try:
            # Using a very restricted eval:
            allowed_names = {"__builtins__": {}} # No builtins
            result = eval(expression, allowed_names, {}) 
            await ctx.info(f"Calculation result: {result}")
            return str(result)
        except Exception as e:
            logger.error(f"Error during calculation for expression '{expression}': {e}", exc_info=True)
            await ctx.error(f"Error during calculation: {str(e)}")
            return f"Error: {str(e)}"

    @mcp.tool()
    async def store_note_in_session(note_text: str, ctx: Context, mcp_session_id: str = None) -> str:
        """Stores a textual note in the current session's context."""
        session_id = await ensure_session_initialized(ctx)
        await ctx.info(f"Session {session_id}: Storing note.")
        
        current_session_data = await get_session_context(session_id)
        
        notes_list: List[Dict[str, str]] = current_session_data.get("user_notes", [])
        notes_list.append({"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "note": note_text})
        current_session_data["user_notes"] = notes_list
        
        await update_session_context(session_id, current_session_data)
        return "Note stored successfully in session."

    @mcp.tool()
    async def retrieve_session_notes(ctx: Context, mcp_session_id: str = None) -> Dict[str, Any]:
        """Retrieves all notes stored in the current session's context."""
        session_id = await ensure_session_initialized(ctx)
        await ctx.info(f"Session {session_id}: Retrieving notes.")
        
        current_session_data = await get_session_context(session_id)
        if "user_notes" in current_session_data:
            return {"notes": current_session_data["user_notes"]}
        return {"notes": [], "message": "No notes found for this session."}

    @mcp.tool()
    async def list_uploaded_files(ctx: Context, mcp_session_id: str = None) -> Dict[str, Any]:
        """
        Retrieves a list of all files that have been uploaded and processed
        in the current session.
        """
        session_id = await ensure_session_initialized(ctx)
        await ctx.info(f"Session {session_id}: Retrieving list of uploaded files.")
        
        current_session_data = await get_session_context(session_id)
        uploaded_files_info = current_session_data.get("uploaded_csv_files", {}) # "uploaded_csv_files" is the key used in csv_rag_tool.py
        
        if not uploaded_files_info:
            return {"uploaded_files": [], "message": "No files have been uploaded and processed in this session."}
            
        files_list = []
        for file_id, info in uploaded_files_info.items():
            files_list.append({
                "file_id": file_id,
                "original_filename": info.get("original_filename", "N/A")
            })
            
        return {"uploaded_files": files_list}

    logger.info("General MCP tools registered.")
