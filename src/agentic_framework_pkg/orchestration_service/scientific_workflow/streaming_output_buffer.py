"""
Streaming Output Buffer for Large Tool Outputs

This module implements mid-stream file redirection when tool outputs exceed
size thresholds. Key features:

- Chunk-by-chunk monitoring during tool execution
- Automatic file redirection at 50k char threshold
- Memory-efficient (max 50k chars in buffer before flush)
- Session-isolated ephemeral storage
- Real-time progress tracking

Architecture:
- Buffer stores chunks until threshold reached
- At threshold: flush buffer to file, continue streaming to disk
- Returns either buffered content or file reference
- Integrates with storage quota enforcement

Author: Phase 3 Implementation
Date: 2026-02-04
"""

import os
import asyncio
import json
import hashlib
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Callable, Awaitable, Dict, Any, Union
from ...logger_config import get_logger
from ..redis_client import get_files_redis_client
from ..routers.v1.storage_quota import check_storage_quota

logger = get_logger(__name__)

# Shared upload directory
SHARED_UPLOAD_DIR = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")


class StreamingOutputBuffer:
    """
    Buffer tool output during streaming execution.
    Automatically redirects to file if size exceeds threshold.

    Example Usage:
        buffer = StreamingOutputBuffer(
            tool_name="QueryDatabase",
            session_id="session123",
            threshold_chars=50000
        )

        # Stream chunks
        async for chunk in tool_execution():
            await buffer.append(chunk)

        # Finalize and get result
        content, file_id = await buffer.finalize()

        if file_id:
            # Output was redirected to file
            logger.info(f"Large output saved to {file_id}")
        else:
            # Output stayed in buffer
            logger.info(f"Output: {content[:100]}...")
    """

    def __init__(
        self,
        tool_name: str,
        session_id: str,
        owner_id: Optional[str] = None,
        threshold_chars: int = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
    ):
        """
        Initialize streaming buffer.

        Args:
            tool_name: Name of the tool generating output
            session_id: Session identifier for isolation
            owner_id: User ID for quota tracking (optional)
            threshold_chars: Size threshold for file redirection
                           (default from env: TOOL_OUTPUT_LARGE_THRESHOLD)
            event_callback: Optional async callback for stream events
                          Signature: async def callback(event_type: str, data: dict)
                          Events: "redirect_started", "redirect_completed"
        """
        self.tool_name = tool_name
        self.session_id = session_id
        self.owner_id = owner_id
        self.event_callback = event_callback

        # Get threshold from environment or use provided value
        default_threshold = int(
            os.getenv("TOOL_OUTPUT_LARGE_THRESHOLD", "1000000")
        )
        self.threshold_chars = threshold_chars or default_threshold

        # Buffer state
        self.buffer = []  # List of string chunks
        self.total_chars = 0
        self.file_handle = None
        self.file_path = None
        self.file_id = None
        self.redirected = False

        logger.debug(
            f"[STREAMING_BUFFER] Initialized for {tool_name}, "
            f"threshold={self.threshold_chars:,} chars, session={session_id}"
        )

    async def append(self, chunk: str) -> None:
        """
        Append chunk to buffer, auto-redirect to file if threshold exceeded.

        This method handles the core streaming logic:
        1. Before threshold: buffer chunks in memory
        2. At threshold: flush buffer to file, open file handle
        3. After threshold: write directly to file

        Args:
            chunk: String chunk from tool output stream

        Raises:
            StorageQuotaExceeded: If quota limit would be exceeded
            IOError: If file write fails
        """
        if not chunk:  # Skip empty chunks
            return

        chunk_size = len(chunk)
        self.total_chars += chunk_size

        if not self.redirected:
            # Still buffering in memory
            self.buffer.append(chunk)

            # Check if we've crossed threshold
            if self.total_chars > self.threshold_chars:
                logger.info(
                    f"[STREAMING_REDIRECT] Tool={self.tool_name}, "
                    f"Size={self.total_chars:,} > {self.threshold_chars:,} chars, "
                    f"redirecting to file..."
                )

                # Emit event for SSE notification (if callback provided)
                if self.event_callback:
                    await self.event_callback("redirect_started", {
                        "tool_name": self.tool_name,
                        "total_chars": self.total_chars,
                        "threshold_chars": self.threshold_chars,
                        "session_id": self.session_id,
                    })

                await self._redirect_to_file()
        else:
            # Already redirected, write directly to file
            try:
                self.file_handle.write(chunk)
                self.file_handle.flush()  # Ensure data written
            except IOError as e:
                logger.error(
                    f"[STREAMING_BUFFER] Error writing to file {self.file_path}: {e}"
                )
                raise

    async def _redirect_to_file(self) -> None:
        """
        Open file and flush buffer to disk.

        This method is called when threshold is exceeded. It:
        1. Checks storage quota
        2. Creates ephemeral file with unique name
        3. Writes buffered content to file
        4. Opens file handle for continued streaming
        5. Registers file in Redis with 7-day TTL

        Raises:
            StorageQuotaExceeded: If quota limit would be exceeded
        """
        # Check storage quota BEFORE creating file
        try:
            await check_storage_quota(
                session_id=self.session_id,
                additional_bytes=self.total_chars,  # Estimate based on current size
                owner_id=self.owner_id
            )
        except Exception as e:
            logger.error(
                f"[STREAMING_BUFFER] Quota check failed: {e}, "
                f"cannot redirect to file"
            )
            raise

        # Create ephemeral file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_tool_name = re.sub(r'[^a-zA-Z0-9_-]', '_', self.tool_name.lower())

        # Generate partial content hash from first buffer chunk for determinism
        first_chunk = self.buffer[0] if self.buffer else "empty"
        content_hash = hashlib.sha256(first_chunk.encode()).hexdigest()[:12]

        self.file_id = f"file-{content_hash}-{safe_tool_name}_{timestamp}.txt"

        # Ephemeral storage path
        ephemeral_dir = Path(SHARED_UPLOAD_DIR) / "ephemeral" / self.session_id
        ephemeral_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = ephemeral_dir / self.file_id

        # Open file for writing
        try:
            self.file_handle = open(self.file_path, 'w', encoding='utf-8')

            # Flush buffer to file
            for buffered_chunk in self.buffer:
                self.file_handle.write(buffered_chunk)

            self.file_handle.flush()

            logger.info(
                f"[STREAMING_BUFFER] Redirected to file: {self.file_path} "
                f"({self.total_chars:,} chars so far)"
            )

            # Clear buffer to free memory
            self.buffer.clear()
            self.redirected = True

            # Emit event for SSE notification (if callback provided)
            if self.event_callback:
                await self.event_callback("redirect_completed", {
                    "tool_name": self.tool_name,
                    "file_id": self.file_id,
                    "file_path": str(self.file_path),
                    "total_chars": self.total_chars,
                    "session_id": self.session_id,
                })

        except IOError as e:
            logger.error(f"[STREAMING_BUFFER] Failed to create file {self.file_path}: {e}")
            raise

    async def _register_file(self) -> str:
        """
        Register file in Redis with 7-day TTL.

        Returns:
            file_id for retrieval
        """
        # Read file from disk to calculate hash (file handle may be closed)
        with open(self.file_path, 'r', encoding='utf-8') as f:
            file_content = f.read()
        content_hash = hashlib.sha256(file_content.encode()).hexdigest()

        # File metadata
        file_metadata = {
            "id": self.file_id,
            "file_id": self.file_id,
            "current_path": str(self.file_path),
            "filename": f"{self.tool_name}_streamed_output.txt",
            "bytes": self.total_chars,  # Character count as proxy for bytes
            "size": self.total_chars,
            "owner_id": self.owner_id,
            "session_id": self.session_id,
            "storage_tier": "ephemeral",
            "ttl_days": 7,
            "source": "streaming_tool_output",
            "tool_name": self.tool_name,
            "content_hash": content_hash,
            "created_at": int(datetime.now().timestamp()),
            "upload_timestamp": datetime.now().isoformat(),
            "object": "file",
            "purpose": "tool_output",
            "status": "processed",
            "streaming_metadata": {
                "threshold_chars": self.threshold_chars,
                "total_chars": self.total_chars,
                "chunks_buffered": len(self.buffer),
            }
        }

        # Register in Redis (7-day TTL)
        redis_pool = await get_files_redis_client()
        await redis_pool.set(
            f"file_metadata:{self.file_id}",
            json.dumps(file_metadata),
            ex=7 * 24 * 60 * 60  # 7 days
        )

        logger.info(
            f"[STREAMING_BUFFER] Registered {self.file_id} in Redis "
            f"with 7-day TTL"
        )

        return self.file_id

    def _extract_metadata(self, content: str) -> Dict[str, Any]:
        """
        Extract metadata from tool output content.

        Tries to parse content as JSON and extract critical metadata fields:
        - status: Tool execution status
        - exit_code: Exit code for code execution tools
        - plots: Array of plot metadata (without base64 content)
        - generated_files: Array of generated file references

        Args:
            content: Tool output content (potentially JSON)

        Returns:
            Dictionary with extracted metadata fields. Empty dict if not JSON
            or if JSON contains no metadata fields.
        """
        metadata = {}

        try:
            data = json.loads(content)
            if isinstance(data, dict):
                # Extract status
                if "status" in data:
                    metadata["status"] = data["status"]

                # Extract exit_code
                if "exit_code" in data:
                    metadata["exit_code"] = data["exit_code"]

                # Extract plots (without base64 content to save space)
                if "plots" in data and isinstance(data["plots"], list):
                    metadata["plots"] = [
                        {k: v for k, v in plot.items() if k != "content_base64" and v is not None}
                        for plot in data["plots"]
                        if isinstance(plot, dict)
                    ]

                # Extract generated_files
                if "generated_files" in data:
                    metadata["generated_files"] = data["generated_files"]

                # Extract output summary if present
                if "output" in data and isinstance(data["output"], str):
                    # Include first 200 chars of output as summary
                    output_str = data["output"]
                    if len(output_str) > 200:
                        metadata["output_summary"] = output_str[:200] + "..."
                    else:
                        metadata["output_summary"] = output_str

        except (json.JSONDecodeError, TypeError) as e:
            # Not JSON or invalid JSON - no metadata to extract
            logger.debug(
                f"[STREAMING_BUFFER] Could not extract metadata from content: {type(e).__name__}"
            )

        return metadata

    async def finalize(self) -> Tuple[Union[str, Dict[str, Any]], Optional[str]]:
        """
        Finalize streaming and return result.

        This method should be called when tool execution completes.
        It handles two scenarios:

        1. Output stayed in buffer (< threshold):
           Returns: (full_content, None)

        2. Output was redirected to file (>= threshold):
           Returns: (structured_dict_with_metadata, file_id)
           The dict includes:
           - summary: Warning message about file redirect
           - file_id: Reference to ephemeral file
           - redirected: True
           - Plus any extracted metadata (status, plots, exit_code, etc.)

        Returns:
            Tuple of (content_or_structured_dict, file_id_if_redirected)
        """
        if self.file_handle:
            # Close file handle
            self.file_handle.close()
            self.file_handle = None

            # Read back the file content to extract metadata
            full_content = ""
            if self.file_path and os.path.exists(self.file_path):
                try:
                    with open(self.file_path, 'r') as f:
                        full_content = f.read()
                except Exception as e:
                    logger.warning(
                        f"[STREAMING_BUFFER] Failed to read back file for metadata extraction: {e}"
                    )

            # Try to extract metadata from content
            metadata = self._extract_metadata(full_content)

            # Register file in Redis
            await self._register_file()

            # Return structured response with metadata
            warning_message = (
                f"⚠️ Tool output too large ({self.total_chars:,} chars, "
                f"~{self.total_chars // 4:,} tokens).\n"
                f"Saved to ephemeral file: {self.file_id}\n\n"
                f"To access the full output, use:\n"
                f"  • ReadFile('{self.file_id}')\n"
                f"  • GeneratePresignedURL('{self.file_id}')\n\n"
                f"Note: Ephemeral files auto-delete after 7 days."
            )

            result_dict = {
                "summary": warning_message,
                "file_id": self.file_id,
                "redirected": True,
                **metadata  # Merge extracted metadata
            }

            logger.info(
                f"[STREAMING_BUFFER] Finalized with file redirect: {self.file_id}, "
                f"total_chars={self.total_chars:,}, metadata_fields={list(metadata.keys())}"
            )

            return result_dict, self.file_id

        else:
            # Output stayed in buffer
            full_content = "".join(self.buffer)

            logger.debug(
                f"[STREAMING_BUFFER] Finalized without redirect: {self.total_chars:,} chars"
            )

            return full_content, None

    def __del__(self):
        """Ensure file handle is closed on garbage collection."""
        if self.file_handle:
            try:
                self.file_handle.close()
            except Exception:
                pass  # Ignore errors during cleanup
