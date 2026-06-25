# src/agentic_framework_pkg/streamlit_app_v2/main.py
import subprocess
import os
import sys
from dotenv import load_dotenv

from ..logger_config import get_logger
logger = get_logger(__name__)

def start_harness_cli():
    """CLI entry point to start the Streamlit v2 test harness."""
    load_dotenv()

    app_py_path = os.path.join(os.path.dirname(__file__), "Chat.py")

    port = os.getenv("STREAMLIT_V2_SERVER_PORT", "8503")
    address = os.getenv("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")

    # Get base URL path from environment (for Nginx proxy routing)
    base_url_path = os.getenv("STREAMLIT_BASE_URL_PATH", "")

    cmd = [
        "streamlit", "run", app_py_path,
        "--server.port", port,
        "--server.address", address,
        "--server.headless", "true",
        "--server.enableCORS", "false",
        "--server.enableXsrfProtection", "false",
    ]

    # Add base URL path if specified
    if base_url_path:
        cmd.extend(["--server.baseUrlPath", base_url_path])

    logger.info(f"Starting Streamlit v2 harness with command: {' '.join(cmd)}")
    try:
        process = subprocess.Popen(cmd)
        process.wait()
    except FileNotFoundError:
        err_msg = "'streamlit' command not found. Make sure Streamlit is installed and in your PATH."
        logger.critical(err_msg)
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Error running Streamlit v2: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    start_harness_cli()
