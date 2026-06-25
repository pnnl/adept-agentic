import uvicorn
import os
from ..logger_config import get_logger

logger = get_logger(__name__)

def start_agent_gateway():
    """CLI entry point to start the Agent Gateway server."""
    port = int(os.getenv("AGENT_GATEWAY_PORT", "8081"))
    host = os.getenv("AGENT_GATEWAY_HOST", "0.0.0.0")

    logger.info(f"Starting Agent Gateway server on {host}:{port}")

    uvicorn.run(
        "agentic_framework_pkg.agent_gateway.app:app",
        host=host,
        port=port,
        reload=True,  # Reload server on code changes, useful for development
        reload_dirs=["/app/src"],  # Only watch source code, not data directories (Session 48)
        reload_excludes=["**/data/**", "**/postgres_data/**", "**/__pycache__/**", "**/*.pyc"],
    )

if __name__ == "__main__":
    start_agent_gateway()