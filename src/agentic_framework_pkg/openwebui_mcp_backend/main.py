
import uvicorn
import os
from ..logger_config import get_logger

logger = get_logger(__name__)

def start_openwebui_mcp_backend_app():
    """CLI entry point to start the OpenWebUI backend server."""
    port = int(os.getenv("OPENWEBUI_PORT", "8081"))
    host = os.getenv("OPENWEBUI_HOST", "0.0.0.0")
    
    logger.info(f"Starting OpenWebUI backend server on {host}:{port}")
    
    uvicorn.run(
        "agentic_framework_pkg.openwebui_mcp_backend.app:app",
        host=host,
        port=port,
        reload=True, # Reload server on code changes, useful for development
    )

if __name__ == "__main__":
    start_openwebui_mcp_backend_app()
