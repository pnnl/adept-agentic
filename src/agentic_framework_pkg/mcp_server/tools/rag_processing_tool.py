"""
RAG Processing Tools for MCP Server

This module provides tools for creating and querying RAG indexes
from uploaded files, enabling semantic search and question answering.
"""
import os
import json
import hashlib
import time
from typing import Dict, Any, Optional, List, Literal
from datetime import datetime
import tempfile
import shutil

from ..server import mcp
from ...logger_config import get_logger
from ..state_manager import get_session_context, update_session_context
from ...core.kb_backend_factory import BackendFactory

logger = get_logger(__name__)

# Check if RAG dependencies are available
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_community.vectorstores import Chroma
    from langchain_core.documents import Document
    LANGCHAIN_AVAILABLE = True
except ImportError as e:
    LANGCHAIN_AVAILABLE = False
    logger.warning(f"LangChain dependencies not available for RAG processing: {e}")

# Base directory for RAG indexes
RAG_INDEX_DIR = os.environ.get("RAG_INDEX_DIR", "/app/data/rag_indexes")

# Initialize backend factory
backend_factory = BackendFactory()

def ensure_rag_directory():
    """Ensure RAG directory exists with fallback to /tmp if needed."""
    global RAG_INDEX_DIR

    # Check if directory already exists and is writable
    if os.path.exists(RAG_INDEX_DIR):
        if os.access(RAG_INDEX_DIR, os.W_OK):
            logger.info(f"RAG directory exists and is writable: {RAG_INDEX_DIR}")
            return True
        else:
            logger.warning(f"RAG directory exists but is not writable: {RAG_INDEX_DIR}")

    # Try to create the directory
    try:
        os.makedirs(RAG_INDEX_DIR, exist_ok=True)
        logger.info(f"Created RAG directory: {RAG_INDEX_DIR}")
        return True
    except PermissionError as e:
        logger.warning(f"Cannot create RAG directory {RAG_INDEX_DIR}: {e}")
        logger.warning("Falling back to /tmp/rag_indexes")

        # Fallback to /tmp which should always be writable
        RAG_INDEX_DIR = "/tmp/rag_indexes"
        try:
            os.makedirs(RAG_INDEX_DIR, exist_ok=True)
            logger.info(f"Using fallback RAG directory: {RAG_INDEX_DIR}")
            return True
        except Exception as e2:
            logger.error(f"Cannot create fallback directory: {e2}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error creating RAG directory: {e}")
        return False

class RAGProcessor:
    """Handles RAG index creation and querying."""
    
    def __init__(self):
        # Ensure directory exists before initializing
        if not ensure_rag_directory():
            logger.error("RAG directory unavailable - some features may not work")

        if LANGCHAIN_AVAILABLE:
            # Initialize embeddings model (using a lightweight model)
            self.embeddings = HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                model_kwargs={'device': 'cpu'},
                encode_kwargs={'normalize_embeddings': True}
            )
        else:
            self.embeddings = None
    
    async def create_index_from_text(
        self,
        text: str,
        index_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200
    ) -> Dict[str, Any]:
        """Create a RAG index from text content."""
        try:
            if not LANGCHAIN_AVAILABLE:
                return {"error": "RAG dependencies not available"}
            
            # Split text into chunks
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
                separators=["\n\n", "\n", ". ", " ", ""]
            )
            
            chunks = text_splitter.split_text(text)
            logger.info(
                f"[RAG_INDEX] Text split into {len(chunks)} chunks "
                f"(chunk_size={chunk_size}, overlap={chunk_overlap})"
            )

            # Create documents with metadata
            documents = []
            for i, chunk in enumerate(chunks):
                doc_metadata = {
                    "chunk_id": i,
                    "index_id": index_id,
                    **(metadata or {})
                }
                documents.append(Document(
                    page_content=chunk,
                    metadata=doc_metadata
                ))
            
            # Create vector store
            index_path = os.path.join(RAG_INDEX_DIR, index_id)
            _embed_start = time.time()
            logger.info(
                f"[RAG_INDEX] Starting embedding for {len(documents)} documents "
                f"(text_length={len(text)} chars)..."
            )
            vectorstore = Chroma.from_documents(
                documents=documents,
                embedding=self.embeddings,
                persist_directory=index_path
            )
            _embed_duration = time.time() - _embed_start
            logger.info(
                f"[RAG_INDEX] Embedding complete in {_embed_duration:.1f}s. "
                f"Persisting to {index_path}..."
            )

            # Persist the index
            vectorstore.persist()
            
            return {
                "success": True,
                "index_id": index_id,
                "chunks_created": len(documents),
                "index_path": index_path,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap
            }
            
        except Exception as e:
            logger.error(f"Error creating RAG index: {e}", exc_info=True)
            return {"error": str(e)}
    
    async def query_index(
        self,
        index_id: str,
        query: str,
        top_k: int = 3,
        score_threshold: Optional[float] = None
    ) -> Dict[str, Any]:
        """Query a RAG index for relevant chunks."""
        try:
            if not LANGCHAIN_AVAILABLE:
                return {"error": "RAG dependencies not available"}
            
            index_path = os.path.join(RAG_INDEX_DIR, index_id)
            if not os.path.exists(index_path):
                return {"error": f"Index {index_id} not found"}
            
            # Load vector store
            vectorstore = Chroma(
                persist_directory=index_path,
                embedding_function=self.embeddings
            )
            
            # Perform similarity search
            if score_threshold:
                results = vectorstore.similarity_search_with_relevance_scores(
                    query, k=top_k
                )
                # Filter by score threshold
                results = [(doc, score) for doc, score in results if score >= score_threshold]
            else:
                docs = vectorstore.similarity_search(query, k=top_k)
                results = [(doc, None) for doc in docs]
            
            # Format results
            formatted_results = []
            for doc, score in results:
                result = {
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "chunk_id": doc.metadata.get("chunk_id", -1)
                }
                if score is not None:
                    result["relevance_score"] = score
                formatted_results.append(result)
            
            return {
                "success": True,
                "query": query,
                "results": formatted_results,
                "num_results": len(formatted_results),
                "index_id": index_id
            }
            
        except Exception as e:
            logger.error(f"Error querying RAG index: {e}", exc_info=True)
            return {"error": str(e)}
    
    async def delete_index(self, index_id: str) -> Dict[str, Any]:
        """Delete a RAG index."""
        try:
            index_path = os.path.join(RAG_INDEX_DIR, index_id)
            if os.path.exists(index_path):
                shutil.rmtree(index_path)
                return {"success": True, "deleted": index_id}
            else:
                return {"error": f"Index {index_id} not found"}
        except Exception as e:
            logger.error(f"Error deleting RAG index: {e}", exc_info=True)
            return {"error": str(e)}

# Global RAG processor instance
rag_processor = RAGProcessor()

async def create_rag_index(
    file_ids: List[str],  # Changed from file_id: str to file_ids: List[str]
    index_name: Optional[str] = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    visibility: str = "session",
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Create a RAG index from already-registered files for semantic search.

    CRITICAL: This tool requires file_ids (list of registered file IDs), NOT folder_path.
    For filesystem folders, use CreateRAGIndexFromFolder instead.

    This tool is used when files are already registered (uploaded or registered via RegisterLocalFile)
    and you have their file_ids. It creates a queryable vector index for semantic search.

    Perfect for:
    - Creating indexes from uploaded files
    - Re-indexing already registered documents with different chunk settings
    - Building search indexes for specific file collections

    Args:
        file_ids: List of file IDs to include in the RAG index (REQUIRED, must be registered files)
                  Example: ["file-abc123", "file-def456", "file-ghi789"]
                  Use ListUploadedFiles to see available file_ids
        index_name: Optional custom name for the index (auto-generated if not provided)
                    Example: "research_papers_2024"
        chunk_size: Size of text chunks for indexing in characters (default: 1000)
                    Smaller chunks = more precise retrieval, larger chunks = more context
        chunk_overlap: Overlap between chunks in characters (default: 200)
                       Prevents context loss at chunk boundaries
        visibility: Access scope for the created index: 'session' (current session only,
                    default), 'user' (persists across sessions for this user), or 'world'
                    (accessible to all authenticated users).
        mcp_session_id: Session ID for context isolation (auto-injected by framework)

    Returns:
        JSON with index creation results including:
        - status: "success" or "error"
        - index_id: Generated RAG index ID for querying
        - index_name: Name of the created index
        - total_chunks: Number of text chunks created
        - vector_store: Backend used (chromadb or ragflow)
        - query_hint: Example QueryRAGIndex command

    Examples:
        # Create index from uploaded files
        create_rag_index(
            file_ids=["file-abc123", "file-def456"],
            index_name="my_documents"
        )

        # Create index with custom chunking
        create_rag_index(
            file_ids=["file-research-001", "file-research-002"],
            chunk_size=500,
            chunk_overlap=100,
            index_name="small_chunk_research"
        )

    Related Tools:
        - ListUploadedFiles: Get available file_ids
        - CreateRAGIndexFromFolder: For filesystem folders (takes folder_path, not file_ids)
        - QueryRAGIndex: Search the created index
    """
    try:
        # Check which backend to use
        if backend_factory.is_ragflow_backend():
            logger.info("Using RAGFlow backend for index creation")
            return await _create_rag_index_ragflow(
                file_ids, index_name, chunk_size, chunk_overlap, mcp_session_id
            )
        else:
            logger.info("Using ChromaDB backend for index creation")
            return await _create_rag_index_chromadb(
                file_ids, index_name, chunk_size, chunk_overlap, mcp_session_id
            )
    except Exception as e:
        logger.error(f"Error in create_rag_index: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


async def _create_rag_index_ragflow(
    file_ids: List[str],
    index_name: Optional[str] = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    mcp_session_id: Optional[str] = None
) -> str:
    """Create RAG index using RAGFlow backend."""
    try:
        backend = backend_factory.create_backend("ragflow")
        if backend is None:
            return json.dumps({"error": "RAGFlow backend not available"})

        # Get session context
        session_data = await get_session_context(mcp_session_id) if mcp_session_id else {}
        uploaded_files = session_data.get("uploaded_files", {})

        # Generate index name if not provided
        if not index_name:
            index_name = f"ragflow_index_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Create knowledge base in RAGFlow
        kb_id = await backend.create_kb(
            name=index_name,
            description=f"RAG index for files: {', '.join(file_ids)}",
            config={
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap
            },
            session_id=mcp_session_id
        )

        # Ingest documents into the knowledge base
        for file_id in file_ids:
            if file_id in uploaded_files:
                file_info = uploaded_files[file_id]
                file_path = file_info.get("path", "")

                if os.path.exists(file_path):
                    await backend.ingest_document(
                        kb_id=kb_id,
                        file_path=file_path,
                        metadata={
                            "file_id": file_id,
                            "original_name": file_info.get("original_name", ""),
                            "session_id": mcp_session_id
                        }
                    )

        # Update session context with RAGFlow index info
        if mcp_session_id:
            session_data.setdefault("ragflow_indexes", {})[kb_id] = {
                "name": index_name,
                "files": file_ids,
                "created_at": datetime.now().isoformat(),
                "backend": "ragflow"
            }
            await update_session_context(mcp_session_id, session_data)

        return json.dumps({
            "success": True,
            "index_id": kb_id,
            "index_name": index_name,
            "files_indexed": file_ids,
            "backend": "ragflow",
            "message": f"RAGFlow index '{index_name}' created successfully"
        })

    except Exception as e:
        logger.error(f"Error creating RAGFlow index: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


async def _create_rag_index_chromadb(
    file_ids: List[str],
    index_name: Optional[str] = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    mcp_session_id: Optional[str] = None
) -> str:
    """Create RAG index using ChromaDB backend (existing implementation)."""
    try:
        # Get session context
        session_data = await get_session_context(mcp_session_id) if mcp_session_id else {}

        # Get file info
        uploaded_files = session_data.get("uploaded_files", {})
        if not uploaded_files:
            uploaded_files = session_data.get("uploaded_csv_files", {})

        # Validate all files exist
        missing_files = []
        for file_id in file_ids:
            if file_id not in uploaded_files:
                missing_files.append(file_id)

        if missing_files:
            return json.dumps({
                "error": f"Files not found: {missing_files}. Use ListUploadedFiles to see available files."
            })

        # Process each file and combine content
        all_content = ""
        combined_metadata = {"files": []}
        base_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")

        for file_id in file_ids:
            file_info = uploaded_files[file_id]

            # Enhanced file path resolution via shared resolver (reads Redis metadata + fallbacks)
            from .file_path_resolver import resolve_file_path
            resolved_path, paths_checked = await resolve_file_path(
                file_id=file_id,
                mcp_session_id=mcp_session_id,
                file_info=file_info,
            )

            if not resolved_path:
                logger.warning(f"RAG index: File ID {file_id} not found. Paths checked: {paths_checked}")
                return json.dumps({
                    "error": f"File {file_id} not found. Searched {len(paths_checked)} locations.",
                    "file_id": file_id,
                    "paths_checked": paths_checked,
                    "suggestions": [
                        "1. Use ListUploadedFiles tool to see available files",
                        "2. Verify the file ID is correct",
                        "3. Check if file was uploaded to current session"
                    ]
                })

            # Read file content
            try:
                with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # Add separator between files for better context
                    original_filename = file_info.get("original_filename", file_id)
                    all_content += f"\n\n=== FILE: {original_filename} ===\n\n{content}"

                    # Track file metadata
                    combined_metadata["files"].append({
                        "file_id": file_id,
                        "filename": original_filename,
                        "size": len(content)
                    })

            except Exception as e:
                return json.dumps({
                    "error": f"Failed to read file {file_id}: {e}"
                })

        logger.info(
            f"[RAG_INDEX] Combined {len(file_ids)} files, "
            f"total content: {len(all_content)} chars"
        )

        # Generate index ID (use first two file IDs in name for brevity)
        if index_name:
            index_id = index_name
        else:
            file_ids_snippet = "_".join(file_ids[:2])
            if len(file_ids) > 2:
                file_ids_snippet += f"_plus{len(file_ids)-2}"
            index_id = f"rag_{file_ids_snippet}_{hashlib.md5(all_content.encode()).hexdigest()[:8]}"

        # Create combined metadata
        # Note: ChromaDB doesn't accept lists in metadata, so we convert file_ids to string
        metadata = {
            "file_ids": ",".join(file_ids) if file_ids else "",  # Convert list to comma-separated string
            "files": json.dumps(combined_metadata["files"]),  # Serialize complex object to string
            "created_at": datetime.now().isoformat(),
            "session_id": mcp_session_id,
            "total_files": len(file_ids)
        }

        # Create RAG index
        result = await rag_processor.create_index_from_text(
            text=all_content,
            index_id=index_id,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        # Store index info in session if successful
        if result.get("success") and mcp_session_id:
            if "rag_indexes" not in session_data:
                session_data["rag_indexes"] = {}

            session_data["rag_indexes"][index_id] = {
                "file_ids": file_ids,
                "files": combined_metadata["files"],
                "created_at": datetime.now().isoformat(),
                "chunks": result.get("chunks_created", 0),
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "total_files": len(file_ids)
            }

            await update_session_context(mcp_session_id, session_data)

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error in create_rag_index: {e}", exc_info=True)
        return json.dumps({"error": str(e)})

async def query_rag_index(
    index_id: str,
    query: str,
    top_k: int = 3,
    score_threshold: Optional[float] = None,
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Query a RAG index for relevant information.

    Args:
        index_id: The ID of the RAG index to query
        query: The search query or question
        top_k: Number of top results to return (default: 3)
        score_threshold: Optional minimum relevance score
        mcp_session_id: Session ID for context

    Returns:
        Relevant text chunks matching the query
    """
    try:
        # Determine backend based on index_id prefix
        # ChromaDB indexes always start with "chromadb_"
        # RAGFlow indexes don't have this prefix
        if index_id.startswith("chromadb_"):
            logger.info(f"Index ID '{index_id}' indicates ChromaDB backend")
            return await _query_rag_index_chromadb(
                index_id, query, top_k, score_threshold, mcp_session_id
            )
        elif backend_factory.is_ragflow_backend():
            logger.info(f"Using RAGFlow backend for index '{index_id}'")
            try:
                return await _query_rag_index_ragflow(
                    index_id, query, top_k, score_threshold, mcp_session_id
                )
            except AttributeError as e:
                # RAGFlow backend method issue - fallback to ChromaDB
                logger.warning(f"RAGFlow backend error: {e}. Falling back to ChromaDB")
                return await _query_rag_index_chromadb(
                    index_id, query, top_k, score_threshold, mcp_session_id
                )
        else:
            logger.info("Using ChromaDB backend for index query")
            return await _query_rag_index_chromadb(
                index_id, query, top_k, score_threshold, mcp_session_id
            )
    except Exception as e:
        logger.error(f"Error in query_rag_index: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


async def _query_rag_index_ragflow(
    index_id: str,
    query: str,
    top_k: int = 3,
    score_threshold: Optional[float] = None,
    mcp_session_id: Optional[str] = None
) -> str:
    """Query RAG index using RAGFlow backend."""
    try:
        backend = backend_factory.create_backend("ragflow")
        if backend is None:
            return json.dumps({"error": "RAGFlow backend not available"})

        # Query the knowledge base in RAGFlow
        results = await backend.query(
            kb_id=index_id,
            query=query,
            top_k=top_k,
            filters={"score_threshold": score_threshold} if score_threshold else None,
            include_metadata=True,
            session_id=mcp_session_id
        )

        # Add session context if available
        if mcp_session_id:
            session_data = await get_session_context(mcp_session_id)
            ragflow_indexes = session_data.get("ragflow_indexes", {})

            if index_id in ragflow_indexes:
                results["index_metadata"] = ragflow_indexes[index_id]

        return json.dumps(results, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error querying RAGFlow index: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


async def _query_rag_index_chromadb(
    index_id: str,
    query: str,
    top_k: int = 3,
    score_threshold: Optional[float] = None,
    mcp_session_id: Optional[str] = None
) -> str:
    """Query RAG index using ChromaDB backend (existing implementation)."""
    try:
        # Query the index
        result = await rag_processor.query_index(
            index_id=index_id,
            query=query,
            top_k=top_k,
            score_threshold=score_threshold
        )

        # Add session context if available
        if mcp_session_id and result.get("success"):
            session_data = await get_session_context(mcp_session_id)
            rag_indexes = session_data.get("rag_indexes", {})

            if index_id in rag_indexes:
                result["index_metadata"] = rag_indexes[index_id]

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error querying ChromaDB index: {e}", exc_info=True)
        return json.dumps({"error": str(e)})

async def list_rag_indexes(
    mcp_session_id: Optional[str] = None,
    include_world: bool = True,
    include_user: bool = True,
    user_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    List available RAG indexes across all visibility scopes the caller can access.

    Args:
        mcp_session_id: Session ID for context
        include_world: Include world-scoped indexes (default True)
        include_user: Include user-scoped indexes for the current user (default True)
        user_context: User context dict with user_id/username for ownership filtering

    Returns:
        List of available RAG indexes with metadata
    """
    try:
        # Check which backend to use
        if backend_factory.is_ragflow_backend():
            logger.info("Using RAGFlow backend for listing indexes")
            return await _list_rag_indexes_ragflow(mcp_session_id)
        else:
            logger.info("Using ChromaDB backend for listing indexes")
            return await _list_rag_indexes_chromadb(
                mcp_session_id=mcp_session_id,
                include_world=include_world,
                include_user=include_user,
                user_context=user_context,
            )
    except Exception as e:
        logger.error(f"Error in list_rag_indexes: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


async def _list_rag_indexes_ragflow(
    mcp_session_id: Optional[str] = None
) -> str:
    """List RAG indexes using RAGFlow backend."""
    try:
        backend = backend_factory.create_backend("ragflow")
        if backend is None:
            return json.dumps({"error": "RAGFlow backend not available"})

        result = {"indexes": [], "backend": "ragflow"}

        # Get session-specific indexes
        if mcp_session_id:
            session_data = await get_session_context(mcp_session_id)
            ragflow_indexes = session_data.get("ragflow_indexes", {})

            for kb_id, index_info in ragflow_indexes.items():
                result["indexes"].append({
                    "index_id": kb_id,
                    "backend": "ragflow",
                    **index_info
                })

            # Also try to list from RAGFlow API
            try:
                kb_list = await backend.list_kbs(session_id=mcp_session_id)
                if isinstance(kb_list, list):
                    for kb in kb_list:
                        # Add if not already in session data
                        if not any(idx["index_id"] == kb.get("id") for idx in result["indexes"]):
                            result["indexes"].append({
                                "index_id": kb.get("id"),
                                "name": kb.get("name"),
                                "backend": "ragflow",
                                "from_api": True
                            })
            except Exception as e:
                logger.warning(f"Could not list KBs from RAGFlow API: {e}")

        result["total_indexes"] = len(result["indexes"])
        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error listing RAGFlow indexes: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


async def _list_rag_indexes_chromadb(
    mcp_session_id: Optional[str] = None,
    include_world: bool = True,
    include_user: bool = True,
    user_context: Optional[Dict[str, Any]] = None,
) -> str:
    """List RAG indexes using ChromaDB backend with visibility-aware discovery.

    Queries three sources:
    1. Session context (ephemeral in-memory dict — indexes created in this session)
    2. ChromaDB collections with world visibility (``w_`` prefix)
    3. ChromaDB collections with user visibility (``u_`` prefix) for the current owner
    """
    try:
        result = {"indexes": [], "backend": "chromadb"}
        seen_ids = set()

        # Extract owner_id from user_context if available
        owner_id = None
        if user_context:
            owner_id = user_context.get("user_id")

        # 1. Session-scoped indexes from session context (existing behaviour)
        if mcp_session_id:
            session_data = await get_session_context(mcp_session_id)
            rag_indexes = session_data.get("rag_indexes", {})

            for index_id, index_info in rag_indexes.items():
                index_path = os.path.join(RAG_INDEX_DIR, index_id)
                result["indexes"].append({
                    "index_id": index_id,
                    "visibility": "session",
                    "exists_on_disk": os.path.exists(index_path),
                    "backend": "chromadb",
                    **index_info
                })
                seen_ids.add(index_id)
        else:
            # Fallback: list all indexes on disk when no session
            if os.path.exists(RAG_INDEX_DIR):
                for index_id in os.listdir(RAG_INDEX_DIR):
                    index_path = os.path.join(RAG_INDEX_DIR, index_id)
                    if os.path.isdir(index_path):
                        result["indexes"].append({
                            "index_id": index_id,
                            "visibility": "session",
                            "path": index_path,
                            "backend": "chromadb"
                        })
                        seen_ids.add(index_id)

        # 2. Discover world-scoped and user-scoped indexes from ChromaDB
        if include_world or include_user:
            try:
                backend = backend_factory.create_backend("chromadb")
                if backend and hasattr(backend, 'client'):
                    collections = backend.client.list_collections()
                    logger.info(
                        f"[RAG_DISCOVERY] Scanning {len(collections)} ChromaDB collections "
                        f"for world/user indexes (include_world={include_world}, "
                        f"include_user={include_user}, owner_id={owner_id})"
                    )
                    for collection in collections:
                        metadata = collection.metadata or {}
                        kb_id = metadata.get("kb_id")
                        if not kb_id or kb_id in seen_ids:
                            continue

                        vis = metadata.get("visibility", "session")

                        if vis == "world" and include_world:
                            result["indexes"].append({
                                "index_id": kb_id,
                                "name": metadata.get("name", "Unknown"),
                                "visibility": "world",
                                "description": metadata.get("description", ""),
                                "document_count": collection.count(),
                                "created_at": metadata.get("created_at"),
                                "backend": "chromadb",
                            })
                            seen_ids.add(kb_id)
                        elif vis == "user" and include_user and owner_id:
                            if metadata.get("owner_id") == owner_id:
                                result["indexes"].append({
                                    "index_id": kb_id,
                                    "name": metadata.get("name", "Unknown"),
                                    "visibility": "user",
                                    "description": metadata.get("description", ""),
                                    "document_count": collection.count(),
                                    "created_at": metadata.get("created_at"),
                                    "owner_id": metadata.get("owner_id"),
                                    "backend": "chromadb",
                                })
                                seen_ids.add(kb_id)
            except Exception as e:
                logger.warning(f"Could not discover world/user indexes from ChromaDB: {e}")

        result["total_indexes"] = len(result["indexes"])
        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error listing ChromaDB indexes: {e}", exc_info=True)
        return json.dumps({"error": str(e)})

async def delete_rag_index(
    index_id: str,
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Delete a RAG index.

    Args:
        index_id: The ID of the RAG index to delete
        mcp_session_id: Session ID for context

    Returns:
        Deletion status
    """
    try:
        # Check which backend to use
        if backend_factory.is_ragflow_backend():
            logger.info("Using RAGFlow backend for index deletion")
            return await _delete_rag_index_ragflow(index_id, mcp_session_id)
        else:
            logger.info("Using ChromaDB backend for index deletion")
            return await _delete_rag_index_chromadb(index_id, mcp_session_id)
    except Exception as e:
        logger.error(f"Error in delete_rag_index: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


async def _delete_rag_index_ragflow(
    index_id: str,
    mcp_session_id: Optional[str] = None
) -> str:
    """Delete RAG index using RAGFlow backend."""
    try:
        backend = backend_factory.create_backend("ragflow")
        if backend is None:
            return json.dumps({"error": "RAGFlow backend not available"})

        # Delete the knowledge base in RAGFlow
        result = await backend.delete_kb(kb_id=index_id, session_id=mcp_session_id)

        # Remove from session if successful
        if result and mcp_session_id:
            session_data = await get_session_context(mcp_session_id)
            ragflow_indexes = session_data.get("ragflow_indexes", {})

            if index_id in ragflow_indexes:
                del ragflow_indexes[index_id]
                session_data["ragflow_indexes"] = ragflow_indexes
                await update_session_context(mcp_session_id, session_data)
                result = {"success": True, "deleted": index_id, "removed_from_session": True}
            else:
                result = {"success": True, "deleted": index_id}

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error deleting RAGFlow index: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


async def _delete_rag_index_chromadb(
    index_id: str,
    mcp_session_id: Optional[str] = None
) -> str:
    """Delete RAG index using ChromaDB backend (existing implementation)."""
    try:
        # Delete the index
        result = await rag_processor.delete_index(index_id)

        # Remove from session if successful
        if result.get("success") and mcp_session_id:
            session_data = await get_session_context(mcp_session_id)
            rag_indexes = session_data.get("rag_indexes", {})

            if index_id in rag_indexes:
                del rag_indexes[index_id]
                session_data["rag_indexes"] = rag_indexes
                await update_session_context(mcp_session_id, session_data)
                result["removed_from_session"] = True

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error deleting ChromaDB index: {e}", exc_info=True)
        return json.dumps({"error": str(e)})

def register_tools(mcp_instance, llm_client=None):
    """Register RAG processing tools with the MCP server."""
    # Register the tools with the passed-in mcp instance
    mcp_instance.tool()(create_rag_index)
    mcp_instance.tool()(query_rag_index)
    mcp_instance.tool()(list_rag_indexes)
    mcp_instance.tool()(delete_rag_index)
    logger.info("RAG processing tools registered")