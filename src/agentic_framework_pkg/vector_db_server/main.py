# DEPRECATED
import os
import chromadb.cli
from ..logger_config import get_logger

logger = get_logger(__name__)

def get_chroma_db_path():
    """Determines the ChromaDB path based on the environment."""
    if os.getenv("CHROMA_DB_PATH"):
        return os.getenv("CHROMA_DB_PATH")
    
    # Check if running inside a Docker container
    if os.path.exists('/.dockerenv'):
        return "/app/data/vector_db_persistence"
    else:
        # Use a local path for non-Docker environments
        local_path = os.path.join(os.getcwd(), "data", "vector_db_persistence")
        return local_path

def start_vector_db_server():
    """CLI entry point to start the vector database server."""
    port = int(os.getenv("VECTOR_DB_PORT", "8001"))
    host = os.getenv("VECTOR_DB_HOST", "0.0.0.0")
    path = get_chroma_db_path()

    logger.info(f"Starting ChromaDB vector database server on {host}:{port}")
    logger.info(f"Persistent storage path: {path}")

    # Ensure the directory exists
    os.makedirs(path, exist_ok=True)

    chromadb.cli.run(port=port, host=host, path=path)

if __name__ == "__main__":
    start_vector_db_server()
