"""
This module provides a self-contained, in-memory RAG and SQL toolset.

It is designed as a tutorial example to demonstrate how to build a specialized
tool server. It manages its own in-memory FAISS index for vector search and an
in-memory SQLite database for structured data queries.

Architectural Role:
-   **Tutorial Example:** Serves as a clear, isolated example of how to create
    a new tool server with both RAG and structured data capabilities.
-   **Executor Logic:** Contains the implementation for tools that ingest text,
    query a vector store, create SQL tables from CSVs, and execute SQL queries.
-   **In-Memory State:** All state (the FAISS index and SQLite database) is
    ephemeral and is lost when the server restarts. This makes it ideal for
    demonstrations and testing without requiring external dependencies.
"""
from fastmcp import FastMCP, Context
from ...logger_config import get_logger
import os
from typing import Dict, Any, List, Optional
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
import pandas as pd
import sqlite3
from sqlalchemy import create_engine

logger = get_logger(__name__)

# --- In-memory Knowledge Base for Unstructured Text ---
KNOWLEDGE_BASE: Dict[str, str] = {}
FAISS_INDEX = None
INDEX_TO_DOC_ID: List[str] = []
EMBEDDING_MODEL = None

# --- In-memory SQLite Database for Structured Text Analysis ---
DB_CONNECTION = None
DB_ENGINE = None
DB_FILE = ":memory:" # Use an in-memory database for simplicity

def _initialize_rag_components():
    """Initializes the in-memory RAG components (model, index, database)."""
    global EMBEDDING_MODEL, FAISS_INDEX, DB_CONNECTION, DB_ENGINE
    if EMBEDDING_MODEL is None:
        EMBEDDING_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    if FAISS_INDEX is None:
        embedding_dim = EMBEDDING_MODEL.get_sentence_embedding_dimension()
        FAISS_INDEX = faiss.IndexFlatL2(embedding_dim)
    if DB_CONNECTION is None:
        DB_CONNECTION = sqlite3.connect(DB_FILE, check_same_thread=False)
        DB_ENGINE = create_engine(f'sqlite:///{DB_FILE}')

def register_tools(mcp: FastMCP):
    """Registers the simple RAG and SQL tools with the MCP server."""
    _initialize_rag_components()

    # --- Tools for Unstructured Text (Vector RAG) ---

    @mcp.tool()
    async def ingest_text_document(ctx: Context, doc_id: str, content: str) -> Dict[str, Any]:
        """
        Ingests an unstructured text document into the in-memory vector knowledge base.
        """
        await ctx.info(f"Ingesting unstructured text document with ID: {doc_id}")
        KNOWLEDGE_BASE[doc_id] = content
        embedding = EMBEDDING_MODEL.encode([content])
        FAISS_INDEX.add(np.array(embedding, dtype=np.float32))
        INDEX_TO_DOC_ID.append(doc_id)
        return {"status": "success", "doc_id": doc_id, "message": "Document ingested successfully."}

    @mcp.tool()
    async def query_text_knowledge_base(ctx: Context, query: str, top_k: int = 3) -> Dict[str, Any]:
        """
        Queries the in-memory vector knowledge base using vector similarity search.
        """
        await ctx.info(f"Querying text knowledge base with: '{query}'")
        if FAISS_INDEX.ntotal == 0:
            return {"results": [], "message": "Knowledge base is empty."}
        query_embedding = EMBEDDING_MODEL.encode([query])
        distances, indices = FAISS_INDEX.search(np.array(query_embedding, dtype=np.float32), top_k)
        results = []
        for i, idx in enumerate(indices[0]):
            if idx != -1:
                doc_id = INDEX_TO_DOC_ID[idx]
                results.append({
                    "doc_id": doc_id,
                    "content": KNOWLEDGE_BASE[doc_id],
                    "distance": float(distances[0][i])
                })
        return {"results": results}

    # --- Tools for Structured Text (CSV/Excel to SQL) ---

    @mcp.tool()
    async def create_sql_table_from_csv(ctx: Context, file_path: str, table_name: str) -> Dict[str, Any]:
        """
        Reads a CSV file and creates a new table in the in-memory SQLite database.
        """
        await ctx.info(f"Creating SQL table '{table_name}' from file: {file_path}")
        try:
            # The on_bad_lines='skip' parameter tells pandas to ignore problematic rows.
            df = pd.read_csv(file_path, on_bad_lines='skip')
            df.to_sql(table_name, DB_ENGINE, if_exists='replace', index=False)
            return {"status": "success", "message": f"Table '{table_name}' created successfully. Some rows may have been skipped due to errors."}
        except Exception as e:
            logger.error(f"Failed to create table from CSV {file_path}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    async def create_sql_table_from_excel(ctx: Context, file_path: str, table_name: str) -> Dict[str, Any]:
        """
        Reads an Excel file and creates a new table in the in-memory SQLite database.
        """
        await ctx.info(f"Creating SQL table '{table_name}' from Excel file: {file_path}")
        try:
            # Pandas' read_excel is generally robust, but we'll wrap it for safety.
            df = pd.read_excel(file_path)
            df.to_sql(table_name, DB_ENGINE, if_exists='replace', index=False)
            return {"status": "success", "message": f"Table '{table_name}' created successfully from Excel file."}
        except Exception as e:
            logger.error(f"Failed to create table from Excel {file_path}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    async def generate_natural_language_sql_query(ctx: Context, user_query: str, table_name: str) -> Dict[str, Any]:
        """
        Takes a natural language query and generates a plausible SQL query.
        (This is a simplified placeholder for a real text-to-SQL model).
        """
        await ctx.info(f"Generating SQL query for: '{user_query}' on table '{table_name}'")
        # This is a very basic implementation. A real version would use an LLM.
        # For this example, we'll just do a simple keyword mapping.
        if "average price" in user_query.lower():
            sql_query = f"SELECT AVG(Price) FROM {table_name};"
        elif "how many properties" in user_query.lower():
            sql_query = f"SELECT COUNT(*) FROM {table_name};"
        else:
            sql_query = f"SELECT * FROM {table_name} LIMIT 5;" # Default fallback
        return {"status": "success", "sql_query": sql_query}

    @mcp.tool()
    async def execute_sqlite_query(ctx: Context, sql_query: str) -> Dict[str, Any]:
        """
        Executes a given SQL query against the in-memory SQLite database.
        """
        await ctx.info(f"Executing SQL query: {sql_query}")
        try:
            cursor = DB_CONNECTION.cursor()
            cursor.execute(sql_query)
            results = cursor.fetchall()
            column_names = [description[0] for description in cursor.description]
            return {"status": "success", "results": [dict(zip(column_names, row)) for row in results]}
        except Exception as e:
            logger.error(f"Failed to execute SQL query '{sql_query}': {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    logger.info("Simple RAG and Text Analysis MCP tools registered.")
