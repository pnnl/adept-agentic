import chromadb
import os
from typing import List, Dict, Any, Optional
from agentic_framework_pkg.logger_config import get_logger # Assuming you have a shared logger

# Assuming an embedding function is available, e.g., from LiteLLM or a direct provider
# from .embedding_utils import get_embeddings # Placeholder for your embedding logic

logger = get_logger(__name__)

# Get the URL for the vector database server from environment variables
VECTOR_DB_URL = os.getenv("VECTOR_DB_URL", "http://localhost:8001")

class VectorStoreManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(VectorStoreManager, cls).__new__(cls)
            cls._instance.client = None # Initialize client to None
        return cls._instance

    def __init__(self):
        if self.client is None: # Only initialize if not already done
            logger.info(f"Initializing ChromaDB client to connect to: {VECTOR_DB_URL}")
            try:
                if "://" in VECTOR_DB_URL:
                    url_no_scheme = VECTOR_DB_URL.split("://")[1]
                else:
                    url_no_scheme = VECTOR_DB_URL

                if ":" in url_no_scheme:
                    host, port_str = url_no_scheme.split(":")
                    port = int(port_str)
                else:
                    host = url_no_scheme
                    port = 8001
                    logger.warning(f"Port not specified in VECTOR_DB_URL ('{VECTOR_DB_URL}'), defaulting to {port}.")

                logger.info(f"Connecting to ChromaDB at host: {host}, port: {port}")
                self.client = chromadb.HttpClient(host=host, port=port)
                logger.info("ChromaDB client initialized.")
            except Exception as e:
                logger.error(f"Failed to parse VECTOR_DB_URL ('{VECTOR_DB_URL}') or initialize ChromaDB client: {e}", exc_info=True)
                raise RuntimeError(f"Could not initialize VectorStoreManager: {e}") from e

    def get_or_create_collection(self, name: str, metadata: Optional[Dict[str, Any]] = None):
        try:
            collection = self.client.get_or_create_collection(name=name, metadata=metadata)
            logger.info(f"Accessed or created collection: {name}")
            return collection
        except Exception as e:
            logger.error(f"Error getting or creating collection '{name}': {e}", exc_info=True)
            raise

    def add_documents(self, collection_name: str, documents: List[str], embeddings: Optional[List[List[float]]] = None, metadatas: Optional[List[dict]] = None, ids: Optional[List[str]] = None):
        if not documents:
            logger.warning(f"No documents provided to add to collection '{collection_name}'.")
            return
        try:
            collection = self.get_or_create_collection(collection_name)
            if embeddings:
                collection.add(embeddings=embeddings, documents=documents, metadatas=metadatas, ids=ids)
            else:
                collection.add(documents=documents, metadatas=metadatas, ids=ids)
            logger.info(f"Added {len(documents)} documents to collection '{collection_name}'.")
        except Exception as e:
            logger.error(f"Error adding documents to collection '{collection_name}': {e}", exc_info=True)
            raise

    def query_collection(self, collection_name: str, query_texts: Optional[List[str]] = None, 
                         query_embeddings: Optional[List[List[float]]] = None, n_results: int = 5, 
                         where: Optional[dict] = None, where_document: Optional[dict] = None,
                         include: Optional[List[str]] = None,
                         ) -> Dict[str, Any]:
        if not query_texts and not query_embeddings:
            raise ValueError("Either query_texts or query_embeddings must be provided.")
        try:
            collection = self.get_or_create_collection(collection_name)
            results = collection.query(
                query_texts=query_texts,
                query_embeddings=query_embeddings,
                n_results=n_results,
                where=where,
                where_document=where_document
            )
            logger.info(f"Queried collection '{collection_name}' with {len(query_texts or query_embeddings)} queries, got {len(results.get('ids', [[]])[0])} results for the first query.")
            return results
        except Exception as e:
            logger.error(f"Error querying collection '{collection_name}': {e}", exc_info=True)
            raise