"""
pgvector Backend Implementation

Implements the KnowledgeBaseBackend interface using PostgreSQL with the pgvector
extension for vector similarity search and native tsvector for full-text search.
Combines both via Reciprocal Rank Fusion (RRF) for hybrid queries.

Uses a dedicated postgres_rag container, separate from the orchestrator's postgres,
to isolate vector workloads (HNSW indexing, cosine similarity) from checkpoint/session
persistence.
"""

import asyncio
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..logger_config import get_logger
from .kb_backend import (
    DocumentStatus,
    KnowledgeBaseBackend,
    KnowledgeBaseInfo,
    QueryResult,
)

logger = get_logger(__name__)

# Database URL for the dedicated RAG PostgreSQL instance
PGVECTOR_DATABASE_URL = os.getenv(
    "PGVECTOR_DATABASE_URL",
    "postgresql+psycopg://admin:password@postgres_rag:5432/agentic_rag",
)

# BM25 engine selection: tsrank (native ts_rank_cd) or pg_search (ParadeDB)
BM25_ENGINE = os.getenv("BM25_ENGINE", "tsrank")

# Default chunking parameters
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200

# Embedding model name (384-dim output)
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# Module-level singleton engine (same pattern as checkpointing.py)
_pgvector_engine: Optional[AsyncEngine] = None
_pgvector_engine_loop_id: Optional[int] = None
_pgvector_engine_lock = threading.Lock()

# Lazy-loaded embedding model
_embedding_model = None
_embedding_model_lock = threading.Lock()


def _get_or_create_engine() -> AsyncEngine:
    """
    Get or create the async engine lazily, with event-loop detection.

    Replicates the singleton pattern from checkpointing.py to handle
    pytest event loop switching and avoid 'Future attached to a different loop'.
    """
    global _pgvector_engine, _pgvector_engine_loop_id

    try:
        current_loop = asyncio.get_running_loop()
        current_loop_id = id(current_loop)
    except RuntimeError:
        current_loop_id = None

    if _pgvector_engine is not None and _pgvector_engine_loop_id != current_loop_id:
        with _pgvector_engine_lock:
            if _pgvector_engine is not None and _pgvector_engine_loop_id != current_loop_id:
                logger.debug(
                    f"Event loop changed (old={_pgvector_engine_loop_id}, "
                    f"new={current_loop_id}), disposing pgvector engine"
                )
                _pgvector_engine = None
                _pgvector_engine_loop_id = None

    if _pgvector_engine is None:
        with _pgvector_engine_lock:
            if _pgvector_engine is None:
                logger.info(
                    f"Creating pgvector async engine: "
                    f"{PGVECTOR_DATABASE_URL.split('@')[1] if '@' in PGVECTOR_DATABASE_URL else 'configured'}"
                )
                engine = create_async_engine(
                    PGVECTOR_DATABASE_URL,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=10,
                    echo=False,
                )
                # Register pgvector codec on raw psycopg connections
                @event.listens_for(engine.sync_engine, "connect")
                def _register_vector(dbapi_connection, connection_record):
                    from pgvector.psycopg import register_vector

                    register_vector(dbapi_connection)

                _pgvector_engine = engine
                _pgvector_engine_loop_id = current_loop_id

    return _pgvector_engine


def _get_embedding_model():
    """Lazy-load the SentenceTransformer embedding model (thread-safe)."""
    global _embedding_model
    if _embedding_model is None:
        with _embedding_model_lock:
            if _embedding_model is None:
                from sentence_transformers import SentenceTransformer

                logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}")
                _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def _chunk_text(
    content: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[str]:
    """
    Word-boundary-aware text chunking.

    Replicates the chunking logic from ChromaDB backend for byte-level compatibility.
    """
    if not content or not content.strip():
        return []

    chunks = []
    start = 0

    while start < len(content):
        end = start + chunk_size
        chunk = content[start:end]

        # Try to break at word boundary
        if end < len(content) and not content[end].isspace():
            last_space = chunk.rfind(" ")
            if last_space > chunk_size * 0.8:
                end = start + last_space
                chunk = content[start:end]

        stripped = chunk.strip()
        if stripped:
            chunks.append(stripped)
        start = end - chunk_overlap

    return chunks


def _compute_rrf_score(
    vector_rank: Optional[int],
    text_rank: Optional[int],
    vector_weight: float = 0.7,
    keyword_weight: float = 0.3,
    k: int = 60,
) -> float:
    """
    Compute Reciprocal Rank Fusion score.

    Formula: vector_weight / (k + vector_rank) + keyword_weight / (k + text_rank)
    Missing ranks contribute 0 to their component.
    """
    score = 0.0
    if vector_rank is not None:
        score += vector_weight / (k + vector_rank)
    if text_rank is not None:
        score += keyword_weight / (k + text_rank)
    return score


class PgVectorBackend(KnowledgeBaseBackend):
    """
    pgvector implementation of the Knowledge Base Backend interface.

    Uses a dedicated PostgreSQL instance with the pgvector extension for:
    - HNSW approximate nearest neighbor vector search
    - Native tsvector + ts_rank_cd full-text search
    - Reciprocal Rank Fusion (RRF) hybrid queries
    - SQL WHERE-based visibility scoping (session/user/world)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._async_session_factory = None

    def _get_session_factory(self):
        """Get or create the async session factory."""
        if self._async_session_factory is None:
            engine = _get_or_create_engine()
            self._async_session_factory = sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
        return self._async_session_factory

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        model = _get_embedding_model()
        embeddings = model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    @staticmethod
    def _visibility_filter(
        owner_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Build SQL WHERE clause for visibility-based filtering.

        Returns the WHERE clause conditions (without the WHERE keyword).
        """
        conditions = []
        if session_id:
            conditions.append(f"(session_id = '{session_id}' AND visibility = 'session')")
        if owner_id:
            conditions.append(f"(owner_id = '{owner_id}' AND visibility = 'user')")
        conditions.append("visibility = 'world'")
        return " OR ".join(conditions)

    async def create_kb(
        self,
        name: str,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        owner_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        kb_id = str(uuid.uuid4())
        visibility = (config or {}).get("visibility", "session")

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO rag_knowledge_bases "
                    "(kb_id, name, description, owner_id, session_id, visibility) "
                    "VALUES (:kb_id, :name, :description, :owner_id, :session_id, :visibility)"
                ),
                {
                    "kb_id": kb_id,
                    "name": name,
                    "description": description,
                    "owner_id": owner_id,
                    "session_id": session_id,
                    "visibility": visibility,
                },
            )
            await session.commit()

        logger.info(f"Created KB {kb_id} (name={name}, visibility={visibility})")
        return kb_id

    async def delete_kb(self, kb_id: str) -> bool:
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text("DELETE FROM rag_knowledge_bases WHERE kb_id = :kb_id"),
                {"kb_id": kb_id},
            )
            await session.commit()

        deleted = result.rowcount > 0
        if deleted:
            logger.info(f"Deleted KB {kb_id} (CASCADE removes docs and chunks)")
        else:
            logger.warning(f"KB {kb_id} not found for deletion")
        return deleted

    async def get_kb_info(self, kb_id: str) -> KnowledgeBaseInfo:
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT kb_id, name, description, owner_id, session_id, "
                    "visibility, created_at, updated_at, "
                    "(SELECT COUNT(*) FROM rag_documents WHERE kb_id = k.kb_id) AS doc_count, "
                    "(SELECT COUNT(*) FROM rag_chunks WHERE kb_id = k.kb_id) AS chunk_count "
                    "FROM rag_knowledge_bases k WHERE kb_id = :kb_id"
                ),
                {"kb_id": kb_id},
            )
            row = result.mappings().first()

        if not row:
            raise ValueError(f"Knowledge base {kb_id} not found")

        return KnowledgeBaseInfo(
            kb_id=str(row["kb_id"]),
            name=row["name"],
            description=row["description"],
            owner_id=row["owner_id"],
            session_id=row["session_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            document_count=row["doc_count"],
            total_chunks=row["chunk_count"],
            backend_type="pgvector",
        )

    async def list_kbs(
        self,
        owner_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[KnowledgeBaseInfo]:
        vis_filter = self._visibility_filter(owner_id, session_id)

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT kb_id, name, description, owner_id, session_id, "
                    "visibility, created_at, updated_at, "
                    "(SELECT COUNT(*) FROM rag_documents WHERE kb_id = k.kb_id) AS doc_count, "
                    "(SELECT COUNT(*) FROM rag_chunks WHERE kb_id = k.kb_id) AS chunk_count "
                    f"FROM rag_knowledge_bases k WHERE {vis_filter} "
                    "ORDER BY created_at DESC"
                )
            )
            rows = result.mappings().all()

        return [
            KnowledgeBaseInfo(
                kb_id=str(row["kb_id"]),
                name=row["name"],
                description=row["description"],
                owner_id=row["owner_id"],
                session_id=row["session_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                document_count=row["doc_count"],
                total_chunks=row["chunk_count"],
                backend_type="pgvector",
            )
            for row in rows
        ]

    async def ingest_document(
        self,
        kb_id: str,
        file_path: str,
        file_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> str:
        doc_id = str(uuid.uuid4())
        chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
        chunk_overlap = chunk_overlap or DEFAULT_CHUNK_OVERLAP
        metadata = metadata or {}

        # Read and chunk the file
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            raise

        chunks = _chunk_text(content, chunk_size, chunk_overlap)
        if not chunks:
            logger.warning(f"No chunks generated from {file_path}")
            # Still create the document record with 0 chunks
            session_factory = self._get_session_factory()
            async with session_factory() as session:
                await session.execute(
                    text(
                        "INSERT INTO rag_documents "
                        "(doc_id, kb_id, file_path, file_id, status, metadata, chunk_count) "
                        "VALUES (:doc_id, :kb_id, :file_path, :file_id, 'completed', :metadata, 0)"
                    ),
                    {
                        "doc_id": doc_id,
                        "kb_id": kb_id,
                        "file_path": file_path,
                        "file_id": file_id,
                        "metadata": json.dumps(metadata),
                    },
                )
                await session.commit()
            return doc_id

        # Generate embeddings for all chunks
        embeddings = self._embed(chunks)

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            # Insert document record
            await session.execute(
                text(
                    "INSERT INTO rag_documents "
                    "(doc_id, kb_id, file_path, file_id, status, metadata, chunk_count) "
                    "VALUES (:doc_id, :kb_id, :file_path, :file_id, 'processing', :metadata, :chunk_count)"
                ),
                {
                    "doc_id": doc_id,
                    "kb_id": kb_id,
                    "file_path": file_path,
                    "file_id": file_id,
                    "metadata": json.dumps(metadata),
                    "chunk_count": len(chunks),
                },
            )

            # Insert chunks with embeddings
            for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
                chunk_id = str(uuid.uuid4())
                await session.execute(
                    text(
                        "INSERT INTO rag_chunks "
                        "(id, kb_id, doc_id, chunk_index, content, embedding, metadata) "
                        "VALUES (:id, :kb_id, :doc_id, :chunk_index, :content, :embedding, :metadata)"
                    ),
                    {
                        "id": chunk_id,
                        "kb_id": kb_id,
                        "doc_id": doc_id,
                        "chunk_index": i,
                        "content": chunk_text,
                        "embedding": str(embedding),
                        "metadata": json.dumps(metadata),
                    },
                )

            # Mark document as completed
            await session.execute(
                text(
                    "UPDATE rag_documents SET status = 'completed' "
                    "WHERE doc_id = :doc_id"
                ),
                {"doc_id": doc_id},
            )
            await session.commit()

        logger.info(
            f"Ingested document {doc_id} ({len(chunks)} chunks) into KB {kb_id}"
        )
        return doc_id

    async def delete_document(self, kb_id: str, doc_id: str) -> bool:
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "DELETE FROM rag_documents WHERE doc_id = :doc_id AND kb_id = :kb_id"
                ),
                {"doc_id": doc_id, "kb_id": kb_id},
            )
            await session.commit()

        deleted = result.rowcount > 0
        if deleted:
            logger.info(f"Deleted document {doc_id} from KB {kb_id}")
        return deleted

    async def get_document_status(self, kb_id: str, doc_id: str) -> DocumentStatus:
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT status FROM rag_documents "
                    "WHERE doc_id = :doc_id AND kb_id = :kb_id"
                ),
                {"doc_id": doc_id, "kb_id": kb_id},
            )
            row = result.mappings().first()

        if not row:
            raise ValueError(f"Document {doc_id} not found in KB {kb_id}")

        return DocumentStatus(row["status"])

    async def query(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        include_metadata: bool = True,
        session_id: Optional[str] = None,
    ) -> List[QueryResult]:
        # Generate query embedding
        query_embedding = self._embed([query])[0]

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT id, content, metadata, chunk_index, "
                    "d.file_path AS source_document, c.page_number, "
                    "1 - (c.embedding <=> :query_vec) AS score "
                    "FROM rag_chunks c "
                    "JOIN rag_documents d ON c.doc_id = d.doc_id "
                    "WHERE c.kb_id = :kb_id "
                    "ORDER BY c.embedding <=> :query_vec "
                    "LIMIT :top_k"
                ),
                {
                    "kb_id": kb_id,
                    "query_vec": str(query_embedding),
                    "top_k": top_k,
                },
            )
            rows = result.mappings().all()

        return [
            QueryResult(
                chunk_id=str(row["id"]),
                content=row["content"],
                score=float(row["score"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                source_document=row["source_document"],
                page_number=row["page_number"],
                chunk_index=row["chunk_index"],
            )
            for row in rows
        ]

    async def hybrid_query(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        keyword_weight: float = 0.3,
        vector_weight: float = 0.7,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[QueryResult]:
        query_embedding = self._embed([query])[0]
        expanded_k = top_k * 3  # Fetch more candidates for RRF

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "WITH vector_results AS ("
                    "  SELECT id, content, metadata, chunk_index, doc_id, page_number, "
                    "    ROW_NUMBER() OVER (ORDER BY embedding <=> :query_vec) AS rank "
                    "  FROM rag_chunks "
                    "  WHERE kb_id = :kb_id "
                    "  ORDER BY embedding <=> :query_vec "
                    "  LIMIT :expanded_k"
                    "), "
                    "text_results AS ("
                    "  SELECT id, content, metadata, chunk_index, doc_id, page_number, "
                    "    ROW_NUMBER() OVER (ORDER BY ts_rank_cd(content_tsv, plainto_tsquery('english', :query_text)) DESC) AS rank "
                    "  FROM rag_chunks "
                    "  WHERE kb_id = :kb_id AND content_tsv @@ plainto_tsquery('english', :query_text) "
                    "  ORDER BY ts_rank_cd(content_tsv, plainto_tsquery('english', :query_text)) DESC "
                    "  LIMIT :expanded_k"
                    ") "
                    "SELECT "
                    "  COALESCE(v.id, t.id) AS id, "
                    "  COALESCE(v.content, t.content) AS content, "
                    "  COALESCE(v.metadata, t.metadata) AS metadata, "
                    "  COALESCE(v.chunk_index, t.chunk_index) AS chunk_index, "
                    "  COALESCE(v.doc_id, t.doc_id) AS doc_id, "
                    "  COALESCE(v.page_number, t.page_number) AS page_number, "
                    "  (COALESCE(:vector_weight / (60.0 + v.rank), 0) + "
                    "   COALESCE(:keyword_weight / (60.0 + t.rank), 0)) AS rrf_score "
                    "FROM vector_results v "
                    "FULL OUTER JOIN text_results t ON v.id = t.id "
                    "ORDER BY rrf_score DESC "
                    "LIMIT :top_k"
                ),
                {
                    "kb_id": kb_id,
                    "query_vec": str(query_embedding),
                    "query_text": query,
                    "expanded_k": expanded_k,
                    "vector_weight": vector_weight,
                    "keyword_weight": keyword_weight,
                    "top_k": top_k,
                },
            )
            rows = result.mappings().all()

        # Fetch source document paths for the results
        doc_ids = list({str(row["doc_id"]) for row in rows if row["doc_id"]})
        doc_paths = {}
        if doc_ids:
            async with session_factory() as session:
                doc_result = await session.execute(
                    text(
                        "SELECT doc_id, file_path FROM rag_documents "
                        "WHERE doc_id = ANY(:doc_ids)"
                    ),
                    {"doc_ids": doc_ids},
                )
                for doc_row in doc_result.mappings().all():
                    doc_paths[str(doc_row["doc_id"])] = doc_row["file_path"]

        return [
            QueryResult(
                chunk_id=str(row["id"]),
                content=row["content"],
                score=float(row["rrf_score"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                source_document=doc_paths.get(str(row["doc_id"])),
                page_number=row["page_number"],
                chunk_index=row["chunk_index"],
            )
            for row in rows
        ]

    async def health_check(self) -> bool:
        try:
            session_factory = self._get_session_factory()
            async with session_factory() as session:
                result = await session.execute(text("SELECT 1"))
                result.scalar()
            return True
        except Exception as e:
            logger.error(f"pgvector health check failed: {e}")
            return False

    def get_backend_info(self) -> Dict[str, Any]:
        return {
            "name": self.backend_name,
            "type": "pgvector",
            "supports_hybrid_search": True,
            "supports_batch_ingest": True,
            "bm25_engine": BM25_ENGINE,
            "embedding_model": EMBEDDING_MODEL_NAME,
            "embedding_dim": EMBEDDING_DIM,
            "database_url": PGVECTOR_DATABASE_URL.split("@")[1]
            if "@" in PGVECTOR_DATABASE_URL
            else "configured",
        }
