"""
Shared File Path Resolver

Provides a reusable `resolve_file_path()` function that resolves a file's
filesystem path using a priority chain:

  1. file_info dict (session state) — current_path / original_path fields
  2. Redis file_metadata:{file_id} — current_path / original_path fields
  3. Reconstructed session path — {SHARED_UPLOAD_DIR}/sessions/{session_id}/{file_id}
  4. Shared directory fallback — {SHARED_UPLOAD_DIR}/{file_id}

This eliminates duplicated path-reconstruction logic across file_processor_tool,
rag_processing_tool, and any future consumers.

Precedent: nginx_file_proxy/app.py:136-147 already reads `current_path` from
Redis with fallback to path reconstruction.
"""

import os
import json
from typing import Dict, Any, Optional, Tuple, List

from ...logger_config import get_logger
from ...orchestration_service.redis_client import get_files_redis_client
from .file_management_tools import get_file_key

logger = get_logger(__name__)


async def resolve_file_path(
    file_id: str,
    mcp_session_id: Optional[str] = None,
    file_info: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], List[str]]:
    """
    Resolve a file's filesystem path using a priority chain.

    Args:
        file_id: The file identifier (e.g. "file-abc123-script.py")
        mcp_session_id: Current MCP session ID (for legacy path reconstruction)
        file_info: Optional dict from session state with path fields

    Returns:
        Tuple of (resolved_path_or_None, list_of_paths_checked)
    """
    base_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
    paths_checked: List[str] = []

    # --- Priority 1: file_info dict (session state) ---
    if file_info:
        for key in ("current_path", "original_path"):
            path = file_info.get(key)
            if path:
                paths_checked.append(f"file_info.{key}={path}")
                if os.path.exists(path):
                    logger.info(
                        f"File {file_id} resolved via file_info.{key}: {path}"
                    )
                    return path, paths_checked

    # --- Priority 2: Redis file_metadata:{file_id} ---
    try:
        redis_pool = await get_files_redis_client()
        redis_key = get_file_key(file_id)
        metadata_json = await redis_pool.get(redis_key)

        if metadata_json:
            metadata = json.loads(metadata_json)
            for key in ("current_path", "original_path"):
                path = metadata.get(key)
                if path:
                    paths_checked.append(f"redis.{key}={path}")
                    if os.path.exists(path):
                        logger.info(
                            f"File {file_id} resolved via Redis {key}: {path}"
                        )
                        return path, paths_checked
    except Exception as e:
        logger.warning(
            f"Redis lookup failed for {file_id}, falling back to path reconstruction: {e}"
        )

    # --- Priority 3: Reconstructed session path ---
    if mcp_session_id:
        session_path = os.path.join(
            base_dir, "sessions", mcp_session_id, file_id
        )
        paths_checked.append(session_path)
        if os.path.exists(session_path):
            logger.info(
                f"File {file_id} resolved via session path: {session_path}"
            )
            return session_path, paths_checked

        # Try streamlit session format variant
        if mcp_session_id.startswith("streamlit_"):
            pass  # Already checked exact session match above
        else:
            alt_session_path = os.path.join(
                base_dir, "sessions", f"streamlit_{mcp_session_id}", file_id
            )
            paths_checked.append(alt_session_path)
            if os.path.exists(alt_session_path):
                logger.info(
                    f"File {file_id} resolved via alt session path: {alt_session_path}"
                )
                return alt_session_path, paths_checked

    # --- Priority 4: Shared directory fallback ---
    shared_path = os.path.join(base_dir, file_id)
    paths_checked.append(shared_path)
    if os.path.exists(shared_path):
        logger.info(
            f"File {file_id} resolved via shared dir: {shared_path}"
        )
        return shared_path, paths_checked

    # Not found
    logger.warning(
        f"File {file_id} not found. Checked {len(paths_checked)} locations: {paths_checked}"
    )
    return None, paths_checked
