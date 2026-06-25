"""File tools — adept_upload_file, adept_list_files, adept_get_image, adept_download_artifact."""

from __future__ import annotations

import base64
import json
import logging
import mimetypes as _mimetypes
import re
from pathlib import Path, PurePosixPath
from typing import Optional, Union
from urllib.parse import unquote, urlparse

from fastmcp.utilities.types import Image

from ..server import get_context, mcp

logger = logging.getLogger(__name__)

# Claude Desktop sandbox paths — not accessible from MCP host process.
# When we see these, fetch via MCP resources/read instead of host open().
_SANDBOX_PREFIXES = ("/mnt/user-data/", "/home/claude/")


def _is_sandbox_path(path: str) -> bool:
    """Return True if path is inside Claude Desktop's sandbox filesystem."""
    return any(path.startswith(p) for p in _SANDBOX_PREFIXES)


async def _discover_resource_uri(sandbox_path: str) -> str | None:
    """Search Claude Desktop's MCP resources for a file matching the sandbox path."""
    from fastmcp.server.dependencies import get_context as _fastmcp_ctx

    target_name = PurePosixPath(sandbox_path).name.lower()
    if not target_name:
        return None

    try:
        mcp_ctx = _fastmcp_ctx()
        resources = await mcp_ctx.list_resources()
        logger.info(
            "MCP resources/list returned %d resources", len(resources)
        )
        for res in resources:
            res_uri = str(getattr(res, "uri", ""))
            res_name = getattr(res, "name", "")
            logger.debug("  Resource: uri=%s, name=%s", res_uri, res_name)
            if target_name in res_uri.lower() or target_name == res_name.lower():
                logger.info(
                    "Matched sandbox path %s to MCP resource URI: %s",
                    sandbox_path, res_uri,
                )
                return res_uri
    except Exception as exc:
        logger.warning(
            "MCP resources/list failed (may not be supported): %s", exc
        )

    return None


async def _read_resource_bytes(uri: str) -> tuple[str, bytes]:
    """Fetch file content from Claude Desktop via MCP resources/read."""
    from fastmcp.server.dependencies import get_context as _fastmcp_ctx

    mcp_ctx = _fastmcp_ctx()

    parsed_path = unquote(urlparse(uri).path)
    name = PurePosixPath(parsed_path).name or "uploaded_file"

    actual_uri = uri
    try:
        contents = await mcp_ctx.read_resource(actual_uri)
    except Exception as exc:
        exc_str = str(exc).lower()
        if "unknown resource" in exc_str or "not found" in exc_str:
            logger.warning(
                "resources/read failed for %s (%s), "
                "trying resources/list to discover correct URI...",
                actual_uri, exc,
            )
            discovered = await _discover_resource_uri(parsed_path)
            if discovered:
                actual_uri = discovered
                contents = await mcp_ctx.read_resource(actual_uri)
            else:
                raise FileNotFoundError(
                    f"MCP resources/read returned 'Unknown resource' for {uri} "
                    f"and resources/list found no matching resource by filename "
                    f"'{name}'. Claude Desktop may use a different URI scheme "
                    f"for uploaded files. Try using file_data (base64) mode "
                    f"instead, or check Claude Desktop's resource URI format."
                ) from exc
        else:
            raise

    if not contents:
        raise FileNotFoundError(
            f"MCP resources/read returned no content for {actual_uri}"
        )
    item = contents[0]

    # BlobResourceContents has .blob (base64), TextResourceContents has .text
    if hasattr(item, "blob") and item.blob:
        raw = base64.b64decode(item.blob)
    elif hasattr(item, "text") and item.text is not None:
        raw = item.text.encode("utf-8")
    else:
        raise ValueError(
            f"MCP resources/read returned unrecognized content type for {actual_uri}"
        )

    logger.info(
        "Fetched %d bytes for %s via MCP resources/read (uri=%s)",
        len(raw), name, actual_uri,
    )
    return name, raw


@mcp.tool()
async def adept_upload_file(
    file_path: Optional[str] = None,
    file_data: Optional[str] = None,
    file_name: Optional[str] = None,
    file_uri: Optional[str] = None,
    purpose: str = "assistants",
    session_id: Optional[str] = None,
) -> str:
    """Upload a file to ADEPT for agent processing.

    When the user attaches or references a file and wants ADEPT to process it,
    use this tool to upload the file first, then pass the returned file_id to
    adept_chat so ADEPT can access it.

    Recommended workflow:
    1. adept_create_session() — get a session_id (if not already created)
    2. adept_upload_file(..., session_id=session_id) — upload, get file_id
    3. adept_chat(message="Analyze file_id: <id>", session_id=session_id)

    Three input modes — use whichever matches how the file is available:

    1. **file_path** — Local filesystem path (e.g. user dragged a file).
       Example: file_path="/Users/alice/data.csv"

    2. **file_data** + **file_name** — Base64-encoded content (e.g. from
       Claude Desktop's embedded resources or copy-pasted data).
       Example: file_data="aGVsbG8=", file_name="hello.txt"

    3. **file_uri** — file:// URI (e.g. from MCP ResourceLink).
       Example: file_uri="file:///Users/alice/Downloads/report.pdf"
       If the URI points to a Claude Desktop sandbox path (e.g.
       /mnt/user-data/uploads/), the content is fetched automatically
       via MCP resources/read — no host filesystem access needed.

    Provide exactly one of file_path, file_data, or file_uri.

    Args:
        file_path: Absolute path to a local file.
        file_data: Base64-encoded file content.
        file_name: Filename (required when using file_data).
        file_uri: file:// URI to resolve and upload.
        purpose: Upload purpose (default: assistants).
        session_id: Session ID from adept_create_session(). Always pass this
            to associate uploaded files with the current conversation.

    Returns:
        JSON string with file_id, filename, and size.
    """
    app_ctx = get_context()
    from ....core.clients.files_client import FilesClient

    # --- Intercept sandbox file_uri before it hits the client ---
    if file_uri:
        parsed = urlparse(file_uri)
        if parsed.scheme == "file" and _is_sandbox_path(parsed.path):
            logger.info(
                "Sandbox URI detected (%s), fetching via MCP resources/read",
                parsed.path,
            )
            name, raw = await _read_resource_bytes(file_uri)
            file_data = base64.b64encode(raw).decode("ascii")
            file_name = file_name or name
            file_uri = None  # Consumed — don't pass to client

    client = FilesClient(app_ctx.client)
    result = await client.upload(
        file_path=file_path,
        purpose=purpose,
        session_id=session_id,
        file_data=file_data,
        file_name=file_name,
        file_uri=file_uri,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def adept_list_mcp_resources() -> str:
    """List MCP resources available from the host (Claude Desktop).

    Diagnostic tool that calls MCP resources/list to enumerate what
    resources Claude Desktop exposes. Use this to discover the correct
    URI scheme for uploaded files when file_uri mode returns
    'Unknown resource'.

    Returns:
        JSON array of resource entries with uri and name fields.
    """
    from fastmcp.server.dependencies import get_context as _fastmcp_ctx

    try:
        mcp_ctx = _fastmcp_ctx()
        resources = await mcp_ctx.list_resources()
        result = []
        for res in resources:
            entry = {
                "uri": str(getattr(res, "uri", "")),
                "name": getattr(res, "name", ""),
            }
            if hasattr(res, "description") and res.description:
                entry["description"] = res.description
            if hasattr(res, "mimeType") and res.mimeType:
                entry["mimeType"] = res.mimeType
            result.append(entry)
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({
            "error": str(e),
            "hint": "MCP resources/list may not be supported by the current host. "
                    "This is expected when running outside Claude Desktop.",
        }, indent=2)


@mcp.tool()
async def adept_list_files(session_id: Optional[str] = None) -> str:
    """List all files uploaded to or generated by ADEPT.

    Use this to see what files are available — both files you uploaded
    (via adept_upload_file) and files ADEPT generated during analysis
    (plots, CSV summaries, processed results, etc.).

    The returned metadata includes file IDs, filenames, sizes, and
    creation timestamps. Use the file_id values to reference files in
    adept_chat messages or to construct presigned download URLs.

    When ADEPT generates plots or output files during a chat session,
    use adept_list_files to find them, then:
    - adept_get_image(url) to view images inline in the conversation
    - adept_download_artifact(url) to save files to your local disk

    Args:
        session_id: Optional session ID to filter files for a specific
            conversation. Omit to list all files.

    Returns:
        JSON array of file metadata objects with id, filename, bytes, etc.
    """
    ctx = get_context()
    from ....core.clients.files_client import FilesClient

    client = FilesClient(ctx.client)
    files = await client.list_files(session_id=session_id)
    return json.dumps(files, indent=2)


@mcp.tool()
async def adept_get_image(url: str) -> Union[Image, str]:
    """Fetch an image from a URL and display it inline in the conversation.

    DISPLAY ONLY — this tool renders the image inside Claude Desktop but
    does NOT save it to disk. To save an image or file to your local
    filesystem, use adept_download_artifact instead.

    The connector is the only process that can reach ADEPT's internal
    servers (e.g. your-adept-host.example.com). Claude Desktop's sandbox and
    your web browser cannot access presigned URLs directly — you must
    use this tool to view images from ADEPT.

    Works with:
    - Presigned URLs from ADEPT responses (e.g. /v1/files/.../download?token=...)
    - plot_url values from ExecuteCode or code execution responses
    - Any image URL reachable from the connector host

    Typical workflow after ADEPT generates a plot:
    1. adept_get_image(url) — view the plot inline
    2. adept_download_artifact(url) — save the plot to ~/Downloads

    Args:
        url: The image URL to fetch (presigned URL, plot_url, etc.).

    Returns:
        Inline image rendered by Claude Desktop, or error message on failure.
    """
    ctx = get_context()
    from ....core.clients.files_client import FilesClient, _MIME_TO_FORMAT

    client = FilesClient(ctx.client)

    try:
        data, mime_type, category = await client.fetch_artifact(url)
    except Exception as e:
        return f"Failed to fetch artifact from {url}: {e}"

    if category == "image":
        format_str = _MIME_TO_FORMAT.get(mime_type, "png")
        return Image(data=data, format=format_str)
    elif category == "text":
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return f"[Binary content: {mime_type or 'unknown'}, {len(data)} bytes — use adept_download_artifact to save]"
    else:
        size_kb = len(data) / 1024
        return (
            f"[Binary artifact: {mime_type or 'unknown'}, {size_kb:.1f} KB — "
            f"this is not an image. Use adept_download_artifact(url) to save it to disk.]"
        )


# Maximum download size for adept_download_artifact (100 MB).
_MAX_ARTIFACT_BYTES = 100 * 1024 * 1024

# Characters allowed in sanitized filenames.
_SAFE_FILENAME_RE = re.compile(r"[^\w\s\-.]", re.ASCII)


def _sanitize_filename(name: str) -> str:
    """Sanitize a filename: strip path traversal, control chars, and unsafe characters."""
    name = PurePosixPath(name).name
    name = name.replace("..", "")
    name = _SAFE_FILENAME_RE.sub("_", name)
    name = "_".join(name.split())
    return name or "download"


def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """Return a non-conflicting path in *directory*, appending _1, _2, ... if needed."""
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


@mcp.tool()
async def adept_download_artifact(
    url: str,
    save_dir: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    """Download a file from a URL and save it to the user's local disk.

    Use this whenever the user wants to KEEP a file that ADEPT generated —
    plots, CSV results, processed data, or any other artifact. Unlike
    adept_get_image (which only displays inline), this tool persists the
    file to the host filesystem where the user can open, share, or sync it.

    The connector is the only process that can reach ADEPT's internal
    servers. Claude Desktop's sandbox and the user's browser cannot
    download from presigned URLs directly — use this tool instead.

    Save location priority:
    1. Explicit save_dir argument (if provided)
    2. ADEPT_WORKSPACE_DIR environment variable (if configured)
    3. ~/Downloads (if it exists)
    4. Current working directory (fallback)

    Files are never overwritten — if a file with the same name exists,
    a suffix (_1, _2, ...) is appended automatically.

    Works with:
    - Presigned URLs from ADEPT responses (e.g. /v1/files/.../download?token=...)
    - plot_url values from ExecuteCode or code execution responses
    - Any file URL reachable from the connector host

    Typical workflow:
    1. adept_chat("Generate a summary plot of the data") — ADEPT creates plot
    2. adept_get_image(presigned_url) — view plot inline
    3. adept_download_artifact(presigned_url) — save plot to disk

    Args:
        url: The URL to download (presigned URL, plot_url, etc.).
        save_dir: Directory to save to. Overrides ADEPT_WORKSPACE_DIR.
        filename: Override filename. By default extracted from the URL path.

    Returns:
        JSON with local_path, filename, size_bytes, and mime_type.
    """
    ctx = get_context()
    from ....core.clients.files_client import FilesClient

    client = FilesClient(ctx.client)

    # --- Download bytes ---
    data, mime_type = await client.download_bytes(url, max_bytes=_MAX_ARTIFACT_BYTES)

    # --- Resolve filename ---
    if filename:
        safe_name = _sanitize_filename(filename)
    else:
        url_path = unquote(urlparse(url).path)
        raw_name = PurePosixPath(url_path).name if url_path else ""
        safe_name = _sanitize_filename(raw_name) if raw_name else "download"

    # Add extension from mime type if the filename lacks one
    stem_part = Path(safe_name).stem
    suffix_part = Path(safe_name).suffix
    if not suffix_part and mime_type:
        guessed_ext = _mimetypes.guess_extension(mime_type, strict=False)
        if guessed_ext:
            suffix_part = guessed_ext
            safe_name = f"{stem_part}{suffix_part}"

    # --- Resolve save directory ---
    if save_dir:
        target_dir = Path(save_dir).expanduser().resolve()
    elif ctx.config.workspace_dir:
        target_dir = Path(ctx.config.workspace_dir).expanduser().resolve()
    else:
        downloads = Path.home() / "Downloads"
        target_dir = downloads if downloads.is_dir() else Path.cwd()

    target_dir.mkdir(parents=True, exist_ok=True)

    if not target_dir.is_dir():
        raise NotADirectoryError(f"Save path is not a directory: {target_dir}")

    # --- Write file (never overwrite) ---
    dest = _unique_path(target_dir, stem_part, suffix_part)
    dest.write_bytes(data)

    logger.info(
        "Saved artifact: %s (%d bytes, %s)", dest, len(data), mime_type,
    )

    return json.dumps({
        "local_path": str(dest),
        "filename": dest.name,
        "size_bytes": len(data),
        "mime_type": mime_type,
    }, indent=2)
