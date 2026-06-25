"""
Batch File Operations Tools

Provides batch processing capabilities for files:
- ProcessFilesBatch: Process multiple files in parallel with concurrency control
- CreateRAGIndexFromFolder: Complete folder→RAG workflow (register→process→index)

Architectural Role:
- **Tier 3 (Executor):** Batch orchestration of existing file operations
- **Stateless:** Uses session context for isolation, no local state
- **Error Resilient:** Failed individual files don't break entire batch
"""

import asyncio
import json
import time
from typing import Dict, Any, List, Optional, Literal
from collections import defaultdict
from datetime import datetime

from ..server import mcp
from ...logger_config import get_logger
from .file_processor_tool import process_file_advanced
from .file_management_tools import register_local_folder
from .rag_processing_tool import create_rag_index

logger = get_logger(__name__)


# ============================================================================
# CORE BUSINESS LOGIC (Testable Implementation Functions)
# ============================================================================


async def _process_files_batch_impl(
    file_ids: List[str],
    processing_type: Literal["auto", "rag", "sql", "dataframe", "text"] = "auto",
    chunk_size: int = 5,
    visibility: str = "session",
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Core implementation for batch file processing.

    This function contains the actual business logic and is directly testable
    without MCP decorator interference.

    See process_files_batch() docstring for full parameter documentation.
    """
    try:
        start_time = time.time()

        if not file_ids:
            return json.dumps({
                "status": "error",
                "message": "No file IDs provided",
                "total_files": 0,
                "processed": 0,
                "failed": 0
            })

        # Validate chunk_size
        if chunk_size < 1:
            chunk_size = 1
        elif chunk_size > 10:
            logger.warning(f"chunk_size={chunk_size} exceeds recommended max of 10, clamping to 10")
            chunk_size = 10

        logger.info(f"Starting batch processing of {len(file_ids)} files with concurrency={chunk_size}")

        # Use asyncio.Semaphore for concurrency control
        semaphore = asyncio.Semaphore(chunk_size)
        results = []
        processed_count = 0
        failed_count = 0

        async def process_single_file(file_id: str, index: int) -> Dict[str, Any]:
            """Process a single file with semaphore-controlled concurrency."""
            async with semaphore:
                try:
                    if processing_type == "sql":
                        from .sql_transformation_tool import file_to_sql
                        result_json = await file_to_sql(
                            file_id=file_id,
                            visibility=visibility,
                            mcp_session_id=mcp_session_id
                        )
                    else:
                        # Existing path: auto/rag/dataframe/text
                        result_json = await process_file_advanced(
                            file_id=file_id,
                            processing_type=processing_type,
                            mcp_session_id=mcp_session_id
                        )
                    result_data = json.loads(result_json)

                    # Check if processing succeeded
                    if "error" in result_data:
                        return {
                            "file_id": file_id,
                            "status": "failed",
                            "error": result_data["error"]
                        }

                    # Extract key metrics from result
                    metrics = {
                        "file_id": file_id,
                        "status": "processed",
                        "filename": result_data.get("filename"),
                        "processing_type": result_data.get("processing_type")
                    }

                    # Add type-specific metrics
                    if "rag" in result_data:
                        rag_data = result_data["rag"]
                        metrics["chunks"] = len(rag_data.get("chunks", []))
                        metrics["total_tokens"] = rag_data.get("total_tokens", 0)
                    elif "dataframe" in result_data:
                        df_data = result_data["dataframe"]
                        metrics["rows"] = df_data.get("shape", [0])[0]
                        metrics["columns"] = df_data.get("shape", [0])[1] if len(df_data.get("shape", [])) > 1 else 0
                    elif "text" in result_data:
                        text_data = result_data["text"]
                        metrics["char_count"] = text_data.get("char_count", 0)

                    # Log progress every 10 files
                    if (index + 1) % 10 == 0:
                        logger.info(f"Progress: {index + 1}/{len(file_ids)} files processed")

                    return metrics

                except Exception as e:
                    logger.error(f"Failed to process file {file_id}: {e}", exc_info=True)
                    return {
                        "file_id": file_id,
                        "status": "failed",
                        "error": str(e)
                    }

        # Process all files in parallel with concurrency control
        results = await asyncio.gather(*[
            process_single_file(file_id, idx)
            for idx, file_id in enumerate(file_ids)
        ])

        # Count successes and failures
        processed_count = sum(1 for r in results if r["status"] == "processed")
        failed_count = sum(1 for r in results if r["status"] == "failed")

        # Calculate summary statistics
        summary = {
            "total_chunks": sum(r.get("chunks", 0) for r in results if r["status"] == "processed"),
            "total_tokens": sum(r.get("total_tokens", 0) for r in results if r["status"] == "processed"),
            "file_types": {}
        }

        # Aggregate file types
        file_type_counts = defaultdict(int)
        for result in results:
            if result["status"] == "processed" and "filename" in result:
                # Extract extension
                filename = result["filename"]
                ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
                file_type_counts[ext] += 1

        summary["file_types"] = dict(file_type_counts)

        processing_time = time.time() - start_time

        # Determine overall status
        if failed_count == 0:
            status = "success"
        elif processed_count > 0:
            status = "partial_success"
        else:
            status = "error"

        logger.info(
            f"Batch processing complete: {processed_count}/{len(file_ids)} succeeded, "
            f"{failed_count} failed in {processing_time:.2f}s"
        )

        return json.dumps({
            "status": status,
            "total_files": len(file_ids),
            "processed": processed_count,
            "failed": failed_count,
            "processing_time_seconds": round(processing_time, 2),
            "results": results,
            "summary": summary
        }, indent=2)

    except Exception as e:
        logger.error(f"Error in _process_files_batch_impl: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "error": str(e),
            "total_files": len(file_ids) if file_ids else 0,
            "processed": 0,
            "failed": len(file_ids) if file_ids else 0
        })


async def _create_rag_index_from_folder_impl(
    folder_path: str,
    index_name: Optional[str] = None,
    file_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    recursive: bool = True,
    processing_type: Literal["auto", "rag"] = "rag",
    chunk_size_files: int = 5,
    chunk_size_text: int = 1000,
    chunk_overlap: int = 200,
    visibility: str = "session",
    copy_to_session: bool = False,
    timeout_seconds: int = 600,
    user_context: Optional[Dict[str, Any]] = None,
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Core implementation for folder-to-RAG workflow.

    This function contains the actual business logic and is directly testable
    without MCP decorator interference.

    See create_rag_index_from_folder() docstring for full parameter documentation.
    """
    try:
        workflow_start = time.time()
        logger.info(f"Starting folder→RAG workflow for: {folder_path}")

        # Step 1: Register folder
        logger.info("Step 1/3: Registering folder files")
        register_result = await register_local_folder(
            folder_path=folder_path,
            file_patterns=file_patterns,
            exclude_patterns=exclude_patterns,
            recursive=recursive,
            copy_to_session=copy_to_session,
            user_context=user_context,
            mcp_session_id=mcp_session_id,
        )

        register_data = json.loads(register_result)

        # Check registration status
        if register_data.get("status") not in ["success", "warning"]:
            return json.dumps({
                "status": "error",
                "message": f"Folder registration failed: {register_data.get('message')}",
                "folder_path": folder_path
            }, indent=2)

        # Extract file_ids — use complete all_file_ids list, falling back to
        # registered_files preview for backward compatibility (Session 57 Bug 3 fix)
        all_file_ids = register_data.get("all_file_ids")
        if all_file_ids:
            file_ids = all_file_ids
            logger.info(f"Using all_file_ids: {len(file_ids)} files from folder")
        else:
            # Backward compatibility: extract from preview (may be truncated to 10)
            registered_files = register_data.get("registered_files", [])
            if not registered_files:
                return json.dumps({
                    "status": "error",
                    "message": "No files found or registered in folder",
                    "folder_path": folder_path,
                    "filters": {
                        "patterns": file_patterns,
                        "exclude": exclude_patterns
                    }
                }, indent=2)
            file_ids = [f["file_id"] for f in registered_files]
            logger.warning(
                f"all_file_ids not available, using registered_files preview: "
                f"{len(file_ids)} files (may be truncated)"
            )

        # Step 2: Process files in batch
        logger.info("Step 2/3: Processing files for RAG")
        process_result = await _process_files_batch_impl(
            file_ids=file_ids,
            processing_type=processing_type,
            chunk_size=chunk_size_files,
            mcp_session_id=mcp_session_id
        )

        process_data = json.loads(process_result)

        # Check processing status
        if process_data.get("status") == "error":
            # Extract meaningful error from individual results when top-level 'error' is absent
            error_detail = process_data.get("error")
            if not error_detail:
                failed_results = [
                    r for r in process_data.get("results", [])
                    if r.get("status") == "failed"
                ]
                if failed_results:
                    error_detail = (
                        f"{len(failed_results)} files failed: "
                        f"{failed_results[0].get('error', 'unknown')}"
                    )
                else:
                    error_detail = "Unknown processing error"
            return json.dumps({
                "status": "error",
                "message": f"File processing failed: {error_detail}",
                "folder_path": folder_path,
                "registered_files": len(file_ids)
            }, indent=2)

        # Get successful file_ids for indexing
        successful_results = [
            r for r in process_data.get("results", [])
            if r.get("status") == "processed"
        ]
        successful_file_ids = [r["file_id"] for r in successful_results]

        if not successful_file_ids:
            return json.dumps({
                "status": "error",
                "message": "No files were successfully processed",
                "folder_path": folder_path,
                "registered_files": len(file_ids),
                "processing_failures": process_data.get("failed", 0)
            }, indent=2)

        logger.info(f"Processed {len(successful_file_ids)}/{len(file_ids)} files successfully")

        # Step 3: Create RAG index
        logger.info(f"Step 3/3: Creating RAG index (timeout={timeout_seconds}s)")
        try:
            rag_result = await asyncio.wait_for(
                create_rag_index(
                    file_ids=successful_file_ids,
                    index_name=index_name,
                    chunk_size=chunk_size_text,
                    chunk_overlap=chunk_overlap,
                    mcp_session_id=mcp_session_id
                ),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            workflow_time = time.time() - workflow_start
            return json.dumps({
                "status": "error",
                "message": f"RAG index creation timed out after {timeout_seconds}s",
                "folder_path": folder_path,
                "processed_files": len(successful_file_ids),
                "workflow_time_seconds": round(workflow_time, 2)
            }, indent=2)

        rag_data = json.loads(rag_result)

        # Check RAG creation status
        if "error" in rag_data:
            return json.dumps({
                "status": "error",
                "message": f"RAG index creation failed: {rag_data['error']}",
                "folder_path": folder_path,
                "registered_files": len(file_ids),
                "processed_files": len(successful_file_ids)
            }, indent=2)

        # Consolidate workflow results
        workflow_time = time.time() - workflow_start

        # Collect failed file details
        failed_results = [
            r for r in process_data.get("results", [])
            if r.get("status") == "failed"
        ]
        failed_details = [
            {
                "file_id": r["file_id"],
                "reason": r.get("error", "Unknown error")
            }
            for r in failed_results
        ]

        # Determine overall status
        if len(failed_results) == 0:
            status = "success"
        else:
            status = "partial_success"

        index_id = rag_data.get("index_id")
        final_index_name = rag_data.get("index_name", index_name)

        logger.info(
            f"Folder→RAG workflow complete: index_id={index_id}, "
            f"{len(successful_file_ids)}/{len(file_ids)} files indexed in {workflow_time:.2f}s"
        )

        return json.dumps({
            "status": status,
            "index_id": index_id,
            "index_name": final_index_name,
            "folder_path": folder_path,
            "total_files_found": len(file_ids),
            "registered_files": len(file_ids),
            "processed_files": len(successful_file_ids),
            "failed_files": len(failed_results),
            "indexed_files": len(successful_file_ids),
            "total_chunks": process_data.get("summary", {}).get("total_chunks", 0),
            "vector_store": rag_data.get("vector_store", "chromadb"),
            "workflow_time_seconds": round(workflow_time, 2),
            "query_hint": f"Use query_rag_index(index_id='{index_id}', query='your question here') to search this index",
            "failed_details": failed_details if failed_details else None
        }, indent=2)

    except Exception as e:
        logger.error(f"Error in _create_rag_index_from_folder_impl: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "error": str(e),
            "folder_path": folder_path
        })


# ============================================================================
# MCP TOOL DECORATORS (Thin Wrappers for Tool Registration)
# ============================================================================


@mcp.tool()
async def process_files_batch(
    file_ids: List[str],
    processing_type: Literal["auto", "rag", "sql", "dataframe", "text"] = "auto",
    chunk_size: int = 5,
    visibility: str = "session",
    timeout_seconds: int = 300,
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Process multiple files in parallel with concurrency control and error handling.

    This tool enables efficient batch processing of large file collections:
    - Parallel processing with configurable concurrency limit
    - Progress tracking (logs every 10 files)
    - Error collection (failed files don't break entire batch)
    - Automatic recovery and detailed reporting

    Args:
        file_ids: List of file IDs to process (from register_local_file or register_local_folder)
        processing_type: Type of processing to apply to all files:
            - auto: Automatically detect and apply appropriate processing
            - rag: Prepare for RAG indexing (chunk text for embeddings)
            - sql: Convert to SQL-queryable format (for structured data)
            - dataframe: Load as pandas DataFrame for analysis
            - text: Extract and return text content
        chunk_size: Number of files to process concurrently (default: 5, max: 10 recommended)
        visibility: Access scope for created indexes/databases: 'session' (current session only,
            default), 'user' (persists across sessions for this user), or 'world' (accessible
            to all authenticated users).
        timeout_seconds: Maximum execution time in seconds (default: 300).
            Increase for large batches (e.g., 600 for 50+ files, 900 for 100+ files).
        mcp_session_id: Session ID for context isolation

    Returns:
        JSON with batch processing results including:
        - status: "success" or "partial_success" (some failures)
        - total_files: Number of files in batch
        - processed: Number successfully processed
        - failed: Number that failed
        - processing_time_seconds: Total time taken
        - results: List of per-file results with status and details
        - summary: Aggregated statistics (chunks, tokens, file types)

    Examples:
        # Process all files from folder registration
        register_result = register_local_folder("/app/data/documents")
        file_ids = [f["file_id"] for f in register_result["registered_files"]]
        process_files_batch(file_ids, processing_type="rag")

        # Process with custom concurrency and extended timeout
        process_files_batch(file_ids, chunk_size=10, timeout_seconds=600)

        # Text extraction for many files
        process_files_batch(file_ids, processing_type="text")
    """
    return await _process_files_batch_impl(
        file_ids=file_ids,
        processing_type=processing_type,
        chunk_size=chunk_size,
        visibility=visibility,
        mcp_session_id=mcp_session_id
    )


@mcp.tool()
async def create_rag_index_from_folder(
    folder_path: str,
    index_name: Optional[str] = None,
    file_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    recursive: bool = True,
    processing_type: Literal["auto", "rag"] = "rag",
    chunk_size_files: int = 5,
    chunk_size_text: int = 1000,
    chunk_overlap: int = 200,
    visibility: str = "session",
    copy_to_session: bool = False,
    timeout_seconds: int = 600,
    user_context: Optional[Dict[str, Any]] = None,
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Create a RAG index from a folder in one command (register→process→index).

    This high-level workflow tool simplifies the common pattern of:
    1. Registering all files in a folder
    2. Processing them for RAG (text chunking, embeddings prep)
    3. Creating a queryable RAG index

    Perfect for:
    - Indexing entire codebases for semantic code search
    - Processing document collections for question answering
    - Batch analysis of research papers or reports

    Args:
        folder_path: Path to the folder to index
        index_name: Optional custom name for the index (auto-generated if not provided)
        file_patterns: List of file patterns to include (e.g., ["*.py", "*.md"])
        exclude_patterns: List of patterns to exclude (e.g., ["__pycache__", ".git"])
        recursive: If True, traverse subdirectories (default: True)
        processing_type: Type of processing ("auto" or "rag", default: "rag")
        chunk_size_files: Number of files to process concurrently (default: 5)
        chunk_size_text: Size of text chunks for RAG indexing (default: 1000)
        chunk_overlap: Overlap between text chunks (default: 200)
        visibility: Access scope for the created RAG index: 'session' (current session only,
            default), 'user' (persists across sessions for this user), or 'world' (accessible
            to all authenticated users).
        copy_to_session: If True, copies source files into the current session directory.
            If False (default), registers references to files at their original location
            (saves disk space, but files must remain accessible).
        timeout_seconds: Maximum execution time in seconds (default: 600).
            This 3-step workflow (register→process→index) needs longer timeouts
            for large folders. Increase to 900-1200 for 100+ files.
        user_context: User context containing user_id, username, and groups (injected by framework)
        mcp_session_id: Session ID for context isolation

    Returns:
        JSON with complete workflow results including:
        - status: "success" or "partial_success"
        - index_id: Generated RAG index ID
        - index_name: Name of the created index
        - folder_path: Source folder path
        - total_files_found: Files discovered during registration
        - registered_files: Files successfully registered
        - processed_files: Files successfully processed
        - failed_files: Number of failures
        - indexed_files: Files included in final index
        - total_chunks: Total text chunks in index
        - vector_store: Backend used (chromadb or ragflow)
        - query_hint: Example query command
        - failed_details: List of failures with reasons

    Examples:
        # Index all Python files in a project
        create_rag_index_from_folder(
            folder_path="/app/projects/myproject",
            file_patterns=["*.py"],
            index_name="myproject_code"
        )

        # Index large documentation with extended timeout
        create_rag_index_from_folder(
            folder_path="/app/docs",
            file_patterns=["*.md", "*.rst"],
            chunk_size_text=500,
            chunk_overlap=100,
            timeout_seconds=900
        )

        # Index with exclusions
        create_rag_index_from_folder(
            folder_path="/app/data",
            exclude_patterns=["*.tmp", "drafts", "__pycache__"]
        )
    """
    return await _create_rag_index_from_folder_impl(
        folder_path=folder_path,
        index_name=index_name,
        file_patterns=file_patterns,
        exclude_patterns=exclude_patterns,
        recursive=recursive,
        processing_type=processing_type,
        chunk_size_files=chunk_size_files,
        chunk_size_text=chunk_size_text,
        chunk_overlap=chunk_overlap,
        visibility=visibility,
        copy_to_session=copy_to_session,
        timeout_seconds=timeout_seconds,
        user_context=user_context,
        mcp_session_id=mcp_session_id,
    )


def register_tools(mcp_instance):
    """
    Register batch file operation tools with the MCP server.

    This function is called by main.py during server initialization.
    """
    logger.info("Batch file operation tools registered (process_files_batch, create_rag_index_from_folder)")
