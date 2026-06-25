"""
Backend Factory for RAG Operations

Provides a factory pattern for creating the appropriate RAG backend
based on environment configuration.
"""

import os
from typing import Optional
from ..logger_config import get_logger

logger = get_logger(__name__)


class BackendFactory:
    """
    Factory for creating RAG backends based on configuration.

    Supports:
    - RAGFlow backend (production)
    - ChromaDB backend (development)
    - pgvector backend (PostgreSQL with vector extension)
    - Auto selection with fallback
    """

    @staticmethod
    def create_backend(backend_type: Optional[str] = None):
        """
        Create the appropriate backend based on configuration.

        Args:
            backend_type: Optional override for backend type.
                         If None, uses environment variable RAG_BACKEND.
                         Options: 'ragflow', 'chromadb', 'pgvector', 'auto'

        Returns:
            Backend instance (RAGFlowBackend or ChromaDB implementation)
        """
        # Determine backend type from parameter or environment
        if backend_type is None:
            backend_type = os.getenv("RAG_BACKEND", "auto")

        # Check if RAGFlow is enabled
        ragflow_enabled = os.getenv("ENABLE_RAGFLOW", "true").lower() == "true"

        logger.info(f"Creating backend: type={backend_type}, ragflow_enabled={ragflow_enabled}")

        # Handle auto selection
        if backend_type == "auto":
            if ragflow_enabled:
                backend_type = "ragflow"
                logger.info("Auto-selected RAGFlow backend (ENABLE_RAGFLOW=true)")
            else:
                backend_type = "chromadb"
                logger.info("Auto-selected ChromaDB backend (ENABLE_RAGFLOW=false)")

        # Create the appropriate backend
        if backend_type == "ragflow":
            try:
                from .knowledge_bases.ragflow import RAGFlowBackend
                backend = RAGFlowBackend()
                logger.info("Created RAGFlow backend")
                return backend
            except Exception as e:
                logger.error(f"Failed to create RAGFlow backend: {e}")
                if os.getenv("RAG_BACKEND_FALLBACK", "true").lower() == "true":
                    logger.info("Falling back to ChromaDB backend")
                    backend_type = "chromadb"
                else:
                    raise

        if backend_type == "pgvector":
            try:
                from .pgvector_backend import PgVectorBackend
                backend = PgVectorBackend()
                logger.info("Created PgVectorBackend (dedicated postgres_rag instance)")
                return backend
            except Exception as e:
                logger.error(f"Failed to create PgVectorBackend: {e}")
                if os.getenv("RAG_BACKEND_FALLBACK", "true").lower() == "true":
                    logger.warning("Falling back to ChromaDB backend")
                    backend_type = "chromadb"
                else:
                    raise

        if backend_type == "chromadb":
            try:
                from .chromadb_backend import ChromaDBBackend
                backend = ChromaDBBackend()
                logger.info("Created ChromaDB backend (via KB abstraction)")
                return backend
            except Exception as e:
                logger.error(f"Failed to create ChromaDB backend: {e}")
                raise

        raise ValueError(f"Unknown backend type: {backend_type}")

    @staticmethod
    def is_ragflow_backend() -> bool:
        """
        Check if the current configuration uses RAGFlow backend.

        Returns:
            True if RAGFlow backend is configured, False otherwise
        """
        backend_type = os.getenv("RAG_BACKEND", "auto")
        ragflow_enabled = os.getenv("ENABLE_RAGFLOW", "true").lower() == "true"

        if backend_type == "ragflow":
            return True
        elif backend_type in ("chromadb", "pgvector"):
            return False
        else:  # auto
            return ragflow_enabled