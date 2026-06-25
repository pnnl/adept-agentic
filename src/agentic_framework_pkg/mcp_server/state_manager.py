"""
This module provides state management for the MCP server.

DEPRECATED: The concept of a stateful MCP server is now obsolete in the
three-tier architecture. All state is managed by the `orchestration_service`.
This module is retained for historical context and because some tools may still
use its session initialization logic, but the underlying ChromaDB-based state
is no longer the primary mechanism for conversational state.

The module uses ChromaDB for persisting session context and embeddings.
"""
import chromadb
import json
import os
import datetime # For timestamps
import asyncio # For to_thread
from collections import defaultdict
from dotenv import load_dotenv
from ..logger_config import get_logger # Use centralized logger
from typing import Optional, Dict, Any, List

# Load environment variables from .env file if it exists.
# This allows CHROMA_DB_PATH (and other env vars) to be set in a .env file,
# which is useful for local development.
load_dotenv()

logger = get_logger(__name__)

# ChromaDB client instance and collection names
_client: Optional[chromadb.ClientAPI] = None
_sessions_collection: Optional[chromadb.Collection] = None
_embeddings_collection: Optional[chromadb.Collection] = None

SESSIONS_COLLECTION_NAME = "mcp_sessions"
EMBEDDINGS_COLLECTION_NAME = "mcp_embeddings" # General purpose embeddings
# Default path for ChromaDB persistent storage if CHROMA_DB_PATH is not set in the environment.
DEFAULT_CHROMA_DB_PATH = "./chroma_data"

# Per-session locks to prevent race conditions in concurrent GET→MODIFY→UPSERT operations.
# When multiple coroutines (e.g., asyncio.gather in batch file processing) update the same
# session concurrently, the non-atomic read-modify-write can cause last-write-wins data loss.
_session_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

def _get_chroma_client_sync() -> chromadb.ClientAPI:
    """
    Initializes the ChromaDB client, running synchronously.
    Intended to be called within an asyncio.to_thread context.
    """
    # This function is synchronous and intended to be run in a thread
    global _client
    if _client is None:
        # Try to get CHROMA_DB_PATH from environment variables (which .env would have loaded into)
        chroma_db_path_env = os.getenv("CHROMA_DB_PATH")

        if chroma_db_path_env:
            chroma_db_path = chroma_db_path_env
            # Log will be handled by the "Initializing persistent/in-memory" message later
        else:
            chroma_db_path = DEFAULT_CHROMA_DB_PATH
            logger.info(f"CHROMA_DB_PATH not set, defaulting to persistent storage at: {chroma_db_path}")

        if chroma_db_path.lower() != ":memory:":
            logger.info(f"Initializing persistent ChromaDB client at: {chroma_db_path}")
            os.makedirs(chroma_db_path, exist_ok=True) # Ensure directory exists
            _client = chromadb.PersistentClient(path=chroma_db_path)
        else:
            logger.info("Initializing in-memory ChromaDB client.")
            _client = chromadb.Client() # Ephemeral client
    return _client

async def initialize_db():
    """
    Asynchronously initializes the ChromaDB client and collections.
    """
    global _sessions_collection, _embeddings_collection
    
    client_instance = await asyncio.to_thread(_get_chroma_client_sync)
    
    logger.info(f"Getting or creating ChromaDB collection: {SESSIONS_COLLECTION_NAME}")
    _sessions_collection = await asyncio.to_thread(client_instance.get_or_create_collection, name=SESSIONS_COLLECTION_NAME)
    
    logger.info(f"Getting or creating ChromaDB collection: {EMBEDDINGS_COLLECTION_NAME}")
    _embeddings_collection = await asyncio.to_thread(client_instance.get_or_create_collection, name=EMBEDDINGS_COLLECTION_NAME)

    logger.info("ChromaDB initialized and collections are ready.")

def _get_sessions_collection() -> chromadb.Collection:
    """Returns the singleton sessions collection instance."""
    if _sessions_collection is None:
        raise RuntimeError("Sessions collection not initialized. Call initialize_db first.")
    return _sessions_collection

def _get_embeddings_collection() -> chromadb.Collection:
    """Returns the singleton embeddings collection instance."""
    if _embeddings_collection is None:
        raise RuntimeError("Embeddings collection not initialized. Call initialize_db first.")
    return _embeddings_collection

async def create_session_if_not_exists(session_id: str, client_id: Optional[str] = None, initial_context: Optional[Dict[str, Any]] = None) -> None:
    """Creates a new session in the database if one does not already exist."""
    collection = _get_sessions_collection()
    
    existing_session_results = await asyncio.to_thread(collection.get, ids=[session_id])
    
    if not existing_session_results['ids']: # Check if id list is empty
        current_time = datetime.datetime.utcnow().isoformat()
        metadata = {
            "client_id": client_id or "", # Ensure not None
            "context_data": json.dumps(initial_context or {}),
            "created_at": current_time,
            "updated_at": current_time
        }
        await asyncio.to_thread(
            collection.add,
            ids=[session_id],
            documents=[session_id], # Placeholder document, as session data is in metadata
            metadatas=[metadata]
        )
        logger.info("Created MCP session: %s", session_id)
    else:
        logger.debug("MCP Session %s already exists. Not creating.", session_id)


async def get_session_context(session_id: str) -> Dict[str, Any]:
    """Retrieves the context data for a given session."""
    collection = _get_sessions_collection()
    session_data = await asyncio.to_thread(collection.get, ids=[session_id], include=['metadatas'])
    
    if session_data['ids'] and session_data['metadatas']:
        metadata = session_data['metadatas'][0]
        context_str = metadata.get("context_data")
        if context_str:
            try:
                return json.loads(context_str)
            except json.JSONDecodeError:
                logger.error("Failed to decode JSON context for session %s. Returning empty context.", session_id, exc_info=True)
                return {}
    return {} # Return empty dict if no session or context found

async def update_session_context(session_id: str, new_context_data: Dict[str, Any]) -> None:
    """Updates (upserts) the context data for a given session.

    Uses a per-session lock to prevent race conditions when multiple coroutines
    (e.g., concurrent file registrations via asyncio.gather) read-modify-write
    the same session state simultaneously.
    """
    async with _session_locks[session_id]:
        collection = _get_sessions_collection()
        current_time = datetime.datetime.utcnow().isoformat()

        # Fetch existing data to preserve fields not being updated (client_id, created_at) during upsert.
        existing_data_results = await asyncio.to_thread(collection.get, ids=[session_id], include=['metadatas'])

        final_metadata = {
            "context_data": json.dumps(new_context_data),
            "updated_at": current_time
        }

        if existing_data_results['ids'] and existing_data_results['metadatas']:
            # Session exists, it's an update. Preserve existing client_id and created_at.
            existing_metadata = existing_data_results['metadatas'][0]
            final_metadata["client_id"] = existing_metadata.get("client_id", "")
            final_metadata["created_at"] = existing_metadata.get("created_at", current_time) # Should ideally exist
        else:
            # Session does not exist, it's an insert part of an upsert.
            # client_id is not provided to this function, so default to empty string.
            final_metadata["client_id"] = ""
            final_metadata["created_at"] = current_time

        await asyncio.to_thread(
            collection.upsert,
            ids=[session_id],
            documents=[session_id], # Placeholder document
            metadatas=[final_metadata]
        )
        logger.debug("Upserted context for MCP session: %s", session_id)

async def delete_session(session_id: str) -> None:
    """Deletes a session and its associated embeddings."""
    sessions_coll = _get_sessions_collection()
    embeddings_coll = _get_embeddings_collection()
        
    await asyncio.to_thread(sessions_coll.delete, ids=[session_id])
    logger.info("Deleted MCP session: %s", session_id)
    
    # Delete associated embeddings (mimicking ON DELETE CASCADE)
    # This requires embeddings to have a "session_id" in their metadata.
    await asyncio.to_thread(embeddings_coll.delete, where={"session_id": session_id})
    logger.info(f"Attempted deletion of associated embeddings for session: {session_id} using where clause.")

# --- Generic Embedding Management Functions ---

async def add_embeddings_batch(
    ids: List[str],
    documents: List[str],
    embeddings: List[List[float]],
    metadatas: List[Dict[str, Any]]
):
    """Adds a batch of embeddings to the embeddings collection."""
    collection = _get_embeddings_collection()
    await asyncio.to_thread(
        collection.add,
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas
    )
    logger.debug(f"Added batch of {len(ids)} embeddings.")

async def get_embeddings(
    ids: Optional[List[str]] = None,
    where: Optional[Dict[str, Any]] = None,
    include: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Generic get function for embeddings from the embeddings collection."""
    collection = _get_embeddings_collection()
    if include is None:
        include = ["metadatas", "documents", "embeddings"] # Default fields to retrieve
        
    results = await asyncio.to_thread(collection.get, ids=ids, where=where, include=include)
    return results

async def query_embeddings(
    query_embeddings_list: List[List[float]],
    n_results: int = 5,
    where: Optional[Dict[str, Any]] = None,
    where_document: Optional[Dict[str, Any]] = None,
    include: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Generic query function for embeddings from the embeddings collection."""
    collection = _get_embeddings_collection()
    if include is None:
        include = ["metadatas", "documents", "distances"] # Default fields for query results

    results = await asyncio.to_thread(
        collection.query,
        query_embeddings=query_embeddings_list,
        n_results=n_results,
        where=where,
        where_document=where_document,
        include=include
    )
    return results

async def delete_embeddings(
    ids: Optional[List[str]] = None,
    where: Optional[Dict[str, Any]] = None
) -> None:
    """Deletes embeddings from the embeddings collection based on ids or a where filter."""
    collection = _get_embeddings_collection()
    await asyncio.to_thread(collection.delete, ids=ids, where=where)
    logger.info(f"Attempted deletion of embeddings with ids: {ids} or where filter: {where}")
    
async def clear_embeddings() -> None:
    """Clears all embeddings from the embeddings collection."""
    collection = _get_embeddings_collection()
    await asyncio.to_thread(collection.delete, where={})  # Deletes all entries
    logger.info("Cleared all embeddings from the collection.")

async def get_all_embeddings() -> Dict[str, Any]:
    """Retrieves all embeddings from the embeddings collection."""
    collection = _get_embeddings_collection()
    results = await asyncio.to_thread(collection.get, where={})  # Get all entries
    return results

async def get_all_sessions() -> Dict[str, Any]:
    """Retrieves all sessions from the sessions collection."""
    collection = _get_sessions_collection()
    results = await asyncio.to_thread(collection.get, where={})  # Get all entries
    return results

async def clear_sessions() -> None:
    """Clears all sessions from the sessions collection."""
    collection = _get_sessions_collection()
    await asyncio.to_thread(collection.delete, where={})  # Deletes all entries
    logger.info("Cleared all sessions from the collection.")

async def get_session_ids() -> List[str]:
    """Retrieves all session IDs from the sessions collection."""
    collection = _get_sessions_collection()
    results = await asyncio.to_thread(collection.get, where={}, include=["ids"])
    return results.get("ids", [])  # Return list of session IDs or empty list if none

async def get_session_metadata(session_id: str) -> Dict[str, Any]:
    """Retrieves metadata for a specific session by ID."""
    collection = _get_sessions_collection()
    results = await asyncio.to_thread(collection.get, ids=[session_id], include=["metadatas"])
    
    if results['ids'] and results['metadatas']:
        return results['metadatas'][0]  # Return the first metadata entry
    return {}  # Return empty dict if no session found

async def update_session_metadata(session_id: str, new_metadata: Dict[str, Any]) -> None:
    """Updates metadata for a specific session by ID.

    Uses a per-session lock to prevent race conditions when multiple coroutines
    read-modify-write the same session metadata simultaneously.
    """
    async with _session_locks[session_id]:
        collection = _get_sessions_collection()

        # Fetch existing metadata to preserve fields not being updated
        existing_data_results = await asyncio.to_thread(collection.get, ids=[session_id], include=['metadatas'])

        if existing_data_results['ids'] and existing_data_results['metadatas']:
            existing_metadata = existing_data_results['metadatas'][0]
            # Merge new metadata with existing, preserving existing fields
            final_metadata = {**existing_metadata, **new_metadata}
        else:
            final_metadata = new_metadata  # If no existing data, just use new metadata

        await asyncio.to_thread(
            collection.upsert,
            ids=[session_id],
            documents=[session_id],  # Placeholder document
            metadatas=[final_metadata]
        )
        logger.debug("Updated metadata for MCP session: %s", session_id)
    
async def delete_session_metadata(session_id: str) -> None:
    """Deletes metadata for a specific session by ID."""
    collection = _get_sessions_collection()
    
    # Fetch existing metadata to ensure session exists
    existing_data_results = await asyncio.to_thread(collection.get, ids=[session_id], include=['metadatas'])
    
    if existing_data_results['ids'] and existing_data_results['metadatas']:
        # Session exists, proceed with deletion
        await asyncio.to_thread(collection.delete, ids=[session_id])
        logger.info("Deleted metadata for MCP session: %s", session_id)
    else:
        logger.warning("Attempted to delete metadata for non-existent session: %s", session_id)