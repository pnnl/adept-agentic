"""
ChromaDB Backend Implementation

Implements the KnowledgeBaseBackend interface using ChromaDB for backward compatibility.
This allows existing ChromaDB-based RAG functionality to work through the unified KB interface.
"""

import os
import uuid
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from .kb_backend import (
    KnowledgeBaseBackend,
    KnowledgeBaseInfo,
    QueryResult,
    DocumentStatus
)
from ..logger_config import get_logger

logger = get_logger(__name__)


class ChromaDBBackend(KnowledgeBaseBackend):
    """
    ChromaDB implementation of the Knowledge Base Backend interface.

    This backend provides backward compatibility with existing ChromaDB-based
    RAG functionality, allowing a smooth transition to the new KB abstraction.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize ChromaDB backend.

        Prefers HttpClient when VECTOR_DB_URL is set (production — connects to
        the vector_db_server container). Falls back to PersistentClient for
        tests/dev when no URL is configured.

        Args:
            config: Optional configuration overrides
        """
        super().__init__(config)

        vector_db_url = (config or {}).get("vector_db_url") or os.getenv("VECTOR_DB_URL")

        if vector_db_url:
            # Production: connect to vector_db_server via HTTP
            host, port = self._parse_url(vector_db_url)
            self.client = chromadb.HttpClient(host=host, port=port)
            logger.info(f"ChromaDBBackend using HttpClient: {host}:{port}")
        else:
            # Fallback: local persistence for tests/dev
            persist_dir = (config or {}).get("persist_directory") \
                or os.getenv("CHROMADB_PERSIST_DIR", "/app/data/vector_db_persistence")
            self.client = chromadb.PersistentClient(
                path=persist_dir,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            logger.info(f"ChromaDBBackend using PersistentClient: {persist_dir}")

        # Initialize embedding function
        self.embedding_function = self._get_embedding_function(config)

        # Track KB metadata (ChromaDB collections don't store all our metadata)
        self._kb_metadata: Dict[str, KnowledgeBaseInfo] = {}
        self._kb_to_collection: Dict[str, str] = {}  # KB ID to collection name mapping

    @staticmethod
    def _parse_url(url: str) -> tuple:
        """Parse a URL into (host, port). Reuses the pattern from VectorStoreManager."""
        if "://" in url:
            url_no_scheme = url.split("://")[1]
        else:
            url_no_scheme = url

        if ":" in url_no_scheme:
            host, port_str = url_no_scheme.split(":")
            port = int(port_str)
        else:
            host = url_no_scheme
            port = 8001
            logger.warning(f"Port not specified in URL '{url}', defaulting to {port}")

        return host, port

    def _get_embedding_function(self, config: Optional[Dict[str, Any]] = None):
        """Get the appropriate embedding function based on configuration"""
        embedding_model = config.get("embedding_model") if config else None
        if not embedding_model:
            embedding_model = os.getenv("EMBEDDING_MODEL", "sentence-transformers")

        if embedding_model == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                return embedding_functions.OpenAIEmbeddingFunction(
                    api_key=api_key,
                    model_name="text-embedding-ada-002"
                )

        # Default to sentence-transformers
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )

    def _generate_collection_name(
        self,
        kb_id: str,
        name: str,
        visibility: Optional[str] = None,
        session_id: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> str:
        """Generate a valid ChromaDB collection name with visibility-aware prefixing.

        Naming convention:
        - session (default): ``s_{session_id[:12]}_{name}``
        - user:              ``u_{owner_id[:12]}_{name}``
        - world:             ``w_{name}``
        - fallback:          ``kb_{kb_id[:8]}_{name}``
        """
        # ChromaDB collection names must be 3-63 characters, start/end with alphanumeric
        if visibility == "session" and session_id:
            base_name = f"s_{session_id[:12]}_{name}"
        elif visibility == "user" and owner_id:
            base_name = f"u_{owner_id[:12]}_{name}"
        elif visibility == "world":
            base_name = f"w_{name}"
        else:
            base_name = f"kb_{kb_id[:8]}_{name}"

        # Remove invalid characters
        clean_name = "".join(c if c.isalnum() or c == "_" else "_" for c in base_name)
        # Ensure proper length
        if len(clean_name) > 63:
            clean_name = clean_name[:63]
        elif len(clean_name) < 3:
            clean_name = f"kb_{kb_id[:8]}"
        return clean_name.lower()

    async def create_kb(
        self,
        name: str,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        owner_id: Optional[str] = None,
        session_id: Optional[str] = None,
        visibility: Optional[str] = None,
    ) -> str:
        """
        Create a new knowledge base (ChromaDB collection).

        Args:
            name: Knowledge base name
            description: Optional description
            config: Additional configuration
            owner_id: Owner user ID
            session_id: Session ID
            visibility: Access scope — "session", "user", or "world" (default: "session")

        Returns:
            Knowledge base ID

        Raises:
            Exception: On creation failure
        """
        try:
            visibility = visibility or "session"

            # Generate unique KB ID
            kb_id = str(uuid.uuid4())
            collection_name = self._generate_collection_name(
                kb_id, name,
                visibility=visibility,
                session_id=session_id,
                owner_id=owner_id,
            )

            # Create ChromaDB collection
            collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_function,
                metadata={
                    "kb_id": kb_id,
                    "name": name,
                    "description": description or "",
                    "owner_id": owner_id or "",
                    "session_id": session_id or "",
                    "visibility": visibility,
                    "created_at": datetime.utcnow().isoformat()
                }
            )

            # Store metadata
            self._kb_metadata[kb_id] = KnowledgeBaseInfo(
                kb_id=kb_id,
                name=name,
                description=description,
                owner_id=owner_id,
                session_id=session_id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                backend_type="chromadb"
            )
            self._kb_to_collection[kb_id] = collection_name

            logger.info(f"Created ChromaDB KB: {kb_id} (collection: {collection_name})")
            return kb_id

        except Exception as e:
            logger.error(f"Failed to create ChromaDB KB: {e}")
            raise

    async def delete_kb(self, kb_id: str) -> bool:
        """
        Delete a knowledge base (ChromaDB collection).

        Args:
            kb_id: Knowledge base ID

        Returns:
            True if successful

        Raises:
            Exception: On deletion failure
        """
        try:
            if kb_id not in self._kb_to_collection:
                raise ValueError(f"Knowledge base {kb_id} not found")

            collection_name = self._kb_to_collection[kb_id]
            self.client.delete_collection(name=collection_name)

            # Remove metadata
            del self._kb_metadata[kb_id]
            del self._kb_to_collection[kb_id]

            logger.info(f"Deleted ChromaDB KB: {kb_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete KB {kb_id}: {e}")
            raise

    async def get_kb_info(self, kb_id: str) -> KnowledgeBaseInfo:
        """
        Get knowledge base information.

        Args:
            kb_id: Knowledge base ID

        Returns:
            Knowledge base metadata

        Raises:
            Exception: If KB not found
        """
        try:
            # Check local metadata
            if kb_id in self._kb_metadata:
                return self._kb_metadata[kb_id]

            # Try to find collection by scanning
            for collection in self.client.list_collections():
                metadata = collection.metadata
                if metadata and metadata.get("kb_id") == kb_id:
                    kb_info = KnowledgeBaseInfo(
                        kb_id=kb_id,
                        name=metadata.get("name", "Unknown"),
                        description=metadata.get("description"),
                        owner_id=metadata.get("owner_id"),
                        session_id=metadata.get("session_id"),
                        document_count=collection.count(),
                        backend_type="chromadb"
                    )
                    self._kb_metadata[kb_id] = kb_info
                    self._kb_to_collection[kb_id] = collection.name
                    return kb_info

            raise ValueError(f"Knowledge base {kb_id} not found")

        except Exception as e:
            logger.error(f"Failed to get KB info for {kb_id}: {e}")
            raise

    async def list_kbs(
        self,
        owner_id: Optional[str] = None,
        session_id: Optional[str] = None,
        include_world: bool = True,
        include_user: bool = True,
    ) -> List[KnowledgeBaseInfo]:
        """
        List knowledge bases (ChromaDB collections) with visibility-aware filtering.

        Visibility scoping logic:
        - **world** collections (``w_`` prefix): Always included when ``include_world=True``,
          regardless of ``owner_id`` / ``session_id`` filters.
        - **user** collections (``u_`` prefix): Included when ``include_user=True`` and
          the collection's ``owner_id`` matches the caller's ``owner_id``.
        - **session** collections (``s_`` prefix): Included when the collection's
          ``session_id`` matches the caller's ``session_id``.

        Args:
            owner_id: Filter user-scoped collections by owner
            session_id: Filter session-scoped collections by session
            include_world: Include world-scoped collections (default True)
            include_user: Include user-scoped collections for the given owner (default True)

        Returns:
            List of knowledge base info
        """
        try:
            kb_list = []

            for collection in self.client.list_collections():
                metadata = collection.metadata
                if not metadata or not metadata.get("kb_id"):
                    continue

                vis = metadata.get("visibility", "session")

                # World-scoped: always include when requested
                if vis == "world":
                    if not include_world:
                        continue
                # User-scoped: include when requested and owner matches
                elif vis == "user":
                    if not include_user:
                        continue
                    if owner_id and metadata.get("owner_id") != owner_id:
                        continue
                # Session-scoped (default): include when session matches
                else:
                    if session_id and metadata.get("session_id") != session_id:
                        continue
                    elif not session_id:
                        # No session filter provided and this is session-scoped;
                        # also apply owner filter if given
                        if owner_id and metadata.get("owner_id") != owner_id:
                            continue

                kb_id = metadata["kb_id"]
                kb_info = KnowledgeBaseInfo(
                    kb_id=kb_id,
                    name=metadata.get("name", "Unknown"),
                    description=metadata.get("description"),
                    owner_id=metadata.get("owner_id"),
                    session_id=metadata.get("session_id"),
                    document_count=collection.count(),
                    backend_type="chromadb"
                )

                # Cache metadata
                self._kb_metadata[kb_id] = kb_info
                self._kb_to_collection[kb_id] = collection.name

                kb_list.append(kb_info)

            return kb_list

        except Exception as e:
            logger.error(f"Failed to list KBs: {e}")
            return []

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
        Ingest a document into a ChromaDB collection.

        Args:
            kb_id: Knowledge base ID
            file_path: Path to document file
            file_id: Optional file identifier
            metadata: Document metadata
            chunk_size: Chunking size (default: 1000)
            chunk_overlap: Chunk overlap (default: 200)

        Returns:
            Document ID

        Raises:
            Exception: On ingestion failure
        """
        try:
            if kb_id not in self._kb_to_collection:
                raise ValueError(f"Knowledge base {kb_id} not found")

            collection_name = self._kb_to_collection[kb_id]
            collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )

            # Generate document ID
            doc_id = file_id or str(uuid.uuid4())

            # Read and chunk the document
            chunk_size = chunk_size or 1000
            chunk_overlap = chunk_overlap or 200

            chunks = await self._chunk_document(file_path, chunk_size, chunk_overlap)

            # Prepare data for ChromaDB
            ids = []
            documents = []
            metadatas = []

            for i, chunk in enumerate(chunks):
                chunk_id = f"{doc_id}_chunk_{i}"
                ids.append(chunk_id)
                documents.append(chunk)

                chunk_metadata = {
                    "doc_id": doc_id,
                    "chunk_index": i,
                    "file_path": file_path,
                    "file_name": os.path.basename(file_path)
                }
                if metadata:
                    chunk_metadata.update(metadata)
                metadatas.append(chunk_metadata)

            # Add to collection
            if ids:
                collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas
                )

            # Update KB metadata
            if kb_id in self._kb_metadata:
                self._kb_metadata[kb_id].document_count += 1
                self._kb_metadata[kb_id].total_chunks += len(ids)
                self._kb_metadata[kb_id].updated_at = datetime.utcnow()

            logger.info(f"Ingested document {doc_id} ({len(chunks)} chunks) into KB {kb_id}")
            return doc_id

        except Exception as e:
            logger.error(f"Failed to ingest document into KB {kb_id}: {e}")
            raise

    async def _chunk_document(
        self,
        file_path: str,
        chunk_size: int,
        chunk_overlap: int
    ) -> List[str]:
        """
        Simple document chunking implementation.

        For production use, this should be replaced with more sophisticated
        chunking that preserves semantic boundaries.
        """
        try:
            # Read file content
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Simple character-based chunking
            chunks = []
            start = 0

            while start < len(content):
                end = start + chunk_size
                chunk = content[start:end]

                # Try to break at word boundary
                if end < len(content) and not content[end].isspace():
                    last_space = chunk.rfind(' ')
                    if last_space > chunk_size * 0.8:  # Don't go back too far
                        end = start + last_space
                        chunk = content[start:end]

                chunks.append(chunk.strip())
                start = end - chunk_overlap

            return [c for c in chunks if c]  # Filter out empty chunks

        except Exception as e:
            logger.error(f"Failed to chunk document {file_path}: {e}")
            return []

    async def delete_document(
        self,
        kb_id: str,
        doc_id: str
    ) -> bool:
        """
        Delete a document from a ChromaDB collection.

        Args:
            kb_id: Knowledge base ID
            doc_id: Document ID

        Returns:
            True if successful

        Raises:
            Exception: On deletion failure
        """
        try:
            if kb_id not in self._kb_to_collection:
                raise ValueError(f"Knowledge base {kb_id} not found")

            collection_name = self._kb_to_collection[kb_id]
            collection = self.client.get_collection(name=collection_name)

            # Delete all chunks for this document
            collection.delete(
                where={"doc_id": doc_id}
            )

            # Update KB metadata
            if kb_id in self._kb_metadata:
                self._kb_metadata[kb_id].document_count = max(0, self._kb_metadata[kb_id].document_count - 1)
                self._kb_metadata[kb_id].updated_at = datetime.utcnow()

            logger.info(f"Deleted document {doc_id} from KB {kb_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete document {doc_id} from KB {kb_id}: {e}")
            raise

    async def get_document_status(
        self,
        kb_id: str,
        doc_id: str
    ) -> DocumentStatus:
        """
        Get document processing status.

        ChromaDB doesn't track processing status, so we check if the document exists.

        Args:
            kb_id: Knowledge base ID
            doc_id: Document ID

        Returns:
            Document status

        Raises:
            Exception: If document not found
        """
        try:
            if kb_id not in self._kb_to_collection:
                raise ValueError(f"Knowledge base {kb_id} not found")

            collection_name = self._kb_to_collection[kb_id]
            collection = self.client.get_collection(name=collection_name)

            # Check if document exists
            results = collection.get(
                where={"doc_id": doc_id},
                limit=1
            )

            if results and results["ids"]:
                return DocumentStatus.COMPLETED
            else:
                return DocumentStatus.FAILED

        except Exception as e:
            logger.error(f"Failed to get status for document {doc_id} in KB {kb_id}: {e}")
            raise

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
        Query a ChromaDB collection.

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
        try:
            if kb_id not in self._kb_to_collection:
                raise ValueError(f"Knowledge base {kb_id} not found")

            collection_name = self._kb_to_collection[kb_id]
            collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )

            # Perform similarity search
            results = collection.query(
                query_texts=[query],
                n_results=top_k,
                where=filters,
                include=["documents", "metadatas", "distances"] if include_metadata else ["documents", "distances"]
            )

            # Convert to QueryResult format
            query_results = []
            if results["ids"] and results["ids"][0]:
                for i in range(len(results["ids"][0])):
                    # ChromaDB returns distances, convert to similarity score (1 - distance)
                    score = 1.0 - results["distances"][0][i] if results["distances"] else 0.0

                    query_result = QueryResult(
                        chunk_id=results["ids"][0][i],
                        content=results["documents"][0][i] if results["documents"] else "",
                        score=score,
                        metadata=results["metadatas"][0][i] if include_metadata and results["metadatas"] else {},
                        source_document=results["metadatas"][0][i].get("file_name") if results["metadatas"] else None,
                        chunk_index=results["metadatas"][0][i].get("chunk_index") if results["metadatas"] else None
                    )
                    query_results.append(query_result)

            logger.info(f"Query returned {len(query_results)} results from KB {kb_id}")
            return query_results

        except Exception as e:
            logger.error(f"Failed to query KB {kb_id}: {e}")
            raise

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

        ChromaDB doesn't natively support hybrid search, so we simulate it
        by combining vector search with simple keyword matching.

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
        try:
            # For ChromaDB, we'll just use vector search with adjusted scoring
            # In a production implementation, you'd want to implement proper BM25 keyword search

            # Get vector search results
            vector_results = await self.query(
                kb_id=kb_id,
                query=query,
                top_k=top_k * 2,  # Get more results for re-ranking
                filters=filters,
                include_metadata=True
            )

            # Simple keyword matching for re-ranking
            query_terms = query.lower().split()

            for result in vector_results:
                content_lower = result.content.lower()
                keyword_score = sum(1 for term in query_terms if term in content_lower) / len(query_terms)

                # Combine scores
                result.score = (vector_weight * result.score) + (keyword_weight * keyword_score)

            # Sort by combined score and return top_k
            vector_results.sort(key=lambda x: x.score, reverse=True)
            return vector_results[:top_k]

        except Exception as e:
            logger.error(f"Failed to perform hybrid query on KB {kb_id}: {e}")
            raise

    async def health_check(self) -> bool:
        """
        Check ChromaDB backend health.

        Returns:
            True if healthy, False otherwise
        """
        try:
            # Try to list collections as a health check
            collections = self.client.list_collections()
            logger.debug(f"ChromaDB backend is healthy, {len(collections)} collections found")
            return True

        except Exception as e:
            logger.error(f"ChromaDB health check failed: {e}")
            return False

    def get_backend_info(self) -> Dict[str, Any]:
        """
        Get backend information and capabilities.

        Returns:
            Dictionary with backend info
        """
        info = super().get_backend_info()
        info.update({
            "name": "ChromaDBBackend",
            "type": "chromadb",
            "supports_hybrid_search": False,  # Simulated only
            "supports_batch_ingest": True,
            "supports_ocr": False,
            "supports_table_extraction": False,
            "supports_multimodal": False,
            "persist_directory": self.client._settings.persist_directory if hasattr(self.client, '_settings') else None,
            "collection_count": len(self.client.list_collections())
        })
        return info