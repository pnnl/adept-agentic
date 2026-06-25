"""
Knowledge Base Integration Module

Provides abstractions for various knowledge base systems including:
- RAGFlow: Production knowledge base with document ingestion (deprecated FY26Q4)
- ChromaDB: Development/embedded vector database
"""

try:
    from .ragflow import (
        RAGFlowClient,
        RAGFlowBackend,
        RAGFlowSessionSync,
        RAGFlowException,
        RAGFlowTimeoutException,
        RAGFlowAuthException,
        RAGFlowBackendStrategy,
    )
except ImportError:
    RAGFlowClient = None
    RAGFlowBackend = None
    RAGFlowSessionSync = None
    RAGFlowException = None
    RAGFlowTimeoutException = None
    RAGFlowAuthException = None
    RAGFlowBackendStrategy = None

__all__ = [
    "RAGFlowClient",
    "RAGFlowBackend",
    "RAGFlowSessionSync",
    "RAGFlowException",
    "RAGFlowTimeoutException",
    "RAGFlowAuthException",
    "RAGFlowBackendStrategy",
]
