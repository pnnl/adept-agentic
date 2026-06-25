"""
SQL Transformation Tools for MCP Server

This module provides tools for converting uploaded files to SQL-queryable
format and executing SQL queries against them.
"""
import os
import json
import sqlite3
import pandas as pd
from typing import Dict, Any, Optional, List
from datetime import datetime
import tempfile
from pathlib import Path

from ..server import mcp
from ...logger_config import get_logger
from ..state_manager import get_session_context, update_session_context

logger = get_logger(__name__)

# Base directory for SQL databases
SQL_DB_DIR = os.environ.get("SQL_DB_DIR", "/app/data/sql_databases")
try:
    os.makedirs(SQL_DB_DIR, exist_ok=True)
except (PermissionError, OSError):
    # During test collection, directory creation may fail - that's ok
    pass

class SQLTransformer:
    """Handles SQL database creation and querying from files."""
    
    @staticmethod
    async def create_database_from_file(
        file_path: str,
        db_id: str,
        table_name: str = "data",
        file_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a SQLite database from a file."""
        try:
            # Detect file type if not provided
            if not file_type:
                ext = Path(file_path).suffix.lower()
                file_type = ext[1:] if ext else "csv"
            
            # Load data based on file type
            if file_type in ["csv", "tsv"]:
                delimiter = '\t' if file_type == "tsv" else ','
                df = pd.read_csv(file_path, delimiter=delimiter)
            elif file_type in ["xlsx", "xls"]:
                df = pd.read_excel(file_path)
            elif file_type == "json":
                df = pd.read_json(file_path)
            elif file_type == "jsonl":
                df = pd.read_json(file_path, lines=True)
            elif file_type == "parquet":
                df = pd.read_parquet(file_path)
            else:
                return {"error": f"Unsupported file type: {file_type}"}
            
            # Create SQLite database
            db_path = os.path.join(SQL_DB_DIR, f"{db_id}.db")
            conn = sqlite3.connect(db_path)
            
            # Store DataFrame in database
            df.to_sql(table_name, conn, if_exists='replace', index=False)
            
            # Get schema information
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            schema = cursor.fetchall()
            
            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                "success": True,
                "db_id": db_id,
                "db_path": db_path,
                "table_name": table_name,
                "row_count": row_count,
                "column_count": len(df.columns),
                "columns": list(df.columns),
                "schema": [
                    {
                        "cid": col[0],
                        "name": col[1],
                        "type": col[2],
                        "notnull": col[3],
                        "default": col[4],
                        "pk": col[5]
                    }
                    for col in schema
                ]
            }
            
        except Exception as e:
            logger.error(f"Error creating SQL database: {e}", exc_info=True)
            return {"error": str(e)}
    
    @staticmethod
    async def execute_query(
        db_id: str,
        query: str,
        limit: Optional[int] = 100
    ) -> Dict[str, Any]:
        """Execute a SQL query against a database."""
        try:
            db_path = os.path.join(SQL_DB_DIR, f"{db_id}.db")
            if not os.path.exists(db_path):
                return {"error": f"Database {db_id} not found"}
            
            conn = sqlite3.connect(db_path)
            
            # Add LIMIT if not present and it's a SELECT query
            if limit and query.strip().upper().startswith("SELECT") and "LIMIT" not in query.upper():
                query = f"{query.rstrip(';')} LIMIT {limit}"
            
            # Execute query
            cursor = conn.cursor()
            cursor.execute(query)
            
            # Check if it's a SELECT query
            if query.strip().upper().startswith("SELECT"):
                # Fetch results
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                
                # Convert to list of dicts for better JSON representation
                rows = []
                for row in results:
                    rows.append(dict(zip(columns, row)))
                
                result = {
                    "success": True,
                    "query": query,
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "limited": len(rows) == limit if limit else False
                }
            else:
                # For non-SELECT queries (INSERT, UPDATE, DELETE)
                conn.commit()
                result = {
                    "success": True,
                    "query": query,
                    "rows_affected": cursor.rowcount,
                    "type": "modification"
                }
            
            conn.close()
            return result
            
        except Exception as e:
            logger.error(f"Error executing SQL query: {e}", exc_info=True)
            return {"error": str(e)}
    
    @staticmethod
    async def get_database_info(db_id: str) -> Dict[str, Any]:
        """Get information about a database."""
        try:
            db_path = os.path.join(SQL_DB_DIR, f"{db_id}.db")
            if not os.path.exists(db_path):
                return {"error": f"Database {db_id} not found"}
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get list of tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            # Get info for each table
            table_info = {}
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                row_count = cursor.fetchone()[0]
                
                cursor.execute(f"PRAGMA table_info({table})")
                columns = cursor.fetchall()
                
                table_info[table] = {
                    "row_count": row_count,
                    "columns": [col[1] for col in columns],
                    "column_types": {col[1]: col[2] for col in columns}
                }
            
            conn.close()
            
            return {
                "success": True,
                "db_id": db_id,
                "db_path": db_path,
                "tables": tables,
                "table_info": table_info,
                "file_size": os.path.getsize(db_path)
            }
            
        except Exception as e:
            logger.error(f"Error getting database info: {e}", exc_info=True)
            return {"error": str(e)}

async def file_to_sql(
    file_id: str,
    db_name: Optional[str] = None,
    table_name: str = "data",
    visibility: str = "session",
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Convert an uploaded file to a SQL-queryable database.

    Args:
        file_id: The ID of the uploaded file to convert
        db_name: Optional custom name for the database (defaults to file_id)
        table_name: Name for the table in the database (default: "data")
        visibility: Access scope for the created database: 'session' (current session only,
                    default), 'user' (persists across sessions), or 'world' (all users).
        mcp_session_id: Session ID for context
    
    Returns:
        Database creation status and schema information
    """
    try:
        # Get session context
        session_data = await get_session_context(mcp_session_id) if mcp_session_id else {}
        
        # Get file info
        uploaded_files = session_data.get("uploaded_files", {})
        if not uploaded_files:
            uploaded_files = session_data.get("uploaded_csv_files", {})
        
        if file_id not in uploaded_files:
            return json.dumps({
                "error": f"File {file_id} not found. Use ListUploadedFiles to see available files."
            })
        
        file_info = uploaded_files[file_id]
        
        # Determine file path
        base_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        if mcp_session_id:
            file_path = os.path.join(base_dir, "sessions", mcp_session_id, file_id)
        else:
            file_path = os.path.join(base_dir, file_id)
        
        if not os.path.exists(file_path):
            return json.dumps({
                "error": f"File not found at expected path: {file_path}"
            })
        
        # Generate database ID
        db_id = db_name or f"sql_{file_id}"
        
        # Detect file type from extension
        filename = file_info.get("original_filename", "")
        file_type = Path(filename).suffix.lower()[1:] if filename else None
        
        # Create SQL database
        result = await SQLTransformer.create_database_from_file(
            file_path=file_path,
            db_id=db_id,
            table_name=table_name,
            file_type=file_type
        )
        
        # Store database info in session if successful
        if result.get("success") and mcp_session_id:
            if "sql_databases" not in session_data:
                session_data["sql_databases"] = {}
            
            session_data["sql_databases"][db_id] = {
                "file_id": file_id,
                "filename": file_info.get("original_filename", "unknown"),
                "table_name": table_name,
                "created_at": datetime.now().isoformat(),
                "row_count": result.get("row_count", 0),
                "columns": result.get("columns", [])
            }
            
            await update_session_context(mcp_session_id, session_data)
        
        return json.dumps(result, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"Error in file_to_sql: {e}", exc_info=True)
        return json.dumps({"error": str(e)})

async def query_file_sql(
    db_id: str,
    query: str,
    limit: int = 100,
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Execute a SQL query against a file-based database.
    
    Args:
        db_id: The ID of the database to query
        query: The SQL query to execute
        limit: Maximum number of rows to return for SELECT queries (default: 100)
        mcp_session_id: Session ID for context
    
    Returns:
        Query results or execution status
    
    Example queries:
        - SELECT * FROM data WHERE column > 100
        - SELECT COUNT(*) FROM data GROUP BY category
        - UPDATE data SET column = value WHERE condition
    """
    try:
        # Execute the query
        result = await SQLTransformer.execute_query(
            db_id=db_id,
            query=query,
            limit=limit
        )
        
        # Add session context if available
        if mcp_session_id and result.get("success"):
            session_data = await get_session_context(mcp_session_id)
            sql_databases = session_data.get("sql_databases", {})
            
            if db_id in sql_databases:
                result["database_metadata"] = sql_databases[db_id]
        
        return json.dumps(result, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"Error in query_file_sql: {e}", exc_info=True)
        return json.dumps({"error": str(e)})

async def list_sql_databases(
    mcp_session_id: Optional[str] = None
) -> str:
    """
    List all available SQL databases in the current session.
    
    Args:
        mcp_session_id: Session ID for context
    
    Returns:
        List of available databases with metadata
    """
    try:
        result = {"databases": []}
        
        # Get session-specific databases
        if mcp_session_id:
            session_data = await get_session_context(mcp_session_id)
            sql_databases = session_data.get("sql_databases", {})
            
            for db_id, db_info in sql_databases.items():
                db_path = os.path.join(SQL_DB_DIR, f"{db_id}.db")
                result["databases"].append({
                    "db_id": db_id,
                    "exists_on_disk": os.path.exists(db_path),
                    **db_info
                })
        else:
            # List all databases on disk
            if os.path.exists(SQL_DB_DIR):
                for db_file in os.listdir(SQL_DB_DIR):
                    if db_file.endswith(".db"):
                        db_id = db_file[:-3]  # Remove .db extension
                        db_path = os.path.join(SQL_DB_DIR, db_file)
                        
                        # Get basic info
                        info = await SQLTransformer.get_database_info(db_id)
                        if info.get("success"):
                            result["databases"].append({
                                "db_id": db_id,
                                "path": db_path,
                                "tables": info.get("tables", []),
                                "file_size": info.get("file_size", 0)
                            })
        
        result["total_databases"] = len(result["databases"])
        return json.dumps(result, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"Error in list_sql_databases: {e}", exc_info=True)
        return json.dumps({"error": str(e)})

async def get_sql_schema(
    db_id: str,
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Get the schema information for a SQL database.
    
    Args:
        db_id: The ID of the database
        mcp_session_id: Session ID for context
    
    Returns:
        Database schema including tables, columns, and types
    """
    try:
        # Get database info
        result = await SQLTransformer.get_database_info(db_id)
        
        # Add session context if available
        if mcp_session_id and result.get("success"):
            session_data = await get_session_context(mcp_session_id)
            sql_databases = session_data.get("sql_databases", {})
            
            if db_id in sql_databases:
                result["session_metadata"] = sql_databases[db_id]
        
        return json.dumps(result, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"Error in get_sql_schema: {e}", exc_info=True)
        return json.dumps({"error": str(e)})

def register_tools(mcp_instance):
    """Register SQL transformation tools with the MCP server."""
    # Register the tools with the passed-in mcp instance
    mcp_instance.tool()(file_to_sql)
    mcp_instance.tool()(query_file_sql)
    mcp_instance.tool()(list_sql_databases)
    mcp_instance.tool()(get_sql_schema)
    logger.info("SQL transformation tools registered")