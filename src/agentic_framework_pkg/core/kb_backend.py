"""
Knowledge Base Backend Abstraction

Provides a common interface for different knowledge base backends (RAGFlow, ChromaDB, LlamaIndex)
to enable backend switching without code changes and support hybrid approaches.
"""

import os
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Union
from datetime import datetime
from enum import Enum

from ..logger_config import get_logger

logger = get_logger(__name__)


class IndexVisibility(str, Enum):
    """Access scope for RAG indexes and knowledge bases."""
    SESSION = "session"   # Scoped to current MCP session only
    USER = "user"         # Persists across sessions for the owning user
    WORLD = "world"       # Accessible to any authenticated user


class DocumentStatus(Enum):
    """Document processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class QueryResult:
    """Standardized query result format"""

    def __init__(
        self,
        chunk_id: str,
        content: str,
        score: float,
        metadata: Optional[Dict[str, Any]] = None,
        source_document: Optional[str] = None,
        page_number: Optional[int] = None,
        chunk_index: Optional[int] = None
    ):
        self.chunk_id = chunk_id
        self.content = content
        self.score = score
        self.metadata = metadata or {}
        self.source_document = source_document
        self.page_number = page_number
        self.chunk_index = chunk_index

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata,
            "source_document": self.source_document,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index
        }


class KnowledgeBaseInfo:
    """Knowledge base metadata"""

    def __init__(
        self,
        kb_id: str,
        name: str,
        description: Optional[str] = None,
        owner_id: Optional[str] = None,
        session_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        document_count: int = 0,
        total_chunks: int = 0,
        backend_type: Optional[str] = None
    ):
        self.kb_id = kb_id
        self.name = name
        self.description = description
        self.owner_id = owner_id
        self.session_id = session_id
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.document_count = document_count
        self.total_chunks = total_chunks
        self.backend_type = backend_type

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "kb_id": self.kb_id,
            "name": self.name,
            "description": self.description,
            "owner_id": self.owner_id,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "document_count": self.document_count,
            "total_chunks": self.total_chunks,
            "backend_type": self.backend_type
        }


class KnowledgeBaseBackend(ABC):
    """
    Abstract interface for knowledge base backends.

    All implementations must provide these core operations while maintaining
    consistent behavior and return types.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize backend with configuration.

        Args:
            config: Backend-specific configuration
        """
        self.config = config or {}
        self.backend_name = self.__class__.__name__

    @abstractmethod
    async def create_kb(
        self,
        name: str,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        owner_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> str:
        """
        Create a new knowledge base.

        Args:
            name: Knowledge base name
            description: Optional description
            config: Additional backend-specific configuration
            owner_id: Owner user ID for access control
            session_id: Session ID for isolation

        Returns:
            Knowledge base ID

        Raises:
            Exception: On creation failure
        """
        pass

    @abstractmethod
    async def delete_kb(
        self,
        kb_id: str
    ) -> bool:
        """
        Delete a knowledge base and all its contents.

        Args:
            kb_id: Knowledge base ID

        Returns:
            True if successful

        Raises:
            Exception: On deletion failure
        """
        pass

    @abstractmethod
    async def get_kb_info(
        self,
        kb_id: str
    ) -> KnowledgeBaseInfo:
        """
        Get knowledge base information.

        Args:
            kb_id: Knowledge base ID

        Returns:
            Knowledge base metadata

        Raises:
            Exception: If KB not found
        """
        pass

    @abstractmethod
    async def list_kbs(
        self,
        owner_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> List[KnowledgeBaseInfo]:
        """
        List knowledge bases.

        Args:
            owner_id: Filter by owner
            session_id: Filter by session

        Returns:
            List of knowledge base info
        """
        pass

    @abstractmethod
    async def ingest_document(
        self,
        kb_id: str,
        file_path: str,
        file_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None
    ) -> str:
        """
        Ingest a document into a knowledge base.

        Args:
            kb_id: Knowledge base ID
            file_path: Path to document file
            file_id: Optional file identifier
            metadata: Document metadata
            chunk_size: Chunking size
            chunk_overlap: Chunk overlap

        Returns:
            Document ID

        Raises:
            Exception: On ingestion failure
        """
        pass

    @abstractmethod
    async def delete_document(
        self,
        kb_id: str,
        doc_id: str
    ) -> bool:
        """
        Delete a document from a knowledge base.

        Args:
            kb_id: Knowledge base ID
            doc_id: Document ID

        Returns:
            True if successful

        Raises:
            Exception: On deletion failure
        """
        pass

    @abstractmethod
    async def get_document_status(
        self,
        kb_id: str,
        doc_id: str
    ) -> DocumentStatus:
        """
        Get document processing status.

        Args:
            kb_id: Knowledge base ID
            doc_id: Document ID

        Returns:
            Document status

        Raises:
            Exception: If document not found
        """
        pass

    @abstractmethod
    async def query(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        include_metadata: bool = True,
        session_id: Optional[str] = None
    ) -> List[QueryResult]:
        """
        Query a knowledge base.

        Args:
            kb_id: Knowledge base ID
            query: Natural language query
            top_k: Number of results to return
            filters: Optional metadata filters
            include_metadata: Include chunk metadata
            session_id: Session ID for access control

        Returns:
            List of query results sorted by relevance

        Raises:
            Exception: On query failure
        """
        pass

    @abstractmethod
    async def hybrid_query(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        keyword_weight: float = 0.3,
        vector_weight: float = 0.7,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[QueryResult]:
        """
        Perform hybrid search (keyword + vector).

        Args:
            kb_id: Knowledge base ID
            query: Search query
            top_k: Number of results
            keyword_weight: Weight for keyword search (0-1)
            vector_weight: Weight for vector search (0-1)
            filters: Optional filters

        Returns:
            List of query results

        Raises:
            Exception: On query failure
        """
        pass

    async def batch_ingest(
        self,
        kb_id: str,
        file_paths: List[str],
        metadata_list: Optional[List[Dict[str, Any]]] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None
    ) -> List[str]:
        """
        Batch ingest multiple documents.

        Default implementation calls ingest_document for each file.
        Backends can override for optimized batch processing.

        Args:
            kb_id: Knowledge base ID
            file_paths: List of file paths
            metadata_list: Optional metadata for each file
            chunk_size: Chunking size
            chunk_overlap: Chunk overlap

        Returns:
            List of document IDs
        """
        doc_ids = []
        metadata_list = metadata_list or [{}] * len(file_paths)

        for file_path, metadata in zip(file_paths, metadata_list):
            try:
                doc_id = await self.ingest_document(
                    kb_id=kb_id,
                    file_path=file_path,
                    metadata=metadata,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap
                )
                doc_ids.append(doc_id)
            except Exception as e:
                logger.error(f"Failed to ingest {file_path}: {e}")
                doc_ids.append(None)

        return doc_ids

    async def health_check(self) -> bool:
        """
        Check backend health.

        Returns:
            True if healthy, False otherwise
        """
        try:
            # Default implementation - try to list KBs
            await self.list_kbs()
            return True
        except Exception:
            return False

    def get_backend_info(self) -> Dict[str, Any]:
        """
        Get backend information and capabilities.

        Returns:
            Dictionary with backend info
        """
        return {
            "name": self.backend_name,
            "supports_hybrid_search": hasattr(self, 'hybrid_query'),
            "supports_batch_ingest": hasattr(self, 'batch_ingest'),
            "config": {k: v for k, v in self.config.items() if not k.endswith('_key')}
        }


class HybridKnowledgeBaseManager:
    """
    Manages multiple KB backends with routing logic.

    Supports hybrid approaches where different document types
    or use cases are routed to different backends.
    """

    def __init__(
        self,
        primary_backend: KnowledgeBaseBackend,
        fallback_backend: Optional[KnowledgeBaseBackend] = None,
        routing_strategy: str = "auto"
    ):
        """
        Initialize hybrid manager.

        Args:
            primary_backend: Primary KB backend
            fallback_backend: Optional fallback backend
            routing_strategy: Routing strategy (auto, manual, document_type)
        """
        self.primary = primary_backend
        self.fallback = fallback_backend
        self.routing_strategy = routing_strategy
        self.backend_metrics = {
            "primary_success": 0,
            "primary_failure": 0,
            "fallback_used": 0
        }

        logger.info(
            f"Hybrid KB manager initialized: "
            f"primary={primary_backend.backend_name}, "
            f"fallback={fallback_backend.backend_name if fallback_backend else 'None'}, "
            f"strategy={routing_strategy}"
        )

    async def select_backend(
        self,
        operation: str,
        document_path: Optional[str] = None,
        kb_id: Optional[str] = None
    ) -> KnowledgeBaseBackend:
        """
        Select appropriate backend based on routing strategy.

        Args:
            operation: Operation type (ingest, query, etc.)
            document_path: Optional document path for routing
            kb_id: Optional KB ID for routing

        Returns:
            Selected backend
        """
        if self.routing_strategy == "auto":
            # Auto-routing based on document type
            if document_path:
                ext = os.path.splitext(document_path)[1].lower()

                # Route complex documents to primary (assumed RAGFlow)
                if ext in ['.pdf', '.docx', '.pptx', '.xlsx']:
                    return self.primary

                # Route simple text to fallback (assumed ChromaDB)
                elif ext in ['.txt', '.md', '.json', '.csv'] and self.fallback:
                    return self.fallback

            # Check if KB exists in primary
            if kb_id:
                try:
                    await self.primary.get_kb_info(kb_id)
                    return self.primary
                except Exception:
                    if self.fallback:
                        try:
                            await self.fallback.get_kb_info(kb_id)
                            return self.fallback
                        except Exception:
                            pass

        return self.primary

    async def create_kb(
        self,
        name: str,
        backend_override: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Create KB with optional backend override.

        Args:
            name: KB name
            backend_override: Force specific backend (primary/fallback)
            **kwargs: Additional arguments

        Returns:
            KB ID with backend prefix
        """
        if backend_override == "fallback" and self.fallback:
            backend = self.fallback
        else:
            backend = self.primary

        try:
            kb_id = await backend.create_kb(name, **kwargs)
            self.backend_metrics["primary_success"] += 1
            # Prefix KB ID with backend type for routing
            return f"{backend.backend_name.lower()}_{kb_id}"
        except Exception as e:
            self.backend_metrics["primary_failure"] += 1
            if self.fallback and backend != self.fallback:
                logger.warning(f"Primary backend failed, using fallback: {e}")
                self.backend_metrics["fallback_used"] += 1
                kb_id = await self.fallback.create_kb(name, **kwargs)
                return f"{self.fallback.backend_name.lower()}_{kb_id}"
            raise

    async def query(
        self,
        kb_id: str,
        query: str,
        **kwargs
    ) -> List[QueryResult]:
        """
        Query with automatic backend selection.

        Args:
            kb_id: KB ID (may have backend prefix)
            query: Search query
            **kwargs: Additional arguments

        Returns:
            Query results
        """
        # Extract backend from KB ID prefix
        if '_' in kb_id:
            prefix, actual_kb_id = kb_id.split('_', 1)
            if prefix == self.fallback.backend_name.lower() and self.fallback:
                backend = self.fallback
            else:
                backend = self.primary
                actual_kb_id = kb_id  # Use full ID if no match
        else:
            backend = await self.select_backend("query", kb_id=kb_id)
            actual_kb_id = kb_id

        try:
            results = await backend.query(actual_kb_id, query, **kwargs)
            self.backend_metrics["primary_success"] += 1
            return results
        except Exception as e:
            self.backend_metrics["primary_failure"] += 1
            if self.fallback and backend != self.fallback:
                logger.warning(f"Query failed on primary, trying fallback: {e}")
                self.backend_metrics["fallback_used"] += 1
                return await self.fallback.query(actual_kb_id, query, **kwargs)
            raise

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get routing metrics.

        Returns:
            Dictionary of metrics
        """
        total_ops = sum(self.backend_metrics.values())
        success_rate = (
            self.backend_metrics["primary_success"] / total_ops * 100
            if total_ops > 0 else 0
        )

        return {
            **self.backend_metrics,
            "total_operations": total_ops,
            "primary_success_rate": success_rate,
            "fallback_percentage": (
                self.backend_metrics["fallback_used"] / total_ops * 100
                if total_ops > 0 else 0
            )
        }