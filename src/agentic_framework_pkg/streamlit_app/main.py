"""
DEPRECATED: This Streamlit application (v1) is obsolete and has been replaced by the v2 application
in the `src/agentic_framework_pkg/streamlit_app_v2/` directory. This file is retained for
posterity and should not be used.
"""
import subprocess
import os
import sys
import logging
from dotenv import load_dotenv

from ..logger_config import get_logger # Use centralized logger
logger = get_logger(__name__)

def start_harness_cli():
    """CLI entry point to start the Streamlit test harness."""
    # Load.env if present, for local runs. Docker Compose handles env vars for containers.
    if os.path.exists(".env"):
        load_dotenv()
    elif os.path.exists("../../.env"): # If run from src/pkg/streamlit_app
         load_dotenv(dotenv_path=os.path.join(os.getcwd(), "../../.env"))


    app_py_path = os.path.join(os.path.dirname(__file__), "app.py")
    
    port = os.getenv("STREAMLIT_SERVER_PORT", "8501")
    address = os.getenv("STREAMLIT_SERVER_ADDRESS", "0.0.0.0") # Listen on all interfaces for Docker

    cmd = [
        "streamlit", "run", app_py_path,
        "--server.port", port,
        "--server.address", address,
        "--server.headless", "true", # Useful for running in containers, prevents opening browser
        "--server.enableCORS", "false", # Adjust if CORS is needed for specific scenarios
    ]
    
    logger.info(f"Starting Streamlit harness with command: {' '.join(cmd)}")
    try:
        # Using subprocess.run to execute.
        # For development, `uv run streamlit...` or `streamlit run...` directly is also common.
        # This programmatic start is more for when the script itself needs to manage the process
        # or ensure specific parameters are passed, as required by `uv run <script_name>`.
        process = subprocess.Popen(cmd)
        process.wait() # Wait for streamlit to exit
    except FileNotFoundError:
        err_msg = "'streamlit' command not found. Make sure Streamlit is installed and in your PATH."
        logger.critical(err_msg)
        print(f"Error: {err_msg}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Error running Streamlit: {e}", exc_info=True)
        print(f"Error running Streamlit: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    # This allows running the streamlit app directly using `python -m agentic_framework_pkg.streamlit_app.main`
    start_harness_cli()
