"""High-level facade for ADEPT Connector operations.

AdeptFacade wraps all lower-level clients (Response API, AG-UI, Files, MCP)
with session management and image rendering. Connectors instantiate a facade
once and call its methods — the facade handles session lifecycle, streaming,
image URL scanning, and rendering delegation.

This is the primary entry point for connector authors.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .auth import AuthManager
from .clients.agui_client import AGUIClient, AGUIResult, ToolCallInfo
from .clients.base import BaseAdeptClient
from .clients.files_client import FilesClient
from .clients.mcp_proxy import MCPProxyClient
from .clients.responses_api import ResponseResult, ResponsesAPIClient
from .config import AdeptConnectorConfig
from .rendering import (
    ImageData,
    ImageRenderer,
    MarkdownRenderer,
    extract_image_urls,
    MAX_AUTO_IMAGES,
)
from .session import SessionInfo, SessionManager

logger = logging.getLogger(__name__)


@dataclass
class ArtifactData:
    """A fetched artifact with MIME-based classification.

    Created by :meth:`FilesClient.fetch_artifact` and used by the facade
    to route content to the correct renderer/embedder.
    """

    data: bytes
    mime_type: Optional[str]
    source_url: str
    category: str  # "image", "text", or "binary"

    @property
    def is_image(self) -> bool:
        return self.category == "image"

    @property
    def is_text(self) -> bool:
        return self.category == "text"

    @property
    def text_content(self) -> Optional[str]:
        """Decode bytes as UTF-8 text.  Returns None for non-text or decode errors."""
        if not self.is_text:
            return None
        try:
            return self.data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    @property
    def base64_content(self) -> str:
        """Base64-encode the raw bytes (works for any category)."""
        return base64.b64encode(self.data).decode("ascii")

    def as_image(self) -> Optional[ImageData]:
        """Convert to ImageData if this is an image artifact."""
        if not self.is_image or not self.mime_type:
            return None
        return ImageData(
            data=self.data, mime_type=self.mime_type, source_url=self.source_url
        )

    @property
    def size_bytes(self) -> int:
        return len(self.data)


@dataclass
class ChatResult:
    """Result from a facade chat() call."""

    text: str
    images: list[ImageData] = field(default_factory=list)
    text_artifacts: list[str] = field(default_factory=list)
    binary_artifacts: list[ArtifactData] = field(default_factory=list)
    session_fork: Optional[dict[str, Any]] = None
    session: Optional[SessionInfo] = None
    model: str = ""
    finish_reason: Optional[str] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        return len(self.images) > 0

    @property
    def has_artifacts(self) -> bool:
        return bool(self.images or self.text_artifacts or self.binary_artifacts)


@dataclass
class AGUIChatResult:
    """Result from a facade agui_run() call."""

    text: str
    images: list[ImageData] = field(default_factory=list)
    text_artifacts: list[str] = field(default_factory=list)
    binary_artifacts: list[ArtifactData] = field(default_factory=list)
    session_fork: Optional[dict[str, Any]] = None
    session: Optional[SessionInfo] = None
    thread_id: str = ""
    run_id: str = ""
    tool_calls: list[ToolCallInfo] = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        return len(self.images) > 0

    @property
    def has_artifacts(self) -> bool:
        return bool(self.images or self.text_artifacts or self.binary_artifacts)


class AdeptFacade:
    """High-level API for ADEPT connector operations.

    Wraps Response API, AG-UI, Files, and MCP clients with session
    management and automatic image fetching/rendering.

    Args:
        config: Full ADEPT connector configuration.
        auth: Authentication manager.
        client: Base HTTP client (with client_source already set).
        session_mgr: Session manager for thread/session mapping.
        renderer: Image renderer for the target UI. Defaults to MarkdownRenderer.

    Usage:
        facade = AdeptFacade(config, auth, client, session_mgr)
        result = await facade.chat("What is BLAST?", session_id="abc")
        # result.text contains the response
        # result.images contains any fetched ImageData objects
        rendered = facade.render(result)  # Applies renderer
    """

    def __init__(
        self,
        config: AdeptConnectorConfig,
        auth: AuthManager,
        client: BaseAdeptClient,
        session_mgr: SessionManager,
        renderer: Optional[ImageRenderer] = None,
    ) -> None:
        self.config = config
        self.auth = auth
        self.client = client
        self.session_mgr = session_mgr
        self.renderer = renderer or MarkdownRenderer()

        # Sub-clients
        self.responses = ResponsesAPIClient(client)
        self.agui = AGUIClient(client)
        self.files = FilesClient(client)
        self.mcp = MCPProxyClient(
            config, auth,
            instance_id=client.instance_id,
            client_source=client._client_source,
        )

    async def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        auto_fetch_images: bool = True,
    ) -> ChatResult:
        """Send a message via Response API with session + image handling.

        1. Gets or creates session from session_id
        2. Calls ResponsesAPIClient.chat() (SSE streaming)
        3. Handles session fork if present
        4. Scans response for image URLs
        5. Fetches image bytes, wraps as ImageData
        6. Returns ChatResult with text + images

        Args:
            message: User message to send.
            session_id: Thread/session ID. Creates new if None.
            model: Model override. Uses config default_model if None.
            auto_fetch_images: Whether to scan and fetch image URLs.
        """
        session = self.session_mgr.get_or_create(session_id)
        session.message_count += 1
        session.touch()

        result = await self.responses.chat(
            messages=[{"role": "user", "content": message}],
            model=model or self.config.default_model,
            session_id=session.session_id,
            mcp_session_id=session.mcp_session_id,
        )

        # Handle fork
        fork_data = None
        if result.session_fork:
            fork_data = result.session_fork
            new_id = result.session_fork.get("forked_session_id")
            if new_id:
                session = self.session_mgr.handle_fork(session.thread_id, new_id)

        # Fetch artifacts
        images: list[ImageData] = []
        text_artifacts: list[str] = []
        binary_artifacts: list[ArtifactData] = []
        if auto_fetch_images:
            images, text_artifacts, binary_artifacts = await self._fetch_artifacts(
                result.content
            )

        return ChatResult(
            text=result.content,
            images=images,
            text_artifacts=text_artifacts,
            binary_artifacts=binary_artifacts,
            session_fork=fork_data,
            session=session,
            model=result.model,
            finish_reason=result.finish_reason,
            tool_calls=result.tool_calls,
        )

    async def agui_run(
        self,
        message: str,
        thread_id: Optional[str] = None,
        auto_fetch_images: bool = True,
    ) -> AGUIChatResult:
        """Send a message via AG-UI Protocol with session + image handling.

        Same workflow as chat() but uses AG-UI JSONL streaming.

        Args:
            message: User message to send.
            thread_id: Thread/session ID. Creates new if None.
            auto_fetch_images: Whether to scan and fetch image URLs.
        """
        session = self.session_mgr.get_or_create(thread_id)
        session.message_count += 1
        session.touch()

        result = await self.agui.run(
            messages=[{"role": "user", "content": message}],
            thread_id=session.thread_id,
        )

        # Handle fork
        fork_data = None
        if result.session_fork:
            fork_data = result.session_fork
            new_id = result.session_fork.get("new_thread_id")
            if new_id:
                session = self.session_mgr.handle_fork(session.thread_id, new_id)

        # Fetch artifacts
        images: list[ImageData] = []
        text_artifacts: list[str] = []
        binary_artifacts: list[ArtifactData] = []
        if auto_fetch_images:
            images, text_artifacts, binary_artifacts = await self._fetch_artifacts(
                result.content
            )

        return AGUIChatResult(
            text=result.content,
            images=images,
            text_artifacts=text_artifacts,
            binary_artifacts=binary_artifacts,
            session_fork=fork_data,
            session=session,
            thread_id=result.thread_id,
            run_id=result.run_id,
            tool_calls=result.tool_calls,
        )

    def render(self, result: ChatResult | AGUIChatResult) -> Any:
        """Apply the configured ImageRenderer to a chat result.

        Renders images via the configured renderer, appends text artifacts
        inline, and adds download references for binary artifacts.
        """
        rendered = self.renderer.render_with_text(result.text, result.images)
        if isinstance(rendered, str):
            for artifact in result.text_artifacts:
                rendered += "\n\n---\n" + artifact + "\n---"
            for ba in result.binary_artifacts:
                size_kb = ba.size_bytes / 1024
                rendered += (
                    f"\n\n[Binary artifact: {ba.mime_type or 'unknown'}, "
                    f"{size_kb:.1f} KB — use download tool to save]"
                )
        return rendered

    async def _fetch_artifacts(
        self, text: str,
    ) -> tuple[list[ImageData], list[str], list[ArtifactData]]:
        """Scan text for artifact URLs, fetch, and route by MIME type.

        Uses :meth:`FilesClient.fetch_artifact` to download and classify
        each presigned URL:

        - **image** → ``ImageData`` for inline rendering
        - **text** → decoded UTF-8 string for inline embedding
        - **binary** → ``ArtifactData`` with base64 for download/embedding

        Returns:
            Tuple of ``(images, text_artifacts, binary_artifacts)``.
        """
        urls = extract_image_urls(text)
        if not urls:
            return [], [], []

        images: list[ImageData] = []
        text_artifacts: list[str] = []
        binary_artifacts: list[ArtifactData] = []

        for url in urls[:MAX_AUTO_IMAGES]:
            try:
                data, mime_type, category = await self.files.fetch_artifact(url)
                artifact = ArtifactData(
                    data=data, mime_type=mime_type,
                    source_url=url, category=category,
                )

                if category == "image":
                    images.append(
                        ImageData(data=data, mime_type=mime_type, source_url=url)
                    )
                    logger.debug(
                        "Auto-fetched image: %s (%s, %d bytes)",
                        url, mime_type, len(data),
                    )
                elif category == "text":
                    decoded = artifact.text_content
                    if decoded is not None:
                        text_artifacts.append(decoded)
                        logger.debug(
                            "Auto-fetched text artifact: %s (%s, %d bytes)",
                            url, mime_type, len(data),
                        )
                    else:
                        binary_artifacts.append(artifact)
                        logger.debug(
                            "Text artifact not decodable, stored as binary: %s",
                            url,
                        )
                else:
                    binary_artifacts.append(artifact)
                    logger.debug(
                        "Auto-fetched binary artifact: %s (mime=%s, %d bytes)",
                        url, mime_type, len(data),
                    )
            except Exception as e:
                logger.warning("Auto-fetch failed for %s: %s", url, e)

        return images, text_artifacts, binary_artifacts

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.close()

    async def __aenter__(self) -> "AdeptFacade":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()
