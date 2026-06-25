"""
Image handling utilities for Streamlit app.

Provides functions to detect, download, and display images from agent responses.
"""
import streamlit as st
import requests
import os
import re
from typing import List, Dict, Optional
from agentic_framework_pkg.logger_config import get_logger

logger = get_logger(__name__)

def extract_markdown_images(message_content: str) -> List[Dict[str, str]]:
    """
    Extract markdown image syntax from agent messages.

    Looks for patterns like: ![alt text](url)

    Returns:
        List of dicts with 'alt' and 'url' keys
    """
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    matches = re.findall(pattern, message_content)
    return [{"alt": alt, "url": url} for alt, url in matches]

def extract_plot_references(message_content: str) -> List[str]:
    """
    Extract plot filenames and URLs from agent messages.

    Looks for patterns like:
    - filename: abc123.png
    - plot available at: http://...
    - saved to: data/uploaded_files/plots/...
    """
    patterns = [
        r"filename[:\s]+'?([a-f0-9]+\.[a-z]+)'?",  # filename: abc123.png
        r"plot available at:\s*(http[^\s]+)",        # plot URL
        r"saved to:\s*([^\s]+\.(?:png|jpg|jpeg|svg|pdf))",  # file path
    ]

    references = []
    for pattern in patterns:
        matches = re.findall(pattern, message_content, re.IGNORECASE)
        references.extend(matches)

    return references

def display_plots_from_message(message_content: str):
    """
    Scan a message for plot references and display them in Streamlit.
    Uses authenticated endpoints for secure access.

    Priority order:
    1. Markdown image syntax: ![alt](url)
    2. Legacy plot references (filename, URL patterns)
    """
    # Try markdown syntax first (highest priority)
    markdown_images = extract_markdown_images(message_content)

    if markdown_images:
        st.write("**📊 Generated Plots:**")

        # Get the user's auth token for authenticated requests
        auth_token = st.session_state.get('api_key')

        for img in markdown_images:
            url = img["url"]
            caption = img["alt"] or "Plot"

            try:
                # Try to display the image from URL
                if auth_token and url.startswith('http'):
                    headers = {'Authorization': f'Bearer {auth_token}'}
                    response = requests.get(url, headers=headers)
                    if response.status_code == 200:
                        st.image(response.content, caption=caption)
                    else:
                        st.write(f"🔗 [{caption}]({url})")
                else:
                    # No auth token or local file path
                    st.image(url, caption=caption)
            except Exception as e:
                logger.warning(f"Could not display markdown image {url}: {e}")
                st.write(f"🔗 [{caption}]({url})")
        return

    # Fallback to legacy plot references
    plot_refs = extract_plot_references(message_content)

    if not plot_refs:
        return

    st.write("**📊 Generated Plots:**")

    # Get the user's auth token for authenticated requests
    auth_token = st.session_state.get('api_key')
    agent_gateway_url = os.getenv("AGENT_GATEWAY_URL", "http://localhost:8083/v1")

    for ref in plot_refs:
        if ref.startswith('http') and 'v1/plots' in ref:
            # This is already a secure URL through agent gateway
            try:
                # For Streamlit display, we need to make authenticated requests
                if auth_token:
                    headers = {'Authorization': f'Bearer {auth_token}'}
                    response = requests.get(ref, headers=headers)
                    if response.status_code == 200:
                        st.image(response.content, caption=f"Plot: {os.path.basename(ref)}")
                    else:
                        st.write(f"🔗 [View Plot]({ref}) (Authentication required)")
                else:
                    st.write(f"🔗 [View Plot]({ref}) (Login required)")
            except Exception as e:
                st.write(f"🔗 [View Plot]({ref})")
                
        elif ref.endswith(('.png', '.jpg', '.jpeg', '.svg', '.pdf')):
            # File reference - construct secure URL through agent gateway
            filename = os.path.basename(ref)
            secure_url = f"{agent_gateway_url}/plots/{filename}"
            
            # First try local file access (within container)
            local_path = f"/app/data/uploaded_files/plots/{filename}"
            if os.path.exists(local_path):
                try:
                    st.image(local_path, caption=f"Plot: {filename}")
                    continue
                except Exception as e:
                    logger.warning(f"Could not display local image {local_path}: {e}")
            
            # Fallback to secure URL with authentication
            if auth_token:
                try:
                    headers = {'Authorization': f'Bearer {auth_token}'}
                    response = requests.get(secure_url, headers=headers)
                    if response.status_code == 200:
                        st.image(response.content, caption=f"Plot: {filename}")
                    else:
                        st.write(f"📁 Plot file: `{filename}` - 🔗 [View Plot]({secure_url})")
                except Exception as e:
                    st.write(f"📁 Plot file: `{filename}` - 🔗 [View Plot]({secure_url})")
            else:
                st.write(f"📁 Plot file: `{filename}` (Login required for access)")

def check_for_plots_in_tool_outputs(run_steps) -> List[Dict]:
    """
    Extract plot information from OpenAI run steps tool outputs.
    """
    plots = []
    
    for step in run_steps.data:
        if step.step_details.type == "tool_calls":
            for tool_call in step.step_details.tool_calls:
                if tool_call.function.name == "ExecuteCode" and tool_call.outputs:
                    for output in tool_call.outputs:
                        try:
                            import json
                            output_data = json.loads(output.logs)
                            if "plots" in output_data:
                                plots.extend(output_data["plots"])
                        except (json.JSONDecodeError, KeyError):
                            continue
    
    return plots

def extract_plots_from_response_api(response) -> List[Dict]:
    """
    Extract plot information from Responses API (chat.completions) response.

    The Responses API returns tool calls in the message object, and we need to
    extract the plots array from execute_code tool outputs.

    Args:
        response: OpenAI Responses API response object

    Returns:
        List of plot dictionaries with plot_url, filename, etc.
    """
    plots = []

    try:
        # Responses API stores tool calls differently than Assistants API
        message = response.choices[0].message

        # Log the response structure for debugging
        logger.info(f"🔍 PLOT EXTRACTION: Inspecting Responses API message")
        logger.info(f"   - Message role: {message.role}")
        logger.info(f"   - Message content length: {len(message.content) if message.content else 0}")
        logger.info(f"   - Has tool_outputs: {hasattr(message, 'tool_outputs') and message.tool_outputs is not None}")

        # Check if message has tool_outputs attribute (Responses API format with plot metadata)
        if hasattr(message, 'tool_outputs') and message.tool_outputs:
            logger.info(f"   - Number of tool_outputs: {len(message.tool_outputs)}")

            for idx, tool_output in enumerate(message.tool_outputs):
                logger.info(f"   - Tool output #{idx}: type={getattr(tool_output, 'type', 'N/A')}, name={getattr(getattr(tool_output, 'function', None), 'name', 'N/A')}")

                # Look for execute_code tool outputs
                if hasattr(tool_output, 'function') and tool_output.function.name in ['execute_code', 'ExecuteCode']:
                    logger.info(f"   - Found execute_code tool output!")

                    # The output might be in function.output or we need to parse arguments
                    if hasattr(tool_output.function, 'output'):
                        try:
                            import json
                            output_data = json.loads(tool_output.function.output)
                            logger.info(f"   - Parsed output data, keys: {output_data.keys()}")

                            if "plots" in output_data and output_data["plots"]:
                                logger.info(f"   - Found {len(output_data['plots'])} plots in output!")
                                plots.extend(output_data["plots"])
                            else:
                                logger.info(f"   - No plots found in output data")
                        except (json.JSONDecodeError, AttributeError) as e:
                            logger.warning(f"   - Failed to parse tool output: {e}")
                    else:
                        logger.info(f"   - Tool function has no output attribute")
        else:
            logger.info(f"   - No tool_outputs found in message")

    except Exception as e:
        logger.error(f"❌ Error extracting plots from Responses API: {e}", exc_info=True)

    if plots:
        logger.info(f"✅ Successfully extracted {len(plots)} plots from Responses API")
    else:
        logger.info(f"ℹ️  No plots found in Responses API response")

    return plots

def display_plots_from_tool_outputs(plots: List[Dict]):
    """
    Display plots extracted from tool outputs.
    """
    if not plots:
        return

    st.write("**📊 Tool Generated Plots:**")

    for plot in plots:
        if "plot_url" in plot:
            try:
                st.image(plot["plot_url"], caption=f"Plot ({plot.get('format', 'unknown')})")
            except Exception as e:
                st.write(f"🔗 [View Plot]({plot['plot_url']})")

        elif "filename" in plot:
            st.write(f"📁 Generated plot: `{plot['filename']}`")

        elif "relative_path" in plot:
            local_path = f"/app/{plot['relative_path']}"
            if os.path.exists(local_path):
                try:
                    st.image(local_path, caption=f"Plot: {os.path.basename(local_path)}")
                except Exception as e:
                    st.write(f"📁 Plot saved to: `{plot['relative_path']}`")