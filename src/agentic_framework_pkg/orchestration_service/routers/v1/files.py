"""
This module provides the implementation for the OpenAI-compatible `/v1/files` API endpoints
for the Orchestration Service. It handles the business logic for file uploads,
metadata storage in Redis, and retrieval from the shared volume.
"""

import os
import uuid
import json
import time
import shutil
import hashlib
import re
from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
    Depends,
    Request,
    Path,
    Query,
    Body,
    Header,
)
from fastapi.responses import JSONResponse, FileResponse, Response, StreamingResponse
import httpx
import redis.asyncio as redis
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from ...auth import get_forwarded_user
from ....core.auth import AuthCredentials
from ....logger_config import get_logger
from ...session_manager import (
    get_session_context,
    update_session_context,
    create_session_if_not_exists,
)
from ...redis_client import get_files_redis_client
from .storage_quota import check_storage_quota, StorageQuotaExceeded

router = APIRouter()
logger = get_logger(__name__)

# --- Shared File Storage Configuration ---
SHARED_UPLOAD_DIR = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
try:
    os.makedirs(SHARED_UPLOAD_DIR, exist_ok=True)
except (PermissionError, OSError):
    # During test collection, directory creation may fail - that's ok
    pass


# --- Pydantic Models for Presigned URLs ---
class GeneratePresignedURLRequest(BaseModel):
    """Request to generate a presigned URL for file download."""

    expiry_seconds: Optional[int] = Field(
        default=None,
        ge=1,  # Minimum 1 second (allow short expiry for testing)
        le=86400,  # Maximum 24 hours
        description="Time-to-live in seconds (default: 3600 = 1 hour)",
    )
    disposition: Optional[str] = Field(
        default=None,
        description='Content-Disposition type: "inline" (browser display) or "attachment" (download). '
        "Defaults to 'inline' for images/SVG/PDF, 'attachment' for other files.",
    )


class GeneratePresignedURLResponse(BaseModel):
    """Response containing presigned URL and metadata."""

    presigned_url: str = Field(description="Full presigned download URL")
    expires_at: int = Field(description="Unix timestamp when URL expires")
    expires_in: int = Field(description="Seconds until expiration")
    file_id: str = Field(description="File UUID")


def get_file_key(file_id: str) -> str:
    """Returns the Redis key for a given file ID."""
    return f"file_metadata:{file_id}"


def generate_stable_file_id(file_content: bytes, filename: str) -> str:
    """
    Generate deterministic file ID based on content hash and filename.
    This ensures the same file gets the same ID across multiple uploads.

    Args:
        file_content: The raw bytes of the file
        filename: Original filename from upload

    Returns:
        Deterministic file ID in format: file-{hash_prefix}-{sanitized_name}
    """
    # Calculate SHA-256 hash of content (first 12 chars for ID)
    content_hash = hashlib.sha256(file_content).hexdigest()[:12]

    # Sanitize filename - remove special chars, lowercase, limit length
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", filename.lower())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")

    # Limit filename part to prevent overly long IDs
    max_name_length = 50
    if len(sanitized) > max_name_length:
        # Keep extension if present
        parts = sanitized.rsplit(".", 1)
        if len(parts) == 2 and len(parts[1]) <= 10:  # Has reasonable extension
            name_part = parts[0][: max_name_length - len(parts[1]) - 1] + "." + parts[1]
        else:
            name_part = sanitized[:max_name_length]
    else:
        name_part = sanitized

    return f"file-{content_hash}-{name_part}"


async def find_file_by_content_hash(
    content_hash_prefix: str, session_id: Optional[str] = None
) -> Optional[Dict]:
    """
    Find existing file metadata by content hash prefix.

    Args:
        content_hash_prefix: First 12 chars of SHA-256 hash
        session_id: Optional session ID to limit search

    Returns:
        File metadata if found, None otherwise
    """
    try:
        redis_pool = await get_files_redis_client()
        # Scan Redis for files with matching hash
        async for key in redis_pool.scan_iter("file_metadata:*"):
            metadata_json = await redis_pool.get(key)
            if metadata_json:
                metadata = json.loads(metadata_json)
                # Check hash match and optionally session match
                if metadata.get("content_hash", "").startswith(content_hash_prefix):
                    if not session_id or metadata.get("session_id") == session_id:
                        return metadata
    except Exception as e:
        logger.error(f"Error searching for file by hash: {e}")
    return None


async def register_ephemeral_tool_output(
    tool_name: str,
    content: str,
    session_id: str,
    owner_id: Optional[str] = None,
) -> str:
    """
    Save large tool output to ephemeral file and register with Redis.

    This function implements the file-only storage architecture for large
    tool outputs (>50k chars). Files are:
    - Saved to /ephemeral/{session_id}/ directory
    - Registered in Redis with 7-day TTL
    - NOT included in LLM context window
    - Accessible via ReadFile or GeneratePresignedURL tools

    Args:
        tool_name: Name of the tool that generated output
        content: Tool output content (string)
        session_id: Session identifier for isolation
        owner_id: User ID for quota tracking

    Returns:
        file_id for retrieval via ReadFile or GeneratePresignedURL

    Raises:
        StorageQuotaExceeded: If quota limit exceeded
    """
    # Generate deterministic file_id
    content_bytes = content.encode('utf-8')
    content_hash = hashlib.sha256(content_bytes).hexdigest()[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_tool_name = re.sub(r'[^a-zA-Z0-9_-]', '_', tool_name.lower())
    file_id = f"file-{content_hash}-{safe_tool_name}_{timestamp}.txt"

    # Ephemeral storage path
    ephemeral_dir = os.path.join(SHARED_UPLOAD_DIR, "ephemeral", session_id)
    os.makedirs(ephemeral_dir, exist_ok=True)
    file_path = os.path.join(ephemeral_dir, file_id)

    # Check high water mark BEFORE writing
    try:
        await check_storage_quota(
            session_id=session_id,
            additional_bytes=len(content_bytes),
            owner_id=owner_id
        )
    except StorageQuotaExceeded as e:
        logger.error(
            f"[EPHEMERAL_STORAGE] Quota exceeded for {owner_id or session_id}: {e}"
        )
        raise

    # Write file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    logger.info(
        f"[EPHEMERAL_STORAGE] Saved tool output: {file_id} "
        f"({len(content):,} chars, {len(content_bytes):,} bytes)"
    )

    # Register in Redis (7-day TTL)
    redis_pool = await get_files_redis_client()
    file_metadata = {
        "id": file_id,
        "file_id": file_id,
        "current_path": file_path,
        "filename": f"{safe_tool_name}_output.txt",
        "bytes": len(content_bytes),
        "size": len(content_bytes),
        "owner_id": owner_id,
        "session_id": session_id,
        "storage_tier": "ephemeral",  # NEW FIELD
        "ttl_days": 7,
        "source": "tool_output",
        "tool_name": tool_name,
        "content_hash": hashlib.sha256(content_bytes).hexdigest(),
        "created_at": int(time.time()),
        "upload_timestamp": datetime.now().isoformat(),
        "object": "file",
        "purpose": "tool_output",
        "status": "processed"
    }

    await redis_pool.set(
        f"file_metadata:{file_id}",
        json.dumps(file_metadata),
        ex=7 * 24 * 60 * 60  # 7-day expiration
    )

    logger.info(
        f"[EPHEMERAL_STORAGE] Registered {file_id} in Redis with 7-day TTL"
    )

    return file_id


async def update_session_with_uploaded_file(
    session_id: str, file_id: str, filename: str
):
    """Update session context to track an uploaded file."""
    try:
        # Ensure session exists
        await create_session_if_not_exists(session_id, None)

        # Get current session context
        session_data = await get_session_context(session_id)

        # Initialize uploaded files tracking if not present
        # Use generic 'uploaded_files' key for all file types
        if "uploaded_files" not in session_data:
            session_data["uploaded_files"] = {}

        # Backward compatibility: Also add to uploaded_csv_files for legacy tools
        if "uploaded_csv_files" not in session_data:
            session_data["uploaded_csv_files"] = {}

        # Add file to session context
        file_info = {
            "original_filename": filename,
            "file_id": file_id,
            "upload_timestamp": time.time(),
        }

        # Store in both keys for compatibility
        session_data["uploaded_files"][file_id] = file_info
        session_data["uploaded_csv_files"][file_id] = file_info

        # Update session context
        await update_session_context(session_id, session_data)

        logger.info(
            f"Added file '{filename}' (ID: {file_id}) to session {session_id} context"
        )

    except Exception as e:
        logger.error(
            f"Failed to update session {session_id} with uploaded file: {e}",
            exc_info=True,
        )
        # Don't raise - file upload should still succeed even if session update fails


async def remove_file_from_session(session_id: str, file_id: str):
    """Remove file from session context when deleted."""
    try:
        # Get current session context
        session_data = await get_session_context(session_id)

        # Remove file from session context if present
        if (
            "uploaded_files" in session_data
            and file_id in session_data["uploaded_files"]
        ):
            del session_data["uploaded_files"][file_id]

        # Also remove from legacy key
        if (
            "uploaded_csv_files" in session_data
            and file_id in session_data["uploaded_csv_files"]
        ):
            del session_data["uploaded_csv_files"][file_id]

            # Update session context
            await update_session_context(session_id, session_data)

            logger.info(f"Removed file '{file_id}' from session {session_id} context")

    except Exception as e:
        logger.error(
            f"Failed to remove file {file_id} from session {session_id}: {e}",
            exc_info=True,
        )
        # Don't raise - file deletion should still succeed even if session update fails


class FileRegistrationRequest(BaseModel):
    file_metadata: Dict
    file_path: str


@router.post("/")
async def upload_file(
    file: UploadFile = File(...),
    purpose: str = Form(...),
    user: AuthCredentials = Depends(get_forwarded_user),
    session_id: Optional[str] = Form(None),
):
    # Read file content first to generate stable ID
    file_content = await file.read()

    # Generate deterministic file ID based on content and name
    file_id = generate_stable_file_id(file_content, file.filename)
    full_content_hash = hashlib.sha256(file_content).hexdigest()

    # Log the file ID generation
    logger.info(
        f"Generated stable file ID: {file_id} for file: {file.filename} (hash: {full_content_hash[:12]})"
    )

    # Determine storage location based on session context
    if session_id:
        # Session-aware storage: store in session-specific directory
        session_dir = os.path.join(SHARED_UPLOAD_DIR, "sessions", session_id)
        os.makedirs(session_dir, exist_ok=True)
        file_location = os.path.join(session_dir, file_id)
        logger.info(f"Storing file in session directory: {file_location}")
    else:
        # Default storage: store in shared directory
        file_location = os.path.join(SHARED_UPLOAD_DIR, file_id)
        logger.info(f"Storing file in shared directory: {file_location}")

    try:
        # Check storage quota BEFORE writing file
        owner_id = user.user_id if user else session_id
        try:
            await check_storage_quota(
                session_id=session_id or "unknown",
                additional_bytes=len(file_content),
                owner_id=owner_id
            )
        except StorageQuotaExceeded as e:
            logger.warning(f"Storage quota exceeded for user {owner_id}: {e}")
            raise HTTPException(
                status_code=507,  # HTTP 507 Insufficient Storage
                detail={
                    "error": "storage_quota_exceeded",
                    "message": str(e),
                    "current_usage_gb": round(e.current_usage_gb, 2),
                    "quota_limit_gb": round(e.quota_limit_gb, 2),
                    "file_size_mb": round(len(file_content) / (1024**2), 2),
                    "recommendations": [
                        "Use GetStorageQuota tool to see detailed usage",
                        "Clean up old ephemeral files with CleanupSession tool",
                        "Delete unnecessary uploaded files",
                        "Contact admin to request quota increase"
                    ]
                }
            )

        # Check if file already exists (same content uploaded before)
        if os.path.exists(file_location):
            logger.info(
                f"File {file_id} already exists at {file_location}, updating metadata only"
            )
            file_size = os.path.getsize(file_location)
        else:
            # Write the file content (already read above)
            with open(file_location, "wb") as f:
                f.write(file_content)
            file_size = len(file_content)
            logger.info(f"Saved new file {file_id} to {file_location}")

        file_metadata = {
            "id": file_id,
            "object": "file",
            "bytes": file_size,
            "created_at": int(time.time()),
            "filename": file.filename,
            "purpose": purpose,
            "status": "processed",
            "owner_id": user.user_id if user else None,
            "session_id": session_id,  # Track which session this file belongs to
            "content_hash": full_content_hash,  # Full SHA-256 hash for verification
            "upload_timestamp": datetime.now().isoformat(),  # ISO timestamp for tracking
            "last_accessed": datetime.now().isoformat(),
            "storage_type": "uploaded",  # File uploaded via REST API /v1/files endpoint
        }

        # Store file metadata and hash mapping atomically (prevents race conditions with 4 workers)
        redis_pool = await get_files_redis_client()
        async with redis_pool.pipeline(transaction=True) as pipe:
            await pipe.set(get_file_key(file_id), json.dumps(file_metadata))
            # Store content hash mapping for deduplication
            hash_key = f"file_hash:{full_content_hash[:12]}"
            await pipe.set(hash_key, file_id)
            await pipe.execute()

        # If session-based upload, update session context to track the file
        if session_id:
            await update_session_with_uploaded_file(session_id, file_id, file.filename)

        logger.info(
            f"File '{file.filename}' uploaded to {file_location} by user '{user.username if user else 'unknown'}'."
        )
        return JSONResponse(content=file_metadata, status_code=201)
    except Exception as e:
        logger.error(f"Failed to upload file: {e}", exc_info=True)
        if os.path.exists(file_location):
            os.remove(file_location)
        raise HTTPException(status_code=500, detail="Failed to upload file. Please try again.")


@router.get("")
async def list_files(
    purpose: Optional[str] = None, user: AuthCredentials = Depends(get_forwarded_user)
):
    file_list = []
    user_id = user.user_id if user else None

    redis_pool = await get_files_redis_client()
    async for key in redis_pool.scan_iter("file_metadata:*"):
        metadata_json = await redis_pool.get(key)
        if metadata_json:
            metadata = json.loads(metadata_json)

            # Ownership check
            if user_id and metadata.get("owner_id") != user_id:
                continue

            # Purpose check
            if purpose and metadata.get("purpose") != purpose:
                continue

            file_list.append(metadata)

    return {"object": "list", "data": file_list}


@router.get("/{file_id}")
async def retrieve_file(
    file_id: str, user: AuthCredentials = Depends(get_forwarded_user)
):
    redis_pool = await get_files_redis_client()
    metadata_json = await redis_pool.get(get_file_key(file_id))
    if not metadata_json:
        raise HTTPException(status_code=404, detail="File not found.")
    metadata = json.loads(metadata_json)
    if user and metadata.get("owner_id") != user.user_id:
        raise HTTPException(status_code=403, detail="Permission denied.")
    return JSONResponse(content=metadata)


@router.get("/{file_id}/content")
async def retrieve_file_content(
    file_id: str, user: AuthCredentials = Depends(get_forwarded_user)
):
    redis_pool = await get_files_redis_client()
    metadata_json = await redis_pool.get(get_file_key(file_id))
    if not metadata_json:
        raise HTTPException(status_code=404, detail="File not found.")
    metadata = json.loads(metadata_json)
    if user and metadata.get("owner_id") != user.user_id:
        raise HTTPException(status_code=403, detail="Permission denied.")

    # Check session-based storage first, then fall back to shared storage
    session_id = metadata.get("session_id")
    if session_id:
        file_location = os.path.join(SHARED_UPLOAD_DIR, "sessions", session_id, file_id)
    else:
        file_location = os.path.join(SHARED_UPLOAD_DIR, file_id)

    if not os.path.exists(file_location):
        raise HTTPException(status_code=404, detail="File content not found on server.")
    return FileResponse(
        path=file_location,
        filename=metadata.get("filename"),
        media_type="application/octet-stream",
    )


@router.delete("/{file_id}")
async def delete_file(
    file_id: str, user: AuthCredentials = Depends(get_forwarded_user)
):
    redis_pool = await get_files_redis_client()
    metadata_json = await redis_pool.get(get_file_key(file_id))
    if not metadata_json:
        raise HTTPException(status_code=404, detail="File not found.")
    metadata = json.loads(metadata_json)
    if user and metadata.get("owner_id") != user.user_id:
        raise HTTPException(status_code=403, detail="Permission denied.")

    # Check session-based storage first, then fall back to shared storage
    session_id = metadata.get("session_id")
    if session_id:
        file_location = os.path.join(SHARED_UPLOAD_DIR, "sessions", session_id, file_id)
    else:
        file_location = os.path.join(SHARED_UPLOAD_DIR, file_id)

    try:
        if os.path.exists(file_location):
            os.remove(file_location)
        await redis_pool.delete(get_file_key(file_id))

        # If session-based file, also remove from session context
        if session_id:
            await remove_file_from_session(session_id, file_id)

        logger.info(
            f"File {file_id} deleted by user '{user.username if user else 'unknown'}'."
        )
        return {"id": file_id, "object": "file.deleted", "deleted": True}
    except Exception as e:
        logger.error(f"Failed to delete file {file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete file. Please try again.")


@router.post("/internal/register")
async def register_generated_file(
    request: FileRegistrationRequest, req: Request = None
):
    """
    Internal endpoint for registering files generated by sandbox or other services.

    This endpoint allows internal services (like sandbox_mcp_server) to register
    files that were generated during execution, making them discoverable via
    the standard /v1/files endpoints.

    Note: This is an internal endpoint and should not be exposed to end users.
    """
    try:
        file_metadata = request.file_metadata
        source_file_path = request.file_path

        # Extract session from metadata or headers
        x_session_id = req.headers.get("X-Session-ID") if req else None
        session_id = file_metadata.get("mcp_session_id") or x_session_id

        # Validate the source file exists
        if not os.path.exists(source_file_path):
            raise HTTPException(status_code=400, detail="Source file does not exist")

        file_id = file_metadata.get("id")
        if not file_id:
            raise HTTPException(status_code=400, detail="File ID is required")

        # Generated files should be accessible to the user who owns the workflow,
        # not isolated to the MCP execution session. Store in shared directory
        # so they appear in the user's file listings.
        target_file_path = os.path.join(SHARED_UPLOAD_DIR, file_id)
        logger.info(
            f"Registering generated file in shared directory: {target_file_path}"
        )

        # Copy the file to the standard location if it's not already there
        if os.path.abspath(source_file_path) != os.path.abspath(target_file_path):
            shutil.copy2(source_file_path, target_file_path)
            logger.info(
                f"Copied generated file from {source_file_path} to {target_file_path}"
            )

        # Keep MCP session info in metadata for traceability, but don't use it for storage isolation
        if session_id:
            file_metadata["mcp_session_id"] = session_id

        # Store metadata in Redis atomically (prevents race conditions with 4 workers)
        redis_pool = await get_files_redis_client()
        async with redis_pool.pipeline(transaction=True) as pipe:
            await pipe.set(get_file_key(file_id), json.dumps(file_metadata))
            await pipe.execute()

        logger.info(
            f"Generated file '{file_metadata.get('filename')}' registered and accessible to user {file_metadata.get('owner_id')}"
        )

        logger.info(
            f"Registered generated file '{file_metadata.get('filename')}' with ID {file_id}"
        )

        return JSONResponse(content=file_metadata, status_code=201)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to register generated file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to register file. Please try again.")


class RegisterLocalFileRequest(BaseModel):
    """Request model for registering local files."""

    file_path: str
    session_id: Optional[str] = None
    alias: Optional[str] = None
    copy_to_session: bool = True


@router.post("/register-local")
async def register_local_file(
    request: RegisterLocalFileRequest,
    user: AuthCredentials = Depends(get_forwarded_user),
    req: Request = None,
):
    """
    Register an existing file from the filesystem with the current session.

    This endpoint allows users to register files that:
    - Were uploaded in different sessions
    - Already exist on the filesystem
    - Need to be accessible in the current session

    Args:
        request: Registration request with file path and options
        user: User credentials from authentication
        req: HTTP request for extracting session info

    Returns:
        Registration response with file_id and details
    """
    try:
        file_path = request.file_path
        session_id = request.session_id
        alias = request.alias
        copy_to_session = request.copy_to_session

        # Extract session from headers if not provided
        if not session_id:
            session_id = req.headers.get("X-Session-ID") if req else None
            if not session_id:
                # Generate a session ID if none provided
                session_id = f"user_{user.user_id}_{int(time.time())}"

        # Validate the source file exists
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Source file not found at the specified path.")

        # Get file info
        file_stats = os.stat(file_path)
        original_filename = os.path.basename(file_path)

        # Extract file_id if it follows the standard pattern
        file_id = None
        if original_filename.startswith("file-"):
            file_id = original_filename
        else:
            # Generate a file_id for non-standard files
            with open(file_path, "rb") as f:
                # Read first 8KB for hash to avoid loading entire file
                content_sample = f.read(8192)
                content_hash = hashlib.sha256(content_sample).hexdigest()[:12]
            safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", original_filename.lower())
            file_id = f"file-{content_hash}-{safe_name}"

        # Use alias if provided, otherwise use original filename
        display_name = alias if alias else original_filename

        # Determine destination path if copying
        destination_path = file_path  # Default to original path

        if copy_to_session and session_id:
            session_dir = os.path.join(SHARED_UPLOAD_DIR, "sessions", session_id)

            # Create session directory if it doesn't exist
            os.makedirs(session_dir, exist_ok=True)

            # Destination file path
            destination_path = os.path.join(session_dir, file_id)

            # Copy the file if it's not already in the session directory
            if os.path.abspath(file_path) != os.path.abspath(destination_path):
                shutil.copy2(file_path, destination_path)
                logger.info(f"Copied file from {file_path} to {destination_path}")

        # Prepare file metadata
        file_metadata = {
            "id": file_id,
            "object": "file",
            "purpose": "assistants",
            "filename": display_name,
            "original_path": file_path,
            "current_path": destination_path,
            "bytes": file_stats.st_size,
            "created_at": int(file_stats.st_mtime),
            "registered_at": int(time.time()),
            "owner_id": user.user_id if user else None,
            "uploaded_by": user.username if user else "unknown",
            "session_id": session_id,
            "copied": copy_to_session and (file_path != destination_path),
            "alias": alias,
        }

        # Store metadata in Redis atomically (prevents race conditions with 4 workers)
        redis_pool = await get_files_redis_client()
        async with redis_pool.pipeline(transaction=True) as pipe:
            await pipe.set(get_file_key(file_id), json.dumps(file_metadata))
            await pipe.execute()

        # Update session context if session_id provided
        if session_id:
            await update_session_with_uploaded_file(session_id, file_id, display_name)

        logger.info(
            f"Registered local file {file_id} from {file_path} for user '{user.username if user else 'unknown'}'"
        )

        return {
            "status": "success",
            "message": "File registered successfully",
            "file_id": file_id,
            "display_name": display_name,
            "path": destination_path,
            "size": file_stats.st_size,
            "copied": copy_to_session and (file_path != destination_path),
            "session_id": session_id,
            "usage_hint": f"You can now use ProcessUploadedFile with file_id='{file_id}' or file_path_on_server='{destination_path}'",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to register local file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to register file. Please try again.")


@router.post(
    "/{file_id}/signed",
    response_model=GeneratePresignedURLResponse,
    summary="Generate Presigned URL",
    description="Generate a time-limited, HMAC-signed URL for file download without authentication",
)
async def generate_presigned_url(
    file_id: str = Path(..., description="File UUID"),
    request_body: GeneratePresignedURLRequest = Body(...),
    user_id: str = Header(..., alias="X-User-ID"),
    username: str = Header(..., alias="X-User-Username"),
    request: Request = None,
) -> GeneratePresignedURLResponse:
    """Generate presigned URL for file download.

    Security:
    - Requires JWT authentication (enforced by Agent Gateway)
    - User must own the file
    - Token is HMAC-signed and time-limited
    - Token cannot be tampered with or reused after expiration

    Access Patterns:
    - Pattern 1 (External): https://api.agentic.local/v1/files/{id}/signed
    - Pattern 2 (Direct): http://localhost:8081/v1/files/{id}/signed
    - Pattern 3 (Forwarded): http://localhost:8443/v1/files/{id}/signed

    Uses RequestContext for hostname resolution (consistent with agent-based flow).
    """
    from ...security.presigned_url import get_presigned_url_manager
    from ...request_context import RequestContext

    # Extract request context for hostname resolution (Option B - Phase 3)
    request_ctx = RequestContext.from_request(request)

    logger.info(
        f"Generating presigned URL: file_id={file_id}, user_id={user_id}, "
        f"username={username}, expiry={request_body.expiry_seconds}s, "
        f"forwarded_host={request_ctx.forwarded_host}"
    )

    # Validate file exists and retrieve metadata
    redis_pool = await get_files_redis_client()
    file_key = get_file_key(file_id)
    file_metadata_json = await redis_pool.get(file_key)

    if not file_metadata_json:
        logger.warning(f"File not found: file_id={file_id}")
        raise HTTPException(status_code=404, detail="File not found")

    try:
        file_metadata = json.loads(file_metadata_json)
    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to parse file metadata: file_id={file_id}, error={e}"
        )
        raise HTTPException(
            status_code=500, detail="File metadata is corrupted"
        )

    # Verify user owns the file
    # CRITICAL: Must use "owner_id" to match field name from upload_file (line 287)
    file_owner_id = file_metadata.get("owner_id")

    if not file_owner_id:
        logger.error(
            f"File metadata missing owner_id field: file_id={file_id}, "
            f"metadata_keys={list(file_metadata.keys())}"
        )
        raise HTTPException(
            status_code=500,
            detail="File metadata is missing ownership information"
        )

    if file_owner_id != user_id:
        logger.warning(
            f"Unauthorized access attempt: file_id={file_id}, "
            f"owner={file_owner_id}, requester={user_id}"
        )
        raise HTTPException(
            status_code=403, detail="You do not have permission to access this file"
        )

    # Generate HMAC token
    manager = get_presigned_url_manager()
    token, expires_ts = manager.generate_token(
        file_id=file_id, user_id=user_id, expiry_seconds=request_body.expiry_seconds
    )

    # Construct presigned URL using RequestContext (consistent with agent-based flow)
    # Use forwarded_host from request context if available, otherwise fallback
    forwarded_host = request_ctx.forwarded_host or "agent_gateway:8081"

    # Determine scheme based on hostname
    scheme = "https" if "api.agentic.local" in forwarded_host else "http"

    # Handle port in URL (if non-standard port is specified)
    if request_ctx.forwarded_port and request_ctx.forwarded_port not in ("80", "443"):
        base_url = f"{forwarded_host}:{request_ctx.forwarded_port}" if ":" not in forwarded_host else forwarded_host
    else:
        base_url = forwarded_host

    presigned_url = f"{scheme}://{base_url}/v1/files/{file_id}/download?token={token}&expires={expires_ts}"

    current_ts = int(time.time())
    expires_in = expires_ts - current_ts

    logger.info(
        f"Generated presigned URL: file_id={file_id}, expires_in={expires_in}s, "
        f"url={presigned_url[:80]}..., scheme={scheme}, base_url={base_url}"
    )

    return GeneratePresignedURLResponse(
        presigned_url=presigned_url,
        expires_at=expires_ts,
        expires_in=expires_in,
        file_id=file_id,
    )


async def _relay_remote_file(
    remote_url: str,
    filename: str,
    file_id: str,
    content_type: str,
    content_disposition: str,
    remote_source: str = "unknown",
) -> StreamingResponse:
    """
    Relay a file from a remote source (e.g., EMSL sandbox) to the client.

    Fetches the file via HTTP from the remote URL (accessible through SSH tunnel)
    and streams it to the user's browser. Used for files with storage_type="remote".

    Sends X-Sandbox-Token header for authentication with the remote nginx /files/
    endpoint. Token is configured via EMSL_SANDBOX_FILES_TOKEN env var.

    Returns 502 if the remote returns non-200, 503 if the remote is unreachable.
    """
    logger.info(
        f"[REMOTE_RELAY] Relaying file: id={file_id}, source={remote_source}, url={remote_url}"
    )

    # Build request headers — include shared secret for /files/ endpoint auth
    request_headers = {}
    sandbox_token = os.getenv("EMSL_SANDBOX_FILES_TOKEN", "")
    if sandbox_token:
        request_headers["X-Sandbox-Token"] = sandbox_token

    # Determine SSL verification for remote file relay:
    #   1. EMSL_SANDBOX_CA_CERT set + file exists → verify against that CA
    #   2. EMSL_SANDBOX_SSL_VERIFY=false → disable verification (escape hatch)
    #   3. Otherwise → default system verification (True)
    _emsl_ca_cert = os.getenv("EMSL_SANDBOX_CA_CERT", "")
    if _emsl_ca_cert and os.path.exists(_emsl_ca_cert):
        _ssl_verify = _emsl_ca_cert
    elif os.getenv("EMSL_SANDBOX_SSL_VERIFY", "true").lower() == "false":
        _ssl_verify = False
    else:
        _ssl_verify = True

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0),
            verify=_ssl_verify,
        ) as client:
            response = await client.send(
                client.build_request("GET", remote_url, headers=request_headers),
                stream=True,
            )

            if response.status_code != 200:
                await response.aclose()
                logger.error(
                    f"[REMOTE_RELAY] Remote returned {response.status_code}: "
                    f"file_id={file_id}, url={remote_url}"
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"Remote file source returned {response.status_code}",
                )

            async def stream_content():
                try:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        yield chunk
                finally:
                    await response.aclose()

            return StreamingResponse(
                stream_content(),
                media_type=content_type,
                headers={
                    "Content-Disposition": content_disposition,
                    "X-Remote-Source": remote_source,
                },
            )

    except httpx.ConnectError as e:
        logger.error(
            f"[REMOTE_RELAY] Cannot reach remote source: file_id={file_id}, "
            f"url={remote_url}, error={e}"
        )
        raise HTTPException(
            status_code=503,
            detail="Remote file source is unreachable (tunnel may be down)",
        )
    except httpx.TimeoutException as e:
        logger.error(
            f"[REMOTE_RELAY] Timeout fetching remote file: file_id={file_id}, "
            f"url={remote_url}, error={e}"
        )
        raise HTTPException(
            status_code=504,
            detail="Timeout fetching file from remote source",
        )


@router.get(
    "/{file_id}/download",
    summary="Download File (Presigned URL) [DEPRECATED]",
    description="""
    **DEPRECATED**: This endpoint is deprecated in favor of direct nginx_file_proxy routing.

    For new integrations, use presigned URLs that route directly to nginx_file_proxy.
    This endpoint remains available as a fallback for backwards compatibility.

    **Deprecation Timeline**:
    - 2026-01-26: Marked deprecated
    - 2026-04-26: Will log deprecation warnings
    - 2026-07-26: May be removed (6-month notice)

    **Migration**: Update clients to use presigned URLs with `api.agentic.local` FQDN,
    which automatically routes to nginx_file_proxy for optimal performance.
    """,
    deprecated=True,
    responses={
        200: {"description": "File content (via X-Accel-Redirect or direct stream)"},
        401: {"description": "Invalid, expired, or tampered token"},
        404: {"description": "File not found"},
    },
)
async def download_file_with_presigned_url(
    file_id: str = Path(..., description="File UUID"),
    token: str = Query(..., description="HMAC-signed token"),
    expires: int = Query(..., description="Expiration timestamp"),
    request: Request = None,
):
    """
    Download file using presigned URL (DEPRECATED).

    **DEPRECATION NOTICE**: Use nginx_file_proxy routing instead.
    This endpoint remains as a fallback for backwards compatibility.

    Security:
    - NO JWT authentication required (token embedded in URL)
    - HMAC-SHA256 signature validation
    - Expiration enforcement
    - Constant-time comparison (timing attack prevention)

    Performance:
    - Uses Nginx X-Accel-Redirect when accessed via proxy (kernel-level serving)
    - Falls back to direct streaming for direct port access

    Access Patterns:
    - Pattern 1 (External): https://api.agentic.local/v1/files/{id}/download?token=...&expires=...
    - Pattern 2 (Direct): http://localhost:8081/v1/files/{id}/download?token=...&expires=...
    - Pattern 3 (Forwarded): http://localhost:8443/v1/files/{id}/download?token=...&expires=...
    """
    from ...security.presigned_url import get_presigned_url_manager

    # DEPRECATION WARNING: Log when this deprecated endpoint is called
    logger.warning(
        f"[DEPRECATED] Orchestration service file download called for file_id={file_id}. "
        f"Clients should migrate to nginx_file_proxy routing for better performance."
    )

    logger.info(
        f"Presigned URL download request: file_id={file_id}, expires={expires}, "
        f"token={token[:20]}..."
    )

    # Retrieve file metadata from Redis
    redis_pool = await get_files_redis_client()
    file_key = get_file_key(file_id)
    file_metadata_json = await redis_pool.get(file_key)

    if not file_metadata_json:
        logger.warning(f"File not found: file_id={file_id}")
        raise HTTPException(status_code=404, detail="File not found")

    try:
        file_metadata = json.loads(file_metadata_json)
    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to parse file metadata: file_id={file_id}, error={e}"
        )
        raise HTTPException(
            status_code=500, detail="File metadata is corrupted"
        )

    # Validate HMAC token
    # CRITICAL: Must use "owner_id" to match field name from upload_file (line 287)
    file_owner_id = file_metadata.get("owner_id")

    if not file_owner_id:
        logger.error(
            f"File metadata missing owner_id field: file_id={file_id}, "
            f"metadata_keys={list(file_metadata.keys())}"
        )
        raise HTTPException(
            status_code=500,
            detail="File metadata is missing ownership information"
        )

    manager = get_presigned_url_manager()
    is_valid, error_msg = manager.validate_token(
        file_id=file_id,
        user_id=file_owner_id,
        token=token,
        expires_ts=expires,
    )

    if not is_valid:
        logger.warning(
            f"Presigned URL validation failed: file_id={file_id}, error={error_msg}"
        )
        raise HTTPException(status_code=401, detail=error_msg)

    # Remote file relay: files stored on EMSL sandbox are fetched on demand
    storage_type = file_metadata.get("storage_type", "uploaded")
    if storage_type == "remote":
        remote_url = file_metadata.get("remote_url")
        if not remote_url:
            raise HTTPException(
                status_code=500,
                detail="Remote file metadata missing remote_url",
            )
        filename = file_metadata.get("filename", file_id)
        file_ext = os.path.splitext(filename)[1].lower()
        mime_types = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".svg": "image/svg+xml", ".pdf": "application/pdf",
            ".csv": "text/csv", ".json": "application/json", ".txt": "text/plain",
        }
        content_type = mime_types.get(file_ext, "application/octet-stream")
        embeddable_extensions = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"}
        disposition_type = "inline" if file_ext in embeddable_extensions else "attachment"
        content_disposition = f'{disposition_type}; filename="{filename}"'

        return await _relay_remote_file(
            remote_url=remote_url,
            filename=filename,
            file_id=file_id,
            content_type=content_type,
            content_disposition=content_disposition,
            remote_source=file_metadata.get("remote_source", "unknown"),
        )

    # Get file path - must match upload logic (lines 254-263)
    session_id = file_metadata.get("session_id")

    if session_id:
        # Session-aware storage: SHARED_UPLOAD_DIR/sessions/{session_id}/{file_id}
        file_path = os.path.join(SHARED_UPLOAD_DIR, "sessions", session_id, file_id)
    else:
        # Default storage: SHARED_UPLOAD_DIR/{file_id}
        file_path = os.path.join(SHARED_UPLOAD_DIR, file_id)

    if not os.path.exists(file_path):
        logger.error(
            f"File exists in metadata but not on disk: file_id={file_id}, "
            f"expected_path={file_path}, session_id={session_id}"
        )
        raise HTTPException(status_code=404, detail="File not found on disk")

    filename = file_metadata.get("filename", file_id)

    # Determine Content-Disposition based on file type (for embedded content support)
    # CRITICAL: 'inline' allows browser embedding (images, SVG, PDF), 'attachment' forces download
    file_ext = os.path.splitext(filename)[1].lower()
    embeddable_extensions = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"}

    # Use inline for embeddable content (Streamlit/OpenWebUI embedding), attachment for others
    disposition_type = "inline" if file_ext in embeddable_extensions else "attachment"
    content_disposition = f'{disposition_type}; filename="{filename}"'

    # Determine MIME type (nginx will override for X-Accel, but set for direct streaming)
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
        ".webp": "image/webp",
        ".gltf": "model/gltf+json",  # 3D visualization support
        ".glb": "model/vnd.gltf.binary",
    }
    content_type = mime_types.get(file_ext, "application/octet-stream")

    # Check if accessed via Nginx proxy (X-Accel-Redirect available)
    # CRITICAL: Only use X-Accel-Redirect for external FQDN (api.agentic.local)
    # Direct port (agent_gateway:8081) and port forwarding (localhost:*) do NOT have NGINX
    forwarded_host = request.headers.get("X-Forwarded-Host", "")
    use_x_accel = forwarded_host and "api.agentic.local" in forwarded_host

    if use_x_accel:
        # Use X-Accel-Redirect for kernel-level file serving (no Python blocking)
        # Internal path must match actual file storage structure
        if session_id:
            internal_path = f"/internal-files/sessions/{session_id}/{file_id}"
        else:
            internal_path = f"/internal-files/{file_id}"

        logger.info(
            f"Using X-Accel-Redirect: file_id={file_id}, internal_path={internal_path}, "
            f"disposition={disposition_type}, content_type={content_type}"
        )

        headers = {
            "X-Accel-Redirect": internal_path,
            "Content-Disposition": content_disposition,  # inline for embeddable, attachment for others
            "Content-Type": content_type,  # proper MIME type for browser rendering
        }
        return Response(content=b"", headers=headers, status_code=200)
    else:
        # Direct port access - stream file directly
        logger.info(
            f"Streaming file directly: file_id={file_id}, path={file_path}, "
            f"disposition={disposition_type}, content_type={content_type}"
        )

        def file_iterator():
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk

        return StreamingResponse(
            file_iterator(),
            media_type=content_type,  # proper MIME type for browser rendering
            headers={
                "Content-Disposition": content_disposition
            },  # inline for embeddable
        )
