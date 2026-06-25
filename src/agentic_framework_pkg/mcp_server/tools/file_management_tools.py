"""
File Management Tools for MCP Server

This module provides tools for managing uploaded files in the MCP server,
including listing, tracking, and organizing files by session.
"""
import os
import json
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime

from fastmcp import FastMCP
import redis.asyncio as redis

from ...logger_config import get_logger
from ..state_manager import get_session_context, update_session_context
from ...orchestration_service.redis_client import get_files_redis_client

logger = get_logger(__name__)


def get_file_key(file_id: str) -> str:
    """Returns the Redis key for a given file ID (consistent with orchestration service)."""
    return f"file_metadata:{file_id}"

async def list_uploaded_files(
    mcp_session_id: Optional[str] = None
) -> str:
    """
    List all files that have been uploaded in the current session.
    
    This tool scans both the session state and the filesystem to ensure
    all uploaded files are discovered and returned.
    
    Args:
        mcp_session_id: Session ID for context
    
    Returns:
        JSON list of uploaded files with their metadata
    """
    try:
        result = {"files": {}, "total_files": 0}
        
        # First, check session state for tracked files
        if mcp_session_id:
            session_data = await get_session_context(mcp_session_id)
            
            # Check multiple possible keys where files might be stored
            for key in ["uploaded_files", "uploaded_csv_files", "processed_files"]:
                if key in session_data:
                    for file_id, file_info in session_data[key].items():
                        if file_id not in result["files"]:
                            result["files"][file_id] = file_info
        
        # Then, scan the filesystem for actual files
        base_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        
        # Check session-specific directory
        if mcp_session_id:
            session_dir = os.path.join(base_dir, "sessions", mcp_session_id)
            if os.path.exists(session_dir):
                for filename in os.listdir(session_dir):
                    file_path = os.path.join(session_dir, filename)
                    if os.path.isfile(file_path):
                        # If file not in result, add it with basic info
                        if filename not in result["files"]:
                            # Try to get original filename from session metadata or use the ID
                            original_name = filename

                            # If we have session data with file info, use that
                            if filename in session_data.get("uploaded_files", {}):
                                file_info = session_data["uploaded_files"][filename]
                                original_name = file_info.get("original_filename", filename)
                            
                            result["files"][filename] = {
                                "file_id": filename,
                                "original_filename": original_name,
                                "size_bytes": os.path.getsize(file_path),
                                "path": file_path,
                                "uploaded_at": datetime.fromtimestamp(
                                    os.path.getmtime(file_path)
                                ).isoformat()
                            }
        
        # Also check the root upload directory for non-session files
        else:
            if os.path.exists(base_dir):
                for filename in os.listdir(base_dir):
                    if filename != "sessions":  # Skip the sessions directory
                        file_path = os.path.join(base_dir, filename)
                        if os.path.isfile(file_path):
                            if filename not in result["files"]:
                                result["files"][filename] = {
                                    "file_id": filename,
                                    "original_filename": filename,
                                    "size_bytes": os.path.getsize(file_path),
                                    "path": file_path,
                                    "uploaded_at": datetime.fromtimestamp(
                                        os.path.getmtime(file_path)
                                    ).isoformat()
                                }
        
        # Redis fallback: if session state and filesystem returned no files,
        # query Redis file_metadata entries filtered by session_id.
        # Handles edge cases where session state was lost (e.g., MCP server
        # restart, session state backend failure, or fork-related ID mismatch).
        if not result["files"] and mcp_session_id:
            try:
                redis_pool = await get_files_redis_client()
                async for key in redis_pool.scan_iter("file_metadata:*"):
                    metadata_json = await redis_pool.get(key)
                    if metadata_json:
                        metadata = json.loads(metadata_json)
                        if metadata.get("session_id") == mcp_session_id:
                            raw_key = key.decode() if isinstance(key, bytes) else key
                            file_id = metadata.get("id", raw_key.split(":", 1)[-1])
                            if file_id not in result["files"]:
                                result["files"][file_id] = {
                                    "file_id": file_id,
                                    "original_filename": metadata.get(
                                        "filename", file_id
                                    ),
                                    "size_bytes": metadata.get("bytes", 0),
                                    "path": metadata.get("current_path", ""),
                                    "uploaded_at": metadata.get(
                                        "upload_timestamp", ""
                                    ),
                                    "owner_id": metadata.get("owner_id"),
                                    "source": "redis_fallback",
                                }
                if result["files"]:
                    logger.info(
                        f"[REDIS_FALLBACK] list_uploaded_files recovered "
                        f"{len(result['files'])} files from Redis for "
                        f"session {mcp_session_id}"
                    )
            except Exception as redis_err:
                logger.warning(
                    f"[REDIS_FALLBACK] Redis query failed: {redis_err}"
                )

        result["total_files"] = len(result["files"])

        # Update session state with discovered files if needed
        if mcp_session_id and result["files"]:
            session_data = await get_session_context(mcp_session_id)
            if "uploaded_files" not in session_data:
                session_data["uploaded_files"] = {}
            
            # Merge discovered files into session state
            for file_id, file_info in result["files"].items():
                if file_id not in session_data["uploaded_files"]:
                    session_data["uploaded_files"][file_id] = file_info
            
            await update_session_context(mcp_session_id, session_data)
        
        return json.dumps(result, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"Error in list_uploaded_files: {e}", exc_info=True)
        return json.dumps({"error": str(e), "files": {}, "total_files": 0})

async def get_file_info(
    file_id: str,
    mcp_session_id: Optional[str] = None
) -> str:
    """
    Get detailed information about a specific uploaded file.
    
    Args:
        file_id: The ID of the file to get info for
        mcp_session_id: Session ID for context
    
    Returns:
        JSON with detailed file information
    """
    try:
        # Determine file path
        base_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        
        if mcp_session_id:
            file_path = os.path.join(base_dir, "sessions", mcp_session_id, file_id)
        else:
            file_path = os.path.join(base_dir, file_id)
        
        if not os.path.exists(file_path):
            return json.dumps({"error": f"File {file_id} not found"})
        
        # Get file stats
        file_stat = os.stat(file_path)
        
        # Get file info from session if available
        session_info = {}
        if mcp_session_id:
            session_data = await get_session_context(mcp_session_id)
            for key in ["uploaded_files", "uploaded_csv_files", "processed_files"]:
                if key in session_data and file_id in session_data[key]:
                    session_info = session_data[key][file_id]
                    break
        
        result = {
            "file_id": file_id,
            "path": file_path,
            "size_bytes": file_stat.st_size,
            "created_at": datetime.fromtimestamp(file_stat.st_ctime).isoformat(),
            "modified_at": datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
            "exists": True,
            **session_info  # Merge any session-stored metadata
        }
        
        return json.dumps(result, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"Error in get_file_info: {e}", exc_info=True)
        return json.dumps({"error": str(e)})

async def discover_files(
    search_pattern: Optional[str] = None,
    session_id: Optional[str] = None,
    include_metadata: bool = False,
    check_all_locations: bool = True
) -> str:
    """
    Discover available files across all sources (session, shared, filesystem).

    This tool helps find files regardless of how they were uploaded or where they're stored.
    It checks multiple locations and can filter by pattern.

    Args:
        search_pattern: Optional filename pattern to search for (e.g., "*.csv", "report*")
        session_id: Optional session to limit search to (None = search all)
        include_metadata: Include detailed file metadata
        check_all_locations: Check session dirs, shared dir, and common paths

    Returns:
        JSON list of discovered files with their locations and metadata
    """
    try:
        discovered = []
        base_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        checked_paths = set()  # Avoid duplicates

        # Helper function to check if file matches pattern
        def matches_pattern(filename: str, pattern: str = None) -> bool:
            if not pattern:
                return True
            # Simple glob-style matching
            import fnmatch
            return fnmatch.fnmatch(filename.lower(), pattern.lower())

        # Strategy 1: Check session-specific directories
        if session_id or check_all_locations:
            session_dirs = []

            if session_id:
                # Check specific session
                session_dirs.extend([
                    os.path.join(base_dir, "sessions", session_id),
                    os.path.join(base_dir, "sessions", f"streamlit_{session_id}")
                ])
            elif check_all_locations:
                # Check all session directories
                sessions_path = os.path.join(base_dir, "sessions")
                if os.path.exists(sessions_path):
                    for session_dir in os.listdir(sessions_path):
                        session_dirs.append(os.path.join(sessions_path, session_dir))

            for session_dir in session_dirs:
                if os.path.exists(session_dir) and os.path.isdir(session_dir):
                    for filename in os.listdir(session_dir):
                        file_path = os.path.join(session_dir, filename)
                        if os.path.isfile(file_path) and file_path not in checked_paths:
                            if matches_pattern(filename, search_pattern):
                                checked_paths.add(file_path)
                                file_info = {
                                    "file_id": filename,
                                    "filename": filename,
                                    "location": "session",
                                    "session_id": os.path.basename(session_dir),
                                    "path": file_path
                                }

                                if include_metadata:
                                    stat = os.stat(file_path)
                                    file_info.update({
                                        "size_bytes": stat.st_size,
                                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                        "created": datetime.fromtimestamp(stat.st_ctime).isoformat()
                                    })

                                discovered.append(file_info)

        # Strategy 2: Check shared directory (non-session files)
        if os.path.exists(base_dir):
            for filename in os.listdir(base_dir):
                file_path = os.path.join(base_dir, filename)
                if os.path.isfile(file_path) and file_path not in checked_paths:
                    if matches_pattern(filename, search_pattern):
                        checked_paths.add(file_path)
                        file_info = {
                            "file_id": filename,
                            "filename": filename,
                            "location": "shared",
                            "path": file_path
                        }

                        if include_metadata:
                            stat = os.stat(file_path)
                            file_info.update({
                                "size_bytes": stat.st_size,
                                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                "created": datetime.fromtimestamp(stat.st_ctime).isoformat()
                            })

                        discovered.append(file_info)

        # Strategy 3: Check common direct paths if pattern suggests it
        if check_all_locations and search_pattern and "/" in search_pattern:
            # User might be looking for a specific path
            direct_path = os.path.join("/app/data", search_pattern)
            if os.path.exists(direct_path) and os.path.isfile(direct_path):
                if direct_path not in checked_paths:
                    checked_paths.add(direct_path)
                    discovered.append({
                        "file_id": os.path.basename(direct_path),
                        "filename": os.path.basename(direct_path),
                        "location": "direct_path",
                        "path": direct_path
                    })

        # Sort by location and filename for consistent output
        discovered.sort(key=lambda x: (x["location"], x["filename"]))

        return json.dumps({
            "discovered_files": discovered,
            "total_found": len(discovered),
            "search_pattern": search_pattern,
            "session_filter": session_id,
            "locations_checked": ["sessions", "shared", "direct"] if check_all_locations else ["specified"],
            "base_directory": base_dir
        }, indent=2)

    except Exception as e:
        logger.error(f"Error in discover_files: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "suggestion": "Check permissions and paths"
        })

async def register_local_file(
    file_path: str,
    mcp_session_id: Optional[str] = None,
    alias: Optional[str] = None,
    copy_to_session: bool = True,
    user_context: Optional[Dict[str, Any]] = None,
    session_hierarchy: Optional[Dict[str, Any]] = None,
    execution_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Register an existing file on the filesystem with the current session.

    This tool allows you to register files that:
    - Were uploaded in different sessions
    - Already exist on the filesystem
    - Need to be accessible in the current session

    Args:
        file_path: Full path to the file on the filesystem (e.g., /app/data/uploaded_files/sessions/old_session/file.pdf)
        mcp_session_id: Session ID to register the file with (uses current session if not provided)
        alias: Optional friendly name/alias for the file (defaults to original filename)
        copy_to_session: If True, copies the file to the current session directory; if False, just registers the reference
        user_context: User context containing user_id, username, and groups (injected by MCPToolWrapper)
        session_hierarchy: Session hierarchy context (injected by MCPToolWrapper)
        execution_context: Execution preferences (injected by MCPToolWrapper)

    Returns:
        JSON with registration status and file details

    Example:
        register_local_file("/app/data/uploaded_files/sessions/old_session/file-abc123.pdf", alias="report.pdf")
    """

    # Extract owner_id from user_context if available
    owner_id = None
    if user_context:
        owner_id = user_context.get("user_id")
        logger.debug(f"RegisterLocalFile: Extracted owner_id={owner_id} from user_context")
    else:
        logger.warning(f"⚠️ RegisterLocalFile: user_context is None! owner_id will be None in Redis metadata")
        logger.debug(f"[DEBUG] session_hierarchy={session_hierarchy}, execution_context={execution_context}")
    try:
        # Verify the source file exists
        if not os.path.exists(file_path):
            return json.dumps({
                "status": "error",
                "message": f"File not found: {file_path}",
                "suggestion": "Check the file path and ensure the file exists"
            })

        # Get file info
        import hashlib as _hashlib
        import re as _re

        file_stats = os.stat(file_path)
        original_filename = os.path.basename(file_path)

        # Always compute content_hash for metadata (SHA256 of first 8192 bytes, 12 hex chars)
        with open(file_path, 'rb') as f:
            content_hash_prefix = _hashlib.sha256(f.read(8192)).hexdigest()[:12]

        # Extract file_id if it follows the standard pattern
        file_id = None
        if original_filename.startswith("file-"):
            file_id = original_filename
        else:
            # Generate a file_id for non-standard files
            safe_name = _re.sub(r'[^a-zA-Z0-9._-]', '_', original_filename.lower())
            file_id = f"file-{content_hash_prefix}-{safe_name}"

        # Use alias if provided, otherwise use original filename
        display_name = alias if alias else original_filename

        # Determine destination path if copying
        destination_path = file_path  # Default to original path

        if copy_to_session and mcp_session_id:
            base_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
            session_dir = os.path.join(base_dir, "sessions", mcp_session_id)

            # Create session directory if it doesn't exist
            os.makedirs(session_dir, exist_ok=True)

            # Destination file path
            destination_path = os.path.join(session_dir, file_id)

            # Copy the file if it's not already in the session directory
            if file_path != destination_path:
                import shutil
                shutil.copy2(file_path, destination_path)
                logger.info(f"Copied file from {file_path} to {destination_path}")

        # Determine storage_type for metadata
        if copy_to_session and (file_path != destination_path):
            storage_type = "session_copy"
        else:
            storage_type = "source_reference"

        # Update session context to register the file
        file_info = {
            "file_id": file_id,
            "original_path": file_path,
            "current_path": destination_path,
            "filename": display_name,
            "size": file_stats.st_size,
            "modified": datetime.fromtimestamp(file_stats.st_mtime).isoformat(),
            "registered_at": datetime.now().isoformat(),
            "copied": copy_to_session and (file_path != destination_path),
            "alias": alias
        }

        # CRITICAL: Also store in Redis file_metadata format (required for GeneratePresignedURL)
        # This ensures compatibility with presigned URL generation and other file operations

        # Determine content_version by checking existing Redis entry
        content_version = 1  # Default for first registration
        try:
            redis_pool_pre = await get_files_redis_client()
            existing_meta_json = await redis_pool_pre.get(get_file_key(file_id))
            if existing_meta_json:
                existing_meta = json.loads(existing_meta_json)
                existing_hash = existing_meta.get("content_hash")  # None for old entries
                existing_version = existing_meta.get("content_version", 0)
                if existing_hash and existing_hash == content_hash_prefix:
                    # Same content — idempotent: keep current version, update last_accessed only
                    content_version = existing_version
                else:
                    # Different content or no prior hash — increment version
                    content_version = existing_version + 1
        except Exception as ver_err:
            logger.warning(f"Could not check existing metadata for versioning: {ver_err}")
            content_version = 1

        file_metadata_for_redis = {
            "id": file_id,
            "object": "file",
            "bytes": file_stats.st_size,
            "created_at": int(file_stats.st_mtime),
            "filename": display_name,
            "purpose": "assistants",  # Default purpose for registered files
            "status": "processed",
            "owner_id": owner_id,  # Extracted from user_context (injected by MCPToolWrapper)
            "session_id": mcp_session_id,
            "upload_timestamp": datetime.now().isoformat(),
            "last_accessed": datetime.now().isoformat(),
            "registered_via": "RegisterLocalFile",  # Track registration method
            "original_path": file_path,
            "current_path": destination_path,
            "storage_type": storage_type,  # "source_reference" or "session_copy"
            "content_hash": content_hash_prefix,  # SHA256 of first 8192 bytes (12 hex chars)
            "content_version": content_version,  # Increments on content change
        }

        logger.debug(f"RegisterLocalFile: Storing Redis metadata with owner_id={owner_id} for file_id={file_id}")

        try:
            # Store in Redis atomically using shared connection pool (prevents race conditions with 4 workers)
            logger.debug(f"[REDIS_DEBUG] Attempting to get Redis client for file_id={file_id}")
            redis_pool = await get_files_redis_client()
            logger.debug(f"[REDIS_DEBUG] Redis client obtained: type={type(redis_pool)}, pool={redis_pool}")

            # Log the exact metadata being stored
            redis_key = get_file_key(file_id)
            metadata_json = json.dumps(file_metadata_for_redis)
            logger.debug(f"[REDIS_DEBUG] Redis key: {redis_key}")
            logger.debug(f"[REDIS_DEBUG] Metadata size: {len(metadata_json)} bytes")
            logger.debug(f"[REDIS_DEBUG] Metadata preview: {metadata_json[:200]}...")

            # Test Redis connection before pipeline
            await redis_pool.ping()
            logger.debug(f"[REDIS_DEBUG] Redis PING successful")

            async with redis_pool.pipeline(transaction=True) as pipe:
                await pipe.set(redis_key, metadata_json)
                result = await pipe.execute()
                logger.debug(f"[REDIS_DEBUG] Pipeline execute result: {result}")

            # Verify the write by reading it back
            stored_value = await redis_pool.get(redis_key)
            if stored_value:
                logger.info(f"✅ Stored and verified file metadata in Redis: {redis_key} ({len(stored_value)} bytes)")
            else:
                logger.error(f"❌ Redis write verification FAILED: key {redis_key} not found after write")
                raise ValueError(f"Redis write verification failed for {redis_key}")

        except Exception as redis_error:
            logger.error(f"❌ CRITICAL: Failed to store file metadata in Redis: {redis_error}", exc_info=True)
            logger.error(f"[REDIS_DEBUG] Error type: {type(redis_error).__name__}")
            logger.error(f"[REDIS_DEBUG] Error details: file_id={file_id}, owner_id={owner_id}, session_id={mcp_session_id}")
            # CRITICAL: Raise error instead of silent failure
            # Without Redis metadata, presigned URLs will fail with "File not found"
            raise RuntimeError(f"Failed to store file metadata in Redis for {file_id}: {redis_error}") from redis_error

        # Register in session state (for backward compatibility)
        if mcp_session_id:
            session_data = await get_session_context(mcp_session_id)

            # Initialize uploaded_files if not present
            if "uploaded_files" not in session_data:
                session_data["uploaded_files"] = {}

            # Register the file
            session_data["uploaded_files"][file_id] = file_info

            # Also add to uploaded_csv_files for backward compatibility if it's a CSV
            if destination_path.lower().endswith('.csv'):
                if "uploaded_csv_files" not in session_data:
                    session_data["uploaded_csv_files"] = {}
                session_data["uploaded_csv_files"][file_id] = {
                    "file_path": destination_path,
                    "original_name": display_name
                }

            # Update the session
            await update_session_context(mcp_session_id, session_data)
            logger.info(f"Registered file {file_id} in session {mcp_session_id}")

        return json.dumps({
            "status": "success",
            "message": f"File registered successfully",
            "file_id": file_id,
            "display_name": display_name,
            "path": destination_path,
            "size": file_stats.st_size,
            "copied": copy_to_session and (file_path != destination_path),
            "session_id": mcp_session_id,
            "usage_hint": f"You can now use ProcessUploadedFile with file_id='{file_id}' or file_path_on_server='{destination_path}'"
        })

    except Exception as e:
        logger.error(f"Error registering file: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": f"Failed to register file: {str(e)}",
            "file_path": file_path
        })


async def gather_folder_statistics(
    folder_path: str,
    recursive: bool = True,
    max_depth: int = 5,
    file_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Gather statistics about a folder before registration.

    Returns detailed information about folder contents.
    """
    import fnmatch
    from collections import defaultdict

    stats = {
        "total_files": 0,
        "total_folders": 0,
        "total_size_bytes": 0,
        "file_types": defaultdict(int),
        "largest_files": [],
        "depth_distribution": defaultdict(int),
        "files_list": []
    }

    # Default exclude patterns
    if exclude_patterns is None:
        exclude_patterns = ["__pycache__", ".git", ".svn", "node_modules", ".venv", "venv"]

    visited_dirs = set()

    def should_exclude(path: str) -> bool:
        """Check if path should be excluded."""
        for pattern in exclude_patterns:
            if pattern in path:
                return True
        return False

    def match_patterns(filename: str) -> bool:
        """Check if file matches patterns."""
        if not file_patterns:
            return True
        return any(fnmatch.fnmatch(filename, pattern) for pattern in file_patterns)

    # Walk the directory tree
    for root, dirs, files in os.walk(folder_path):
        # Calculate depth
        depth = root[len(folder_path):].count(os.sep)

        # Skip if exceeding max depth
        if recursive and depth >= max_depth:
            dirs[:] = []  # Stop recursion
            continue
        elif not recursive and depth > 0:
            dirs[:] = []  # No recursion
            continue

        # Filter out excluded directories
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d))]

        # Count folders
        if root not in visited_dirs:
            visited_dirs.add(root)
            if root != folder_path:  # Don't count the root folder
                stats["total_folders"] += 1

        # Process files
        for filename in files:
            file_path = os.path.join(root, filename)

            # Skip excluded files
            if should_exclude(file_path):
                continue

            # Check pattern match
            if not match_patterns(filename):
                continue

            try:
                file_stat = os.stat(file_path)
                file_size = file_stat.st_size

                stats["total_files"] += 1
                stats["total_size_bytes"] += file_size
                stats["depth_distribution"][depth] += 1

                # Track file type
                _, ext = os.path.splitext(filename)
                if ext:
                    stats["file_types"][ext.lower().lstrip('.')] += 1

                # Track file info
                file_info = {
                    "path": file_path,
                    "relative_path": os.path.relpath(file_path, folder_path),
                    "size_bytes": file_size,
                    "depth": depth
                }
                stats["files_list"].append(file_info)

                # Track largest files (keep top 10)
                stats["largest_files"].append(file_info)
                stats["largest_files"] = sorted(
                    stats["largest_files"],
                    key=lambda x: x["size_bytes"],
                    reverse=True
                )[:10]

            except Exception as e:
                logger.warning(f"Could not stat file {file_path}: {e}")

    # Convert file_types to regular dict
    stats["file_types"] = dict(stats["file_types"])
    stats["depth_distribution"] = dict(stats["depth_distribution"])

    # Add human-readable size
    stats["total_size_mb"] = round(stats["total_size_bytes"] / (1024 * 1024), 2)

    # Add summary for largest files
    for file_info in stats["largest_files"]:
        file_info["size_mb"] = round(file_info["size_bytes"] / (1024 * 1024), 2)

    return stats


async def register_local_folder(
    folder_path: str,
    mcp_session_id: Optional[str] = None,
    recursive: bool = True,
    max_depth: int = 5,
    file_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    copy_to_session: bool = False,
    gather_stats_only: bool = False,
    user_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Recursively register all files in a folder with the current session.

    This tool allows batch registration of entire folders, perfect for:
    - Registering entire codebases
    - Processing document collections
    - Analyzing data directories

    Args:
        folder_path: Path to the folder to register
        mcp_session_id: Session ID to register files with
        recursive: If True, traverse subdirectories (default: True)
        max_depth: Maximum depth for recursive traversal (default: 5)
        file_patterns: List of file patterns to include (e.g., ["*.py", "*.md"])
        exclude_patterns: List of patterns to exclude (e.g., ["__pycache__", ".git"])
        copy_to_session: If True, copies files to session directory (default: False for folders)
        gather_stats_only: If True, only gather statistics without registering (preview mode)

    Returns:
        JSON with registration results, statistics, and registered file IDs

    Examples:
        # Register all Python files in a project
        register_local_folder("/app/projects/myproject", file_patterns=["*.py"])

        # Preview folder contents without registering
        register_local_folder("/app/data", gather_stats_only=True)

        # Register with exclusions
        register_local_folder("/app/docs", exclude_patterns=["drafts", "*.tmp"])
    """
    try:
        # Verify folder exists
        if not os.path.exists(folder_path):
            return json.dumps({
                "status": "error",
                "message": f"Folder not found: {folder_path}"
            })

        if not os.path.isdir(folder_path):
            return json.dumps({
                "status": "error",
                "message": f"Path is not a directory: {folder_path}"
            })

        # Gather statistics first
        logger.info(f"Gathering statistics for folder: {folder_path}")
        stats = await gather_folder_statistics(
            folder_path=folder_path,
            recursive=recursive,
            max_depth=max_depth,
            file_patterns=file_patterns,
            exclude_patterns=exclude_patterns
        )

        # If stats-only mode, return statistics
        if gather_stats_only:
            return json.dumps({
                "status": "success",
                "mode": "preview",
                "folder_path": folder_path,
                "statistics": stats,
                "message": f"Found {stats['total_files']} files in {stats['total_folders']} folders"
            }, indent=2)

        # Check if we have files to register
        if stats["total_files"] == 0:
            return json.dumps({
                "status": "warning",
                "message": "No files found matching criteria",
                "folder_path": folder_path,
                "filters": {
                    "patterns": file_patterns,
                    "exclude": exclude_patterns
                }
            })

        # Warning for large folders
        if stats["total_files"] > 100:
            logger.warning(f"Registering large folder with {stats['total_files']} files")

        # Register files with progress tracking
        registered_files = []
        failed_files = []

        logger.info(f"Starting registration of {stats['total_files']} files")

        for i, file_info in enumerate(stats["files_list"]):
            file_path = file_info["path"]

            try:
                # Register individual file
                result = await register_local_file(
                    file_path=file_path,
                    mcp_session_id=mcp_session_id,
                    alias=file_info["relative_path"],
                    copy_to_session=copy_to_session,
                    user_context=user_context,
                )

                result_data = json.loads(result)

                if result_data.get("status") == "success":
                    registered_files.append({
                        "file_id": result_data["file_id"],
                        "path": file_info["relative_path"],
                        "size_bytes": file_info["size_bytes"]
                    })
                else:
                    failed_files.append({
                        "path": file_info["relative_path"],
                        "error": result_data.get("message", "Unknown error")
                    })

                # Log progress every 10 files
                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i + 1}/{stats['total_files']} files registered")

            except Exception as e:
                logger.error(f"Failed to register {file_path}: {e}")
                failed_files.append({
                    "path": file_info["relative_path"],
                    "error": str(e)
                })

        # Generate folder ID for tracking
        import hashlib
        folder_name = os.path.basename(folder_path.rstrip('/'))
        folder_hash = hashlib.md5(folder_path.encode()).hexdigest()[:8]
        folder_id = f"folder-{folder_hash}-{folder_name}"

        # Update session context with folder registration
        if mcp_session_id:
            session_data = await get_session_context(mcp_session_id)

            if "registered_folders" not in session_data:
                session_data["registered_folders"] = {}

            session_data["registered_folders"][folder_id] = {
                "path": folder_path,
                "stats": {
                    "total_files": stats["total_files"],
                    "total_folders": stats["total_folders"],
                    "total_size_mb": stats["total_size_mb"],
                    "file_types": stats["file_types"]
                },
                "file_ids": [f["file_id"] for f in registered_files],
                "registered_at": datetime.now().isoformat(),
                "options": {
                    "recursive": recursive,
                    "max_depth": max_depth,
                    "patterns": file_patterns,
                    "exclude": exclude_patterns
                }
            }

            await update_session_context(mcp_session_id, session_data)

        # Prepare result
        result = {
            "status": "success",
            "folder_id": folder_id,
            "folder_path": folder_path,
            "statistics": {
                "total_files": stats["total_files"],
                "registered": len(registered_files),
                "failed": len(failed_files),
                "total_size_mb": stats["total_size_mb"],
                "file_types": stats["file_types"]
            },
            "all_file_ids": [f["file_id"] for f in registered_files],  # Complete list for downstream processing
            "registered_files": registered_files[:10],  # First 10 for LLM display preview
            "failed_files": failed_files[:10] if failed_files else []
        }

        if len(registered_files) > 10:
            result["message"] = f"Showing first 10 of {len(registered_files)} registered files"

        if failed_files:
            result["warning"] = f"{len(failed_files)} files failed to register"

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error in register_local_folder: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": f"Failed to register folder: {str(e)}",
            "folder_path": folder_path
        })


async def get_storage_quota(
    user_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Get current storage usage and quota limits for the user.

    This tool provides visibility into storage consumption including:
    - Current usage vs quota limit
    - Warning/critical status
    - Ephemeral file breakdown
    - Cleanup recommendations

    Args:
        user_context: User context containing user_id and session info

    Returns:
        JSON with storage quota status
    """
    try:
        # Import here to avoid circular dependencies
        from ...orchestration_service.routers.v1.storage_quota import get_quota_status

        # Extract user_id from context
        owner_id = user_context.get("user_id") if user_context else "unknown"

        # Get quota status
        quota_status = await get_quota_status(owner_id)

        # Add actionable recommendations based on status
        if quota_status["status"] == "critical":
            quota_status["recommendations"] = [
                "Storage quota exceeded. Immediate cleanup required.",
                "Use CleanupSession tool to remove ephemeral files",
                "Delete unnecessary uploaded files",
                "Contact admin to request quota increase"
            ]
        elif quota_status["status"] == "warning":
            quota_status["recommendations"] = [
                f"Approaching storage limit ({quota_status['usage_percent']}% used)",
                "Consider cleaning up old ephemeral files",
                "Review uploaded files for duplicates"
            ]
        else:
            quota_status["recommendations"] = [
                f"Storage usage is healthy ({quota_status['usage_percent']}% used)",
                f"Ephemeral files auto-delete after 7 days"
            ]

        return json.dumps(quota_status, indent=2)

    except Exception as e:
        logger.error(f"Error in get_storage_quota: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": f"Failed to get storage quota: {str(e)}"
        })


async def cleanup_session_storage(
    mcp_session_id: Optional[str] = None,
    user_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Clean up ephemeral files for the current session.

    This tool deletes all ephemeral files (tool outputs, sandbox plots, etc.)
    for the specified session, freeing up storage quota. Permanent uploaded
    files are NOT affected.

    Args:
        mcp_session_id: Session ID to clean up
        user_context: User context for authorization

    Returns:
        JSON with cleanup statistics
    """
    try:
        if not mcp_session_id:
            return json.dumps({
                "status": "error",
                "message": "Session ID required for cleanup"
            })

        # Import here to avoid circular dependencies
        from ...orchestration_service.routers.v1.storage_quota import cleanup_session_ephemeral_files

        # Perform cleanup
        result = await cleanup_session_ephemeral_files(mcp_session_id)

        return json.dumps({
            "status": "success",
            "session_id": mcp_session_id,
            "files_deleted": result["files_deleted"],
            "bytes_freed": result["bytes_freed"],
            "mb_freed": round(result["bytes_freed"] / (1024**2), 2),
            "message": f"Cleaned up {result['files_deleted']} ephemeral files, freed {result['bytes_freed']:,} bytes"
        }, indent=2)

    except Exception as e:
        logger.error(f"Error in cleanup_session_storage: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": f"Failed to cleanup session storage: {str(e)}"
        })


def register_tools(mcp: FastMCP):
    """Register file management tools with the MCP server."""
    mcp.tool()(list_uploaded_files)
    mcp.tool()(get_file_info)
    mcp.tool()(discover_files)
    mcp.tool()(register_local_file)
    mcp.tool()(register_local_folder)
    mcp.tool()(get_storage_quota)
    mcp.tool()(cleanup_session_storage)
    logger.info("File management tools registered (including discovery, registration, folder tools, and storage quota).")