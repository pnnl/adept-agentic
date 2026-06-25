"""DEPRECATED: This Streamlit application (v1) is obsolete and has been replaced by the v2 application
in the `src/agentic_framework_pkg/streamlit_app_v2/` directory. This file is retained for
posterity and should not be used.
"""

import streamlit as st
import os
import uuid
import json # For displaying dict results
import asyncio
import base64
from typing import List, Dict, Any

# Apply nest_asyncio at the top of the application
import nest_asyncio
nest_asyncio.apply()

# Get or create a persistent event loop
# This setup is now more robust with nest_asyncio
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Adjust the import path based on your project structure if this file is moved
from agentic_framework_pkg.orchestration_service.scientific_workflow.langchain_agent import ScientificWorkflowAgent # noqa: E402
from agentic_framework_pkg.logger_config import get_logger # noqa: E402
try:
    from fastmcp import Client as MCPClient
    # Langchain callback imports
    from langchain_core.callbacks.base import BaseCallbackHandler
    from langchain_core.messages import ToolMessage
    from langchain_core.agents import AgentAction, AgentFinish
    from langchain_core.outputs import LLMResult
except ImportError:
    st.error("FastMCP client library not found. Please ensure 'fastmcp' is installed.")
    st.stop()

logger = get_logger(__name__)

# --- Configuration ---
st.set_page_config(page_title="Agentic Framework UI", layout="wide")

# The URL for the main MCP server, used for direct tool calls like file uploads.
# This is set by Helm in Kubernetes or docker-compose/.env for local dev.
# The default points to localhost for easy `streamlit run app.py` development.
DEFAULT_MCP_SERVER_URL = os.getenv("DEFAULT_MCP_SERVER_URL", "http://localhost:8080/mcp")
logger.info(f"Streamlit App: Using main MCP Server at {DEFAULT_MCP_SERVER_URL}")

# Determine Shared Upload Directory:
# Prioritize the "SHARED_UPLOAD_DIR" environment variable (can be set in .env for local testing).
# Defaults to "/app/shared_uploads" if the environment variable is not set (for containerized runs).
_DEFAULT_SHARED_UPLOAD_DIR_IN_CONTAINER = "/app/shared_uploads"
SHARED_UPLOAD_DIR = os.getenv("SHARED_UPLOAD_DIR", _DEFAULT_SHARED_UPLOAD_DIR_IN_CONTAINER)
logger.info(f"Streamlit App: Effective SHARED_UPLOAD_DIR is {SHARED_UPLOAD_DIR}")
os.makedirs(SHARED_UPLOAD_DIR, exist_ok=True)

# --- Session State Initialization ---
if "mcp_session_id" not in st.session_state:
    # Debugging: Check environment variables are loaded
    logger.info("Checking env vars in Streamlit app:")
    logger.info(f"AZURE_API_KEY: {'Set' if os.getenv('AZURE_API_KEY') else 'Not Set'}")
    logger.info(f"AZURE_API_BASE: {'Set' if os.getenv('AZURE_API_BASE') else 'Not Set'}")
    logger.info(f"AZURE_API_VERSION: {'Set' if os.getenv('AZURE_API_VERSION') else 'Not Set'}")
    logger.info(f"LANGCHAIN_LLM_MODEL: {'Set' if os.getenv('LANGCHAIN_LLM_MODEL') else 'Not Set'}")
    logger.info(f"OPENAI_API_KEY: {'Set' if os.getenv('OPENAI_API_KEY') else 'Not Set'}") # type: ignore
    logger.info(f"DEFAULT_MCP_SERVER_URL (used by Streamlit): {DEFAULT_MCP_SERVER_URL}")
    st.session_state.mcp_session_id = str(uuid.uuid4())
    logger.info(f"New Streamlit session started. MCP Session ID: {st.session_state.mcp_session_id}")

if "chat_history" not in st.session_state:
    st.session_state.chat_history: List[Dict[str, str]] = [] # Stores {"role": "user/assistant", "content": "..."}

if "agent_thoughts" not in st.session_state:
    st.session_state.agent_thoughts: List[str] = []

# --- Custom Langchain Callback Handler for Streamlit ---
class StreamlitThoughtsCallbackHandler(BaseCallbackHandler):
    """A callback handler that writes agent thoughts to Streamlit session state."""

    def _ensure_agent_thoughts_initialized(self):
        if "agent_thoughts" not in st.session_state:
            st.session_state.agent_thoughts = []

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        self._ensure_agent_thoughts_initialized()
        st.session_state.agent_thoughts.append("🧠 LLM thinking...")

    def on_agent_action(self, action: AgentAction, **kwargs: Any) -> None:
        self._ensure_agent_thoughts_initialized()
        # First, log the thought process that led to the action
        if action.log:
            log_lines = action.log.splitlines()
            thought_lines = [line for line in log_lines if not line.startswith("Invoking") and not line.startswith("Action:")]
            if thought_lines:
                thought_content = "\n".join(thought_lines).strip()
                st.session_state.agent_thoughts.append(f"🤔 **Thought:**\n```\n{thought_content}\n```")

        # Then, log the action itself, formatting the input as a JSON block for readability
        try:
            # Pretty-print if tool_input is a dict, otherwise just show as string
            tool_input_str = json.dumps(action.tool_input, indent=2) if isinstance(action.tool_input, dict) else str(action.tool_input)
        except Exception:
            tool_input_str = str(action.tool_input)
        tool_call_str = f"**🛠️ Action:** `{action.tool}`\n\n**Input:**\n```json\n{tool_input_str}\n```"
        st.session_state.agent_thoughts.append(tool_call_str)

    def on_tool_end(self, output: str, name: str, **kwargs: Any) -> None:
        self._ensure_agent_thoughts_initialized()
        st.session_state.agent_thoughts.append(f"**✅ Tool Output (`{name}`):**\n```json\n{output}\n```\n---")

    def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> None:
        self._ensure_agent_thoughts_initialized()
        final_answer_content = finish.return_values.get('output', '')
        st.session_state.agent_thoughts.append(f"**🏁 Agent Finished.**\n\n**Final Answer:**\n{final_answer_content}")

    def on_chain_error(self, error: BaseException, **kwargs: Any) -> None:
        self._ensure_agent_thoughts_initialized()
        st.session_state.agent_thoughts.append(f"❌ Error: {error}")

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        self._ensure_agent_thoughts_initialized()
        st.session_state.agent_thoughts.append(f"❌ Tool Error: {error}")

# --- UI Rendering ---
st.title("🔬 Agentic Scientific Workflow Assistant")
st.caption(f"MCP Session ID: {st.session_state.mcp_session_id} | Main Server: {DEFAULT_MCP_SERVER_URL}")

# Main layout (now a single column as thoughts are in sidebar)
# chat_col, thoughts_col = st.columns([4, 1]) # Removed columns

with st.container(): # Use a container for the main chat area
    # Display chat messages
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

# # Add the checkbox for enabling Chain-of-Thought / LangGraph
# # Placed before the chat input for better visibility of mode selection
# use_cot_research_mode = st.checkbox(
#     "🔬 Research mode (enable Chain-of-Thought / LangGraph)", 
#     value=st.session_state.get("use_cot_research_mode", False), # Persist checkbox state
#     key="use_cot_research_mode_checkbox"
# )
# st.session_state.use_cot_research_mode = use_cot_research_mode # Update session state

# User input
user_query = st.chat_input("Ask the agent...")

async def get_agent_response(query: str, history: List[Dict[str, str]], callbacks: List[BaseCallbackHandler], recursion_limit: int = 40) -> Dict[str, Any]:
    """
    Helper async function to create and run the agent.
    This ensures event loop compatibility with Streamlit.
    """
    # Create a new agent instance for each request to ensure it's on the current event loop.
    try:
        agent = await ScientificWorkflowAgent.create(mcp_session_id=st.session_state.mcp_session_id)
        logger.info(f"ScientificWorkflowAgent created for session {st.session_state.mcp_session_id}")
    except Exception as e:
        st.error(f"Failed to initialize agent: {e}")
        logger.error(f"Agent initialization error for session {st.session_state.mcp_session_id}: {e}", exc_info=True)
        return {"output": f"Failed to initialize agent: {e}"}

    try:
        response_dict = await agent.arun(user_input=query, chat_history=history, callbacks=callbacks, recursion_limit=recursion_limit)
        return response_dict
    except Exception as e:
        logger.error(f"Error during agent execution for session {st.session_state.mcp_session_id}: {e}", exc_info=True)
        return {"output": f"An error occurred while processing your request: {e}"}

if user_query:
    # Add user message to chat history
    st.session_state.chat_history.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    # Clear previous thoughts and prepare callback
    st.session_state.agent_thoughts = []
    streamlit_callback = StreamlitThoughtsCallbackHandler()

    # Get agent response
    with st.spinner("Agent is thinking... (see thoughts in the sidebar)"):
        agent_response_dict = loop.run_until_complete(
            get_agent_response(
                user_query, 
                st.session_state.chat_history[:-1], # Pass history up to the previous message
                [streamlit_callback],
                st.session_state.get("recursion_limit", 25))
        )
        agent_response_content = agent_response_dict.get("output", "Agent did not provide a standard output.")

    # Add agent response to chat history
    st.session_state.chat_history.append({"role": "assistant", "content": agent_response_content})
    with st.chat_message("assistant"):
        st.markdown(agent_response_content)

        # Add an expander for the agent's thoughts right under the answer.
        if st.session_state.agent_thoughts:
            with st.expander("Show Agent Thoughts 🧠"):
                st.markdown("\n\n".join(st.session_state.agent_thoughts), unsafe_allow_html=True)

        # Check for and display any plots from the last tool call
        # Read from the new 'full_tool_outputs' field in the agent's final state
        full_tool_outputs = agent_response_dict.get("full_graph_state", {}).get("full_tool_outputs", [])
        if full_tool_outputs:
            # Get the last tool output dictionary
            last_tool_output = full_tool_outputs[-1]
            if isinstance(last_tool_output, dict) and "plots" in last_tool_output and last_tool_output["plots"]:
                st.write("I have generated the following plot(s):")
                for plot in last_tool_output["plots"]:
                    try:
                        # Prioritize rendering from base64 for reliability
                        if plot.get('content_base64') and 'omitted' not in plot.get('content_base64'):
                            if plot.get('format') == 'html':
                                html_content = base64.b64decode(plot['content_base64']).decode('utf-8')
                                st.html(html_content, height=600, scrolling=True)
                            else: # Assume other formats are standard images
                                img_bytes = base64.b64decode(plot['content_base64'])
                                st.image(img_bytes, caption=f"Generated Plot ({plot.get('format', 'N/A')})")
                        elif plot.get('plot_url'): # Fallback to URL if no base64 content
                            st.image(plot['plot_url'], caption=f"Generated Plot ({plot.get('format', 'N/A')})")
                    except Exception as e:
                        st.error(f"Error decoding or displaying plot: {e}")


# --- Sidebar for advanced options or info (optional) ---
with st.sidebar:
    st.header("About")
    st.markdown(
        "This is a Streamlit UI for the Agentic Framework. "
        "It interacts with an MCP server and a Langchain-based scientific workflow agent."
    )
    if st.button("Clear Chat History"):
        st.session_state.chat_history = []
        st.session_state.agent_thoughts = [] # Also clear thoughts
        logger.info(f"Chat history cleared for session {st.session_state.mcp_session_id}")
        st.rerun()
    
    st.header("Agent Configuration")
    recursion_limit = st.number_input(
        "Set Agent Recursion Limit", 
        min_value=5, 
        max_value=100, 
        value=st.session_state.get("recursion_limit", 25), 
        step=5,
        help="Sets the maximum number of steps the agent can take. Increase this for very complex, multi-step tasks."
    )
    st.session_state.recursion_limit = recursion_limit
    
    # # Agent Thoughts section moved to sidebar
    # with st.expander("Agent Thoughts 🧠", expanded=True):
    #     # This placeholder will be updated by the callback handler
    #     thoughts_container = st.empty()
    #     if st.session_state.agent_thoughts:
    #         thoughts_container.markdown("\n\n".join(st.session_state.agent_thoughts), unsafe_allow_html=True)
    #     else:
    #         thoughts_container.markdown("_Agent thoughts will appear here_..." ) # Initial message/placeholder


    st.header("Environment Info (for debugging)")
    st.text(f"Effective Main MCP Server URL: {DEFAULT_MCP_SERVER_URL}")
    langchain_llm = os.getenv("LANGCHAIN_LLM_MODEL", "gpt-3.5-turbo (default)")
    st.text(f"Langchain LLM: {langchain_llm}")

    # Note: To test document uploads, you would add st.file_uploader and then
    # call the 'register_uploaded_csv' MCP tool. The file_id returned
    # would then be used in queries to 'query_csv_data' via the agent.
    # This example focuses on the chat interaction with the pre-configured agent.
    
    # --- document RAG Tool Testing Section ---
    with st.expander("document RAG Tool Test"):
        supported_types = ["csv", "xlsx", "docx", "pdf", "png", "jpg", "jpeg", "gif", "webp", "txt", "tex"]
        uploaded_files = st.file_uploader(
            f"Upload Documents for RAG ({', '.join(supported_types)})", 
            type=supported_types, 
            key="doc_uploader_main_app",
            accept_multiple_files=True)  # Allow multiple files

        if uploaded_files:
            st.write(f"{len(uploaded_files)} file(s) selected.")
            if st.button("Process Uploaded Documents for RAG", key="process_csv_button_main_app"):
                results_placeholder = st.empty()
                all_results = []
                status_placeholder = st.empty()  # Create a placeholder for status messages
                for uploaded_file in uploaded_files:
                    status_placeholder.info(f"Processing {uploaded_file.name}...")
                    original_filename = uploaded_file.name
                    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
                    sanitized_base_filename = "".join(c if c in safe_chars else '_' for c in os.path.splitext(original_filename)[0])
                    file_extension = os.path.splitext(original_filename)[1]
                    unique_filename_part = str(uuid.uuid4())[:8]
                    final_sanitized_filename = f"{sanitized_base_filename}_{st.session_state.mcp_session_id[:8]}_{unique_filename_part}{file_extension}"
                    
                    secure_shared_file_path = os.path.join(SHARED_UPLOAD_DIR, final_sanitized_filename)

                    try:
                        with open(secure_shared_file_path, "wb") as f:
                            f.write(uploaded_file.getvalue())
                        st.write(f"File saved to shared volume at internal path: {secure_shared_file_path}")

                        async def register_document_async_rag():
                            try:
                                async with MCPClient(DEFAULT_MCP_SERVER_URL) as client:
                                    registration_params = {
                                        "file_path_on_server": secure_shared_file_path,
                                        "original_filename": original_filename,
                                        "mcp_session_id": st.session_state.mcp_session_id,
                                    }
                                    result = await client.call_tool("process_uploaded_file", registration_params)
                                    
                                    if isinstance(result, list) and len(result) > 0:
                                        first_content_item = result[0]
                                        if hasattr(first_content_item, 'text') and isinstance(first_content_item.text, str):
                                            try:
                                                parsed_data = json.loads(first_content_item.text)
                                                all_results.append({original_filename: parsed_data})
                                                results_placeholder.json(all_results)
                                            except json.JSONDecodeError:
                                                all_results.append({original_filename: {"error": "Failed to parse JSON response"}})
                                                results_placeholder.json(all_results)
                                        else:
                                            all_results.append({original_filename: {"error": "Unexpected tool response format"}})
                                            results_placeholder.json(all_results)
                                    else:
                                        all_results.append({original_filename: {"error": "Empty or invalid tool response"}})
                                        results_placeholder.json(all_results)
                            except Exception as e:
                                all_results.append({original_filename: {"error": str(e)}})
                                results_placeholder.json(all_results)
                        
                        asyncio.run(register_document_async_rag())

                    except Exception as e:
                        all_results.append({original_filename: {"error": f"Failed to save file: {e}"}})
                        results_placeholder.json(all_results)
                status_placeholder.empty()  # Clear the status message after all files are processed

        st.markdown("Once a document is processed, you can ask the agent to query it using its `file_id`.")
        st.text_input("Current RAG File ID (if processed)", value=st.session_state.get("current_rag_file_id", "N/A"), disabled=True, key="current_rag_file_id_display")

    # --- Video Transcription Tool Testing Section (New) ---
    with st.expander("Video Transcription & Summarization (HPC)"):
        video_input_type = st.radio("Video Input Type", ["URL", "Upload"], key="video_input_type_selector_hpc")
        
        video_path_or_url_for_agent_tool = None # This will hold the final path/URL for the agent
        
        if video_input_type == "URL":
            video_url = st.text_input("Enter Video URL (e.g., YouTube)", key="video_url_input_hpc")
            if video_url:
                video_path_or_url_for_agent_tool = video_url
                
        elif video_input_type == "Upload":
            supported_video_types = ["mp4", "mkv", "webm", "mov", "avi", "flv", "mpeg", "mpg", "wmv"]
            uploaded_video_file = st.file_uploader(
                f"Upload Video File ({', '.join(supported_video_types)})",
                type=supported_video_types,
                key="video_uploader_hpc_tool"
            )
            if uploaded_video_file is not None:
                st.write(f"Uploaded: {uploaded_video_file.name} (Size: {uploaded_video_file.size} bytes)")
                
                original_filename = uploaded_video_file.name
                safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
                sanitized_base_filename = "".join(c if c in safe_chars else '_' for c in os.path.splitext(original_filename)[0])
                file_extension = os.path.splitext(original_filename)[1]
                unique_filename_part = str(uuid.uuid4())[:8]
                final_sanitized_filename = f"video_{sanitized_base_filename}_{st.session_state.mcp_session_id[:8]}_{unique_filename_part}{file_extension}"
                
                # SHARED_UPLOAD_DIR is defined at the top of app.py
                # This path needs to be absolute from the perspective of the HPC server container
                # Dockerfile.hpc mounts shared_uploads to /app/data/uploaded_files
                path_inside_container = os.path.join("/app/data/uploaded_files", final_sanitized_filename)
                host_path_for_saving = os.path.join(SHARED_UPLOAD_DIR, final_sanitized_filename) # Path for Streamlit to save to
                
                try:
                    with open(host_path_for_saving, "wb") as f:
                        f.write(uploaded_video_file.getvalue())
                    st.info(f"Video saved to shared volume. HPC server will access it at: {path_inside_container}")
                    video_path_or_url_for_agent_tool = path_inside_container # Agent tool needs the path *inside the HPC container*
                except Exception as e:
                    st.error(f"Error saving uploaded video to shared volume: {e}")
                    logger.error("Error saving uploaded video", exc_info=True)

        whisper_model_option = st.selectbox(
            "Whisper Model Size",
            ("tiny", "base", "small", "medium", "large"),
            index=1, # Default to 'base'
            key="whisper_model_selector_hpc_tool"
        )

        if st.button("Transcribe and Summarize Video via Agent", key="run_video_transcription_agent_button"):
            if video_path_or_url_for_agent_tool:
                # Construct the query for the Langchain agent
                agent_query = (
                    f"Please transcribe and summarize the video from '{video_path_or_url_for_agent_tool}' "
                    f"using the '{whisper_model_option}' Whisper model."
                )
                st.info(f"Sending query to agent: {agent_query}")

                # Add user message to chat history and display it
                st.session_state.chat_history.append({"role": "user", "content": agent_query})
                with st.chat_message("user"):
                    st.markdown(agent_query)

                st.session_state.agent_thoughts = []
                streamlit_callback = StreamlitThoughtsCallbackHandler()
                
                with st.spinner("Agent is processing video transcription request... (see main chat for progress and thoughts)"):
                    agent_response_dict = asyncio.run(
                        get_agent_response(
                            agent_query,
                            st.session_state.chat_history[:-1],
                            [streamlit_callback]
                        )
                    )
                    agent_response_content = agent_response_dict.get("output", "Agent did not provide a standard output.")

                st.session_state.chat_history.append({"role": "assistant", "content": agent_response_content})
                with st.chat_message("assistant"):
                    st.markdown(agent_response_content)
                st.success("Video processing request completed by agent. See main chat for results.")
            else:
                st.warning("Please provide a video URL or upload a video file.")

logger.debug(f"Streamlit app script execution finished for session {st.session_state.mcp_session_id}.")
