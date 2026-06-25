import os
from fastmcp import FastMCP
from ..logger_config import get_logger

logger = get_logger(__name__)

# Initialize FastMCP instance for the Sandbox server
sandbox_mcp = FastMCP(
    name=os.getenv("SANDBOX_MCP_SERVER_NAME", "AgenticFramework_Sandbox_MCP"),
    instructions="This MCP server provides a tool for executing Python code in a secure sandbox.",
    # NOTE: stateless_http=True is passed to http_app() in main.py, not here.
    # FastMCP >=2.14 deprecated constructor kwargs; they must go in http_app().
)

def setup_plots_directory():
    """Setup plots directory for secure file serving."""
    # The plots directory is inside the shared_uploads volume at /app/data/uploaded_files
    # TODO: Need to remove this hardcoded path and ensure that it is configurable
    plots_dir = "/app/data/uploaded_files/plots"
    
    # Check if parent directory (mounted volume) exists
    # TODO: Need to remove this hardcoded path and ensure that it is configurable
    parent_dir = "/app/data/uploaded_files"
    if not os.path.exists(parent_dir):
        logger.warning(f"Parent directory {parent_dir} does not exist, plots will be stored in temp location")
        # Use a fallback directory for testing or non-volume environments
        # TODO: Need to remove this hardcoded path and ensure that it is configurable
        plots_dir = "/tmp/plots"
        parent_dir = "/tmp"
    
    try:
        os.makedirs(plots_dir, exist_ok=True)
        logger.info(f"Successfully created plots directory: {plots_dir}")
    except PermissionError as e:
        logger.warning(f"Cannot create plots directory {plots_dir} due to permissions: {e}")
        # Don't fail startup - plots might work even without pre-creating the directory
        # The llm-sandbox tool will handle directory creation when needed
    except Exception as e:
        logger.error(f"Unexpected error creating plots directory {plots_dir}: {e}")
    
    return plots_dir


