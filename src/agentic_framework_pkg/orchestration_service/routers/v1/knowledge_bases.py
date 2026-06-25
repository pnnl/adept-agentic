"""
Knowledge Base Management Router for Tier 2 Orchestration Service

This router provides RESTful endpoints for managing knowledge bases using
the abstract KB backend interface, supporting both RAGFlow and ChromaDB.
"""

import os
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ....core.kb_backend import (
    KnowledgeBaseBackend,
    KnowledgeBaseInfo,
    QueryResult,
    DocumentStatus,
    HybridKnowledgeBaseManager
)
try:
    from ....core.knowledge_bases.ragflow import RAGFlowClient
except ImportError:
    RAGFlowClient = None
from ....logger_config import get_logger
from ....core.auth import get_current_user, AuthCredentials

logger = get_logger(__name__)

router = APIRouter(
    prefix="/knowledge_bases",
    tags=["knowledge_bases"],
    responses={404: {"description": "Knowledge base not found"}},
)


# ==================== Request/Response Models ====================

class CreateKBRequest(BaseModel):
    """Request model for creating a knowledge base"""
    name: str = Field(..., description="Knowledge base name")
    description: Optional[str] = Field(None, description="Knowledge base description")
    backend_type: Optional[str] = Field("auto", description="Backend type: ragflow, chromadb, or auto")
    chunk_size: Optional[int] = Field(1000, description="Document chunk size")
    chunk_overlap: Optional[int] = Field(200, description="Chunk overlap size")
    config: Optional[Dict[str, Any]] = Field(None, description="Additional backend-specific configuration")


class CreateKBResponse(BaseModel):
    """Response model for KB creation"""
    kb_id: str
    name: str
    backend_type: str
    created_at: str
    message: str = "Knowledge base created successfully"


class IngestDocumentRequest(BaseModel):
    """Request model for document ingestion"""
    kb_id: str = Field(..., description="Knowledge base ID")
    file_path: Optional[str] = Field(None, description="Path to file in shared storage")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Document metadata")
    chunk_size: Optional[int] = Field(None, description="Override default chunk size")
    chunk_overlap: Optional[int] = Field(None, description="Override default chunk overlap")


class IngestDocumentResponse(BaseModel):
    """Response model for document ingestion"""
    doc_id: str
    kb_id: str
    status: str
    message: str = "Document ingestion initiated"


class QueryKBRequest(BaseModel):
    """Request model for KB query"""
    query: str = Field(..., description="Natural language query")
    top_k: int = Field(5, description="Number of results to return")
    filters: Optional[Dict[str, Any]] = Field(None, description="Metadata filters")
    include_metadata: bool = Field(True, description="Include chunk metadata in results")
    hybrid_search: bool = Field(False, description="Use hybrid search (keyword + vector)")
    keyword_weight: float = Field(0.3, description="Weight for keyword search (0-1)")
    vector_weight: float = Field(0.7, description="Weight for vector search (0-1)")


class QueryKBResponse(BaseModel):
    """Response model for KB query"""
    kb_id: str
    query: str
    results: List[Dict[str, Any]]
    total_results: int
    search_type: str


class ListKBResponse(BaseModel):
    """Response model for listing knowledge bases"""
    knowledge_bases: List[Dict[str, Any]]
    total_count: int


class DocumentStatusResponse(BaseModel):
    """Response model for document status"""
    doc_id: str
    kb_id: str
    status: str
    created_at: Optional[str]
    updated_at: Optional[str]
    metadata: Optional[Dict[str, Any]]


# ==================== Backend Manager ====================

class KBBackendManager:
    """
    Manages KB backend instances and routing.

    This is a singleton that initializes the appropriate backend
    based on environment configuration and feature flags.
    """

    _instance = None
    _backend: KnowledgeBaseBackend = None
    _manager: Optional[HybridKnowledgeBaseManager] = None

    @classmethod
    async def get_backend(cls) -> KnowledgeBaseBackend:
        """Get or initialize the KB backend"""
        if cls._backend is None:
            await cls._initialize_backend()
        return cls._backend

    @classmethod
    async def _initialize_backend(cls):
        """Initialize the backend based on configuration"""
        enable_ragflow = os.getenv("ENABLE_RAGFLOW", "false").lower() == "true"
        kb_strategy = os.getenv("KB_BACKEND_STRATEGY", "hybrid")
        use_fallback = os.getenv("USE_CHROMADB_FALLBACK", "true").lower() == "true"

        logger.info(f"Initializing KB backend: ragflow={enable_ragflow}, strategy={kb_strategy}")

        if not enable_ragflow or kb_strategy == "chromadb_only":
            # Use ChromaDB backend
            from ....core.chromadb_backend import ChromaDBBackend
            cls._backend = ChromaDBBackend()
            logger.info("Using ChromaDB backend")

        elif kb_strategy == "ragflow_only":
            # Use RAGFlow backend only
            from ....core.knowledge_bases.ragflow import RAGFlowBackend
            cls._backend = RAGFlowBackend()
            logger.info("Using RAGFlow backend")

        else:  # hybrid
            # Use hybrid manager with both backends
            from ....core.knowledge_bases.ragflow import RAGFlowBackend
            from ....core.chromadb_backend import ChromaDBBackend

            primary = RAGFlowBackend()
            fallback = ChromaDBBackend() if use_fallback else None

            cls._manager = HybridKnowledgeBaseManager(
                primary_backend=primary,
                fallback_backend=fallback,
                routing_strategy="auto"
            )
            cls._backend = cls._manager
            logger.info("Using hybrid KB manager with RAGFlow primary and ChromaDB fallback")


# ==================== Dependency Injection ====================

async def get_kb_backend() -> KnowledgeBaseBackend:
    """Dependency to get KB backend instance"""
    return await KBBackendManager.get_backend()


# ==================== Router Endpoints ====================

@router.post("/create", response_model=CreateKBResponse)
async def create_knowledge_base(
    request: CreateKBRequest,
    current_user: AuthCredentials = Depends(get_current_user),
    backend: KnowledgeBaseBackend = Depends(get_kb_backend)
):
    """Create a new knowledge base"""
    try:
        # Add user context for access control
        kb_id = await backend.create_kb(
            name=request.name,
            description=request.description,
            config=request.config,
            owner_id=current_user.user_id,
            session_id=current_user.session_id
        )

        # Get KB info for response
        kb_info = await backend.get_kb_info(kb_id)

        return CreateKBResponse(
            kb_id=kb_id,
            name=kb_info.name,
            backend_type=kb_info.backend_type or "unknown",
            created_at=kb_info.created_at.isoformat() if kb_info.created_at else datetime.utcnow().isoformat()
        )

    except Exception as e:
        logger.error(f"Failed to create knowledge base: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create knowledge base: {str(e)}"
        )


@router.post("/ingest", response_model=IngestDocumentResponse)
async def ingest_document(
    request: IngestDocumentRequest,
    current_user: AuthCredentials = Depends(get_current_user),
    backend: KnowledgeBaseBackend = Depends(get_kb_backend)
):
    """Ingest a document into a knowledge base"""
    try:
        # Verify KB exists and user has access
        kb_info = await backend.get_kb_info(request.kb_id)
        if kb_info.owner_id and kb_info.owner_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this knowledge base"
            )

        # Ingest document
        doc_id = await backend.ingest_document(
            kb_id=request.kb_id,
            file_path=request.file_path,
            metadata=request.metadata,
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap
        )

        return IngestDocumentResponse(
            doc_id=doc_id,
            kb_id=request.kb_id,
            status="processing"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to ingest document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest document: {str(e)}"
        )


@router.post("/query/{kb_id}", response_model=QueryKBResponse)
async def query_knowledge_base(
    kb_id: str,
    request: QueryKBRequest,
    current_user: AuthCredentials = Depends(get_current_user),
    backend: KnowledgeBaseBackend = Depends(get_kb_backend)
):
    """Query a knowledge base"""
    try:
        # Verify KB exists and user has access
        kb_info = await backend.get_kb_info(kb_id)
        if kb_info.owner_id and kb_info.owner_id != current_user.user_id:
            # Check if session-based access
            if not kb_info.session_id or kb_info.session_id != current_user.session_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to this knowledge base"
                )

        # Perform query
        if request.hybrid_search and hasattr(backend, 'hybrid_query'):
            results = await backend.hybrid_query(
                kb_id=kb_id,
                query=request.query,
                top_k=request.top_k,
                keyword_weight=request.keyword_weight,
                vector_weight=request.vector_weight,
                filters=request.filters
            )
            search_type = "hybrid"
        else:
            results = await backend.query(
                kb_id=kb_id,
                query=request.query,
                top_k=request.top_k,
                filters=request.filters,
                include_metadata=request.include_metadata,
                session_id=current_user.session_id
            )
            search_type = "vector"

        # Convert results to dict format
        results_dict = [r.to_dict() for r in results]

        return QueryKBResponse(
            kb_id=kb_id,
            query=request.query,
            results=results_dict,
            total_results=len(results_dict),
            search_type=search_type
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to query knowledge base: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query knowledge base: {str(e)}"
        )


@router.get("/list", response_model=ListKBResponse)
async def list_knowledge_bases(
    owner_only: bool = Query(False, description="List only KBs owned by current user"),
    session_only: bool = Query(False, description="List only KBs for current session"),
    current_user: AuthCredentials = Depends(get_current_user),
    backend: KnowledgeBaseBackend = Depends(get_kb_backend)
):
    """List available knowledge bases"""
    try:
        owner_id = current_user.user_id if owner_only else None
        session_id = current_user.session_id if session_only else None

        kb_list = await backend.list_kbs(
            owner_id=owner_id,
            session_id=session_id
        )

        # Convert to dict format
        kb_dicts = [kb.to_dict() for kb in kb_list]

        return ListKBResponse(
            knowledge_bases=kb_dicts,
            total_count=len(kb_dicts)
        )

    except Exception as e:
        logger.error(f"Failed to list knowledge bases: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list knowledge bases: {str(e)}"
        )


@router.get("/{kb_id}", response_model=Dict[str, Any])
async def get_knowledge_base_info(
    kb_id: str,
    current_user: AuthCredentials = Depends(get_current_user),
    backend: KnowledgeBaseBackend = Depends(get_kb_backend)
):
    """Get information about a specific knowledge base"""
    try:
        kb_info = await backend.get_kb_info(kb_id)

        # Check access
        if kb_info.owner_id and kb_info.owner_id != current_user.user_id:
            if not kb_info.session_id or kb_info.session_id != current_user.session_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to this knowledge base"
                )

        return kb_info.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get KB info: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge base not found: {str(e)}"
        )


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: str,
    current_user: AuthCredentials = Depends(get_current_user),
    backend: KnowledgeBaseBackend = Depends(get_kb_backend)
):
    """Delete a knowledge base"""
    try:
        # Verify ownership
        kb_info = await backend.get_kb_info(kb_id)
        if kb_info.owner_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can delete this knowledge base"
            )

        success = await backend.delete_kb(kb_id)

        if success:
            return {"message": f"Knowledge base {kb_id} deleted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete knowledge base"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete knowledge base: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete knowledge base: {str(e)}"
        )


@router.get("/document/{kb_id}/{doc_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    kb_id: str,
    doc_id: str,
    current_user: AuthCredentials = Depends(get_current_user),
    backend: KnowledgeBaseBackend = Depends(get_kb_backend)
):
    """Get the processing status of a document"""
    try:
        # Verify KB access
        kb_info = await backend.get_kb_info(kb_id)
        if kb_info.owner_id and kb_info.owner_id != current_user.user_id:
            if not kb_info.session_id or kb_info.session_id != current_user.session_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to this knowledge base"
                )

        doc_status = await backend.get_document_status(kb_id, doc_id)

        return DocumentStatusResponse(
            doc_id=doc_id,
            kb_id=kb_id,
            status=doc_status.value,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document status: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document not found: {str(e)}"
        )


@router.delete("/document/{kb_id}/{doc_id}")
async def delete_document(
    kb_id: str,
    doc_id: str,
    current_user: AuthCredentials = Depends(get_current_user),
    backend: KnowledgeBaseBackend = Depends(get_kb_backend)
):
    """Delete a document from a knowledge base"""
    try:
        # Verify KB ownership
        kb_info = await backend.get_kb_info(kb_id)
        if kb_info.owner_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can delete documents from this knowledge base"
            )

        success = await backend.delete_document(kb_id, doc_id)

        if success:
            return {"message": f"Document {doc_id} deleted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete document"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(e)}"
        )


@router.post("/batch/ingest")
async def batch_ingest_documents(
    kb_id: str,
    files: List[UploadFile] = File(...),
    current_user: AuthCredentials = Depends(get_current_user),
    backend: KnowledgeBaseBackend = Depends(get_kb_backend)
):
    """Batch ingest multiple documents"""
    try:
        # Verify KB ownership
        kb_info = await backend.get_kb_info(kb_id)
        if kb_info.owner_id and kb_info.owner_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this knowledge base"
            )

        # Save uploaded files temporarily
        file_paths = []
        temp_dir = f"/tmp/kb_upload_{uuid.uuid4()}"
        os.makedirs(temp_dir, exist_ok=True)

        try:
            for file in files:
                file_path = os.path.join(temp_dir, file.filename)
                with open(file_path, "wb") as f:
                    content = await file.read()
                    f.write(content)
                file_paths.append(file_path)

            # Batch ingest
            doc_ids = await backend.batch_ingest(
                kb_id=kb_id,
                file_paths=file_paths
            )

            # Clean up temp files
            for path in file_paths:
                try:
                    os.remove(path)
                except:
                    pass
            os.rmdir(temp_dir)

            return {
                "message": f"Batch ingestion initiated for {len(doc_ids)} documents",
                "doc_ids": doc_ids,
                "kb_id": kb_id
            }

        except Exception as e:
            # Clean up on error
            for path in file_paths:
                try:
                    os.remove(path)
                except:
                    pass
            try:
                os.rmdir(temp_dir)
            except:
                pass
            raise e

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to batch ingest documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to batch ingest documents: {str(e)}"
        )


@router.get("/health")
async def health_check(
    backend: KnowledgeBaseBackend = Depends(get_kb_backend)
):
    """Check KB backend health"""
    try:
        is_healthy = await backend.health_check()
        backend_info = backend.get_backend_info()

        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "backend": backend_info,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }