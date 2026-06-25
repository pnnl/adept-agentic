"""Chat tools — adept_chat (Response API) and adept_agui_run (AG-UI)."""

from __future__ import annotations

import logging
import re
from typing import Optional, Union

from fastmcp.utilities.types import Image

from ..server import get_context, mcp

logger = logging.getLogger(__name__)

# Matches presigned download URLs and plot URLs from ADEPT responses.
# Captures: /v1/files/{id}/download?token=...&expires=... and /v1/plots/...
_IMAGE_URL_RE = re.compile(
    r"(https?://[^\s\"'<>]+/v1/(?:files/[^\s\"'<>]+/download\?[^\s\"'<>]+|plots/[^\s\"'<>]+\.(?:png|jpg|jpeg|gif|webp|svg)))",
    re.IGNORECASE,
)

_MAX_AUTO_IMAGES = 5


async def _auto_fetch_artifacts(text: str) -> list[Union[str, Image]]:
    """Scan text for artifact URLs, fetch, and route by MIME type.

    Returns a list starting with the original text, followed by:
    - ``Image`` objects for image/* content (rendered inline by Claude Desktop)
    - Text strings for text/* content (embedded inline)
    - Reference strings for binary content (user can use adept_download_artifact)

    Failed fetches are silently skipped.
    """
    urls = list(dict.fromkeys(_IMAGE_URL_RE.findall(text)))  # dedupe, preserve order
    if not urls:
        return [text]

    from ....core.clients.files_client import FilesClient, _MIME_TO_FORMAT

    ctx = get_context()
    client = FilesClient(ctx.client)
    parts: list[Union[str, Image]] = [text]

    for url in urls[:_MAX_AUTO_IMAGES]:
        try:
            data, mime_type, category = await client.fetch_artifact(url)

            if category == "image":
                fmt = _MIME_TO_FORMAT.get(mime_type, "png")
                parts.append(Image(data=data, format=fmt))
                logger.debug(
                    "Auto-fetched image: %s (%s, %d bytes)",
                    url, mime_type, len(data),
                )
            elif category == "text":
                try:
                    decoded = data.decode("utf-8")
                    parts.append(f"\n--- Artifact content ({mime_type}) ---\n{decoded}\n---")
                    logger.debug(
                        "Auto-fetched text artifact: %s (%s, %d bytes)",
                        url, mime_type, len(data),
                    )
                except UnicodeDecodeError:
                    logger.debug("Text artifact not decodable: %s", url)
            else:
                size_kb = len(data) / 1024
                parts.append(
                    f"\n[Binary artifact: {mime_type or 'unknown'}, "
                    f"{size_kb:.1f} KB — use adept_download_artifact(url) to save]"
                )
                logger.debug(
                    "Auto-fetched binary artifact: %s (mime=%s, %d bytes)",
                    url, mime_type, len(data),
                )
        except Exception as e:
            logger.warning("Auto-fetch failed for %s: %s", url, e)

    return parts


@mcp.tool()
async def adept_chat(
    message: str,
    session_id: Optional[str] = None,
    model: Optional[str] = None,
) -> Union[str, list[Union[str, Image]]]:
    """Send a message to ADEPT via the Response API and return the response.

    IMPORTANT: Always call adept_create_session() first to get a session_id,
    then pass it here. This ensures ADEPT maintains conversation history,
    uploaded file context, and multi-agent state across messages. Without a
    session_id, each call starts a fresh context with no memory of prior
    messages.

    File workflow: If the user wants ADEPT to process an attached file,
    upload it first with adept_upload_file, then reference the file_id in
    the message here. Example: "Analyze the uploaded file (file_id: file-xyz)".

    Uses SSE streaming internally but returns the complete accumulated response.
    ADEPT automatically manages memory — when context grows large, the server
    forks to a new session with a summary of prior context (handled
    transparently by the connector).

    When ADEPT returns presigned URLs or plot URLs in the response, images are
    automatically fetched and returned inline as MCP image content blocks that
    Claude Desktop renders natively (no CORS, no token exposure). Up to 5
    images per response are auto-fetched.

    You can also use adept_get_image(url) to manually fetch any image URL.
    NEVER ask ADEPT to return raw base64 image data — this wastes tokens.

    Args:
        message: The user message to send.
        session_id: Session ID from adept_create_session(). Always provide this.
        model: Optional model override (default: scientific-agent-v1).
    """
    ctx = get_context()
    from ....core.clients.responses_api import ResponsesAPIClient

    client = ResponsesAPIClient(ctx.client)
    session = ctx.session_mgr.get_or_create(session_id)
    session.message_count += 1
    session.touch()

    result = await client.chat(
        messages=[{"role": "user", "content": message}],
        model=model or ctx.config.default_model,
        session_id=session.session_id,
        mcp_session_id=session.mcp_session_id,
    )

    # Handle fork if server forked the session
    if result.session_fork:
        new_id = result.session_fork.get("forked_session_id")
        if new_id:
            ctx.session_mgr.handle_fork(session.thread_id, new_id)

    parts = await _auto_fetch_artifacts(result.content)
    return parts if len(parts) > 1 else result.content


@mcp.tool()
async def adept_agui_run(
    message: str,
    thread_id: Optional[str] = None,
    include_tool_details: bool = False,
) -> Union[str, list[Union[str, Image]]]:
    """Send a message to ADEPT via the AG-UI Protocol and return the response.

    IMPORTANT: Always call adept_create_session() first to get a session_id,
    then pass it as thread_id here. This ensures ADEPT maintains conversation
    history, uploaded file context, and multi-agent state across messages.
    Without a thread_id, each call starts a fresh context with no memory of
    prior messages.

    AG-UI provides richer event streaming with tool call visibility.
    Returns accumulated text, optionally with tool call details.
    ADEPT automatically manages memory — when context grows large, the server
    forks to a new session with a summary of prior context (handled
    transparently by the connector).

    When ADEPT returns presigned URLs or plot URLs in the response, images are
    automatically fetched and returned inline as MCP image content blocks that
    Claude Desktop renders natively (no CORS, no token exposure). Up to 5
    images per response are auto-fetched.

    You can also use adept_get_image(url) to manually fetch any image URL.
    NEVER ask ADEPT to return raw base64 image data — this wastes tokens.

    Args:
        message: The user message to send.
        thread_id: Session ID from adept_create_session(). Always provide this.
        include_tool_details: If True, append tool call details to output.
    """
    ctx = get_context()
    from ....core.clients.agui_client import AGUIClient

    client = AGUIClient(ctx.client)
    session = ctx.session_mgr.get_or_create(thread_id)
    session.message_count += 1
    session.touch()

    result = await client.run(
        messages=[{"role": "user", "content": message}],
        thread_id=session.thread_id,
    )

    # Handle fork
    if result.session_fork:
        new_id = result.session_fork.get("new_thread_id")
        if new_id:
            ctx.session_mgr.handle_fork(session.thread_id, new_id)

    output = result.content

    if include_tool_details and result.tool_calls:
        details = []
        for tc in result.tool_calls:
            detail = f"- {tc.name}({tc.arguments})"
            if tc.result:
                # Truncate long results
                r = tc.result[:500] + "..." if len(tc.result) > 500 else tc.result
                detail += f" -> {r}"
            details.append(detail)
        output += "\n\n**Tool calls:**\n" + "\n".join(details)

    parts = await _auto_fetch_artifacts(output)
    return parts if len(parts) > 1 else output
