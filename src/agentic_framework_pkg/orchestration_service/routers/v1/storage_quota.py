"""
Storage Quota Management Module

This module implements a high water mark system to prevent disk exhaustion from
ephemeral tool outputs and uploaded files. It provides:

- Storage usage tracking with Redis caching
- Pre-write quota validation
- Graduated warning thresholds (4GB warning, 5GB hard limit)
- Background cleanup for expired ephemeral files
- User-facing MCP tool for storage visibility

Architecture:
- File-based storage (no PostgreSQL table needed)
- Redis cache for usage calculations (5-min TTL)
- 7-day TTL on ephemeral files (auto-cleanup)
- Session-isolated storage paths
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional
import redis.asyncio as redis

from ....logger_config import get_logger
from ...redis_client import get_files_redis_client

logger = get_logger(__name__)

# --- Configuration (Environment Variables) ---
DEFAULT_QUOTA_GB = int(os.getenv("STORAGE_QUOTA_GB", "5"))  # 5GB per user
WARNING_THRESHOLD_GB = int(os.getenv("STORAGE_WARNING_GB", "4"))  # 4GB warning
LOW_WATER_MARK_MB = int(
    os.getenv("BROWSER_CACHE_LIMIT_MB", "100")
)  # Browser cache optimization
EPHEMERAL_FILE_TTL_DAYS = int(os.getenv("EPHEMERAL_FILE_TTL_DAYS", "7"))
CLEANUP_INTERVAL_MINUTES = int(os.getenv("CLEANUP_INTERVAL_MINUTES", "5"))

# Shared upload directory
SHARED_UPLOAD_DIR = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")

# Convert to bytes for internal calculations
DEFAULT_QUOTA_BYTES = DEFAULT_QUOTA_GB * 1024 * 1024 * 1024
WARNING_THRESHOLD_BYTES = WARNING_THRESHOLD_GB * 1024 * 1024 * 1024
LOW_WATER_MARK_BYTES = LOW_WATER_MARK_MB * 1024 * 1024


class StorageQuotaExceeded(Exception):
    """Raised when storage quota exceeded."""

    def __init__(self, message: str, current_usage: int, quota_limit: int):
        super().__init__(message)
        self.current_usage = current_usage
        self.quota_limit = quota_limit
        self.current_usage_gb = current_usage / (1024**3)
        self.quota_limit_gb = quota_limit / (1024**3)


async def check_storage_quota(
    session_id: str,
    additional_bytes: int,
    owner_id: Optional[str] = None,
) -> bool:
    """
    Check if write would exceed storage quota.

    Args:
        session_id: Session identifier for storage isolation
        additional_bytes: Size of data to be written
        owner_id: User ID (falls back to session_id if not provided)

    Returns:
        True if write is allowed

    Raises:
        StorageQuotaExceeded: If projected usage exceeds hard limit
    """
    user_id = owner_id or session_id
    current_usage = await get_user_storage_usage(user_id)
    projected_usage = current_usage + additional_bytes

    # Check hard limit
    if projected_usage > DEFAULT_QUOTA_BYTES:
        raise StorageQuotaExceeded(
            f"Storage quota exceeded: {projected_usage / (1024**3):.2f}GB > {DEFAULT_QUOTA_GB}GB",
            current_usage=projected_usage,
            quota_limit=DEFAULT_QUOTA_BYTES,
        )

    # Check warning threshold (only log, don't block)
    if projected_usage > WARNING_THRESHOLD_BYTES and current_usage <= WARNING_THRESHOLD_BYTES:
        await _set_quota_warning(user_id, projected_usage)
        logger.warning(
            f"[STORAGE_WARNING] User {user_id} approaching quota limit: "
            f"{projected_usage / (1024**3):.2f}GB / {DEFAULT_QUOTA_GB}GB "
            f"({(projected_usage / DEFAULT_QUOTA_BYTES) * 100:.1f}%)"
        )

    return True


async def get_user_storage_usage(user_id: str) -> int:
    """
    Calculate total storage usage for a user.
    Results are cached in Redis with 5-minute TTL for performance.

    Args:
        user_id: User identifier

    Returns:
        Total storage usage in bytes
    """
    redis_pool = await get_files_redis_client()
    cache_key = f"storage_quota:{user_id}"

    # Check cache
    cached = await redis_pool.get(cache_key)
    if cached:
        logger.debug(f"[STORAGE_CACHE_HIT] User {user_id}: {int(cached)} bytes")
        return int(cached)

    # Calculate from filesystem
    total_bytes = 0
    locations = [
        Path(SHARED_UPLOAD_DIR) / "sessions" / user_id,
        Path(SHARED_UPLOAD_DIR) / "ephemeral" / user_id,
    ]

    for location in locations:
        if location.exists():
            for file_path in location.rglob("*"):
                if file_path.is_file():
                    try:
                        total_bytes += file_path.stat().st_size
                    except (FileNotFoundError, PermissionError) as e:
                        logger.warning(f"[STORAGE_CALC] Error accessing {file_path}: {e}")
                        continue

    # Cache result (5-minute TTL)
    await redis_pool.set(cache_key, str(total_bytes), ex=300)
    logger.info(
        f"[STORAGE_CALC] User {user_id}: {total_bytes:,} bytes "
        f"({total_bytes / (1024**3):.2f}GB)"
    )

    return total_bytes


async def _set_quota_warning(user_id: str, projected_usage: int) -> None:
    """
    Set a warning flag in Redis when user crosses warning threshold.
    This can be used by frontend to display warnings.

    Args:
        user_id: User identifier
        projected_usage: Projected storage usage in bytes
    """
    redis_pool = await get_files_redis_client()
    warning_key = f"storage_quota_warning:{user_id}"

    warning_data = {
        "timestamp": datetime.now().isoformat(),
        "usage_bytes": projected_usage,
        "usage_gb": round(projected_usage / (1024**3), 2),
        "quota_gb": DEFAULT_QUOTA_GB,
        "usage_percent": round((projected_usage / DEFAULT_QUOTA_BYTES) * 100, 1),
        "message": (
            f"⚠️ Storage usage: {projected_usage / (1024**3):.2f}GB / {DEFAULT_QUOTA_GB}GB "
            f"({(projected_usage / DEFAULT_QUOTA_BYTES) * 100:.1f}%). Consider cleanup."
        ),
    }

    # Store warning with 24-hour TTL
    await redis_pool.set(warning_key, json.dumps(warning_data), ex=86400)


async def get_quota_status(user_id: str) -> Dict[str, any]:
    """
    Get current storage quota status for a user.

    Args:
        user_id: User identifier

    Returns:
        Dictionary with quota status information
    """
    current_bytes = await get_user_storage_usage(user_id)
    current_gb = current_bytes / (1024**3)

    status = (
        "critical"
        if current_gb >= DEFAULT_QUOTA_GB
        else "warning"
        if current_gb >= WARNING_THRESHOLD_GB
        else "healthy"
    )

    # Get ephemeral file count
    ephemeral_dir = Path(SHARED_UPLOAD_DIR) / "ephemeral" / user_id
    ephemeral_files = []
    ephemeral_bytes = 0

    if ephemeral_dir.exists():
        for file_path in ephemeral_dir.rglob("*"):
            if file_path.is_file():
                try:
                    file_size = file_path.stat().st_size
                    ephemeral_files.append(
                        {
                            "path": str(file_path.relative_to(ephemeral_dir)),
                            "size": file_size,
                            "modified": datetime.fromtimestamp(
                                file_path.stat().st_mtime
                            ).isoformat(),
                        }
                    )
                    ephemeral_bytes += file_size
                except (FileNotFoundError, PermissionError):
                    continue

    return {
        "current_usage_gb": round(current_gb, 2),
        "quota_limit_gb": DEFAULT_QUOTA_GB,
        "usage_percent": round((current_gb / DEFAULT_QUOTA_GB) * 100, 1),
        "status": status,
        "remaining_gb": round(DEFAULT_QUOTA_GB - current_gb, 2),
        "ephemeral_files_count": len(ephemeral_files),
        "ephemeral_usage_gb": round(ephemeral_bytes / (1024**3), 2),
        "ephemeral_files": ephemeral_files,
        "warning_threshold_gb": WARNING_THRESHOLD_GB,
        "low_water_mark_mb": LOW_WATER_MARK_MB,
    }


async def cleanup_expired_ephemeral_files() -> Dict[str, int]:
    """
    Background job: Delete ephemeral files older than TTL.

    Returns:
        Dictionary with cleanup statistics
    """
    ephemeral_root = Path(SHARED_UPLOAD_DIR) / "ephemeral"

    if not ephemeral_root.exists():
        logger.debug("[CLEANUP] Ephemeral directory does not exist")
        return {"files_deleted": 0, "bytes_freed": 0}

    files_deleted = 0
    bytes_freed = 0
    cutoff_time = datetime.now() - timedelta(days=EPHEMERAL_FILE_TTL_DAYS)

    for file_path in ephemeral_root.rglob("*"):
        if file_path.is_file():
            try:
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if mtime < cutoff_time:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    files_deleted += 1
                    bytes_freed += file_size
                    logger.debug(
                        f"[CLEANUP] Deleted expired file: {file_path.name} "
                        f"({file_size:,} bytes, modified {mtime.isoformat()})"
                    )
            except (FileNotFoundError, PermissionError) as e:
                logger.warning(f"[CLEANUP] Error deleting {file_path}: {e}")
                continue

    if files_deleted > 0:
        logger.info(
            f"[CLEANUP] Deleted {files_deleted} expired files, "
            f"freed {bytes_freed:,} bytes ({bytes_freed / (1024**2):.2f}MB)"
        )

    # Clean up empty directories
    for dir_path in sorted(ephemeral_root.rglob("*"), reverse=True):
        if dir_path.is_dir() and not any(dir_path.iterdir()):
            try:
                dir_path.rmdir()
                logger.debug(f"[CLEANUP] Removed empty directory: {dir_path}")
            except (FileNotFoundError, PermissionError, OSError):
                continue

    return {"files_deleted": files_deleted, "bytes_freed": bytes_freed}


async def cleanup_session_ephemeral_files(session_id: str) -> Dict[str, int]:
    """
    Delete all ephemeral files for a specific session.
    Used when user explicitly requests cleanup.

    Args:
        session_id: Session identifier

    Returns:
        Dictionary with cleanup statistics
    """
    session_dir = Path(SHARED_UPLOAD_DIR) / "ephemeral" / session_id

    if not session_dir.exists():
        return {"files_deleted": 0, "bytes_freed": 0}

    files_deleted = 0
    bytes_freed = 0

    for file_path in session_dir.rglob("*"):
        if file_path.is_file():
            try:
                file_size = file_path.stat().st_size
                file_path.unlink()
                files_deleted += 1
                bytes_freed += file_size
            except (FileNotFoundError, PermissionError) as e:
                logger.warning(f"[CLEANUP] Error deleting {file_path}: {e}")
                continue

    # Remove empty directory
    try:
        session_dir.rmdir()
    except (FileNotFoundError, PermissionError, OSError):
        pass

    # Invalidate cache
    redis_pool = await get_files_redis_client()
    await redis_pool.delete(f"storage_quota:{session_id}")

    logger.info(
        f"[CLEANUP] Session {session_id}: Deleted {files_deleted} files, "
        f"freed {bytes_freed:,} bytes"
    )

    return {"files_deleted": files_deleted, "bytes_freed": bytes_freed}


# --- Background Task Runner ---
async def storage_cleanup_task():
    """
    Background task that runs periodically to clean up expired ephemeral files.
    """
    logger.info(
        f"[CLEANUP_TASK] Starting background cleanup task "
        f"(interval: {CLEANUP_INTERVAL_MINUTES} minutes, TTL: {EPHEMERAL_FILE_TTL_DAYS} days)"
    )

    while True:
        try:
            result = await cleanup_expired_ephemeral_files()
            if result["files_deleted"] > 0:
                logger.info(
                    f"[CLEANUP_TASK] Completed: {result['files_deleted']} files deleted, "
                    f"{result['bytes_freed']:,} bytes freed"
                )
        except Exception as e:
            logger.error(f"[CLEANUP_TASK] Failed: {e}", exc_info=True)

        # Wait for next interval
        await asyncio.sleep(CLEANUP_INTERVAL_MINUTES * 60)
