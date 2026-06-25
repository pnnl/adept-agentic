"""SSE streaming client for ADEPT Response API.

Parses Server-Sent Events from POST /v1/responses/chat/completions,
accumulates delta content, and handles session fork metadata.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .base import BaseAdeptClient

logger = logging.getLogger(__name__)


@dataclass
class ResponseResult:
    """Accumulated result from an SSE streaming response."""

    content: str = ""
    model: str = ""
    finish_reason: Optional[str] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    session_fork: Optional[dict[str, Any]] = None


class ResponsesAPIClient:
    """Client for ADEPT Response API (SSE streaming)."""

    def __init__(self, base_client: BaseAdeptClient) -> None:
        self._client = base_client

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "agentic-framework:scientific-agent-v1",
        session_id: Optional[str] = None,
        mcp_session_id: Optional[str] = None,
    ) -> ResponseResult:
        """Send a chat request and accumulate the streamed SSE response."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if session_id:
            payload["session_id"] = session_id
        if mcp_session_id:
            payload["mcp_session_id"] = mcp_session_id

        result = ResponseResult(model=model)

        stream_ctx = await self._client.post_stream(
            "/responses/chat/completions", json=payload
        )
        async with stream_ctx as stream:
            async for line in stream.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue

                data_str = line[6:]  # Strip "data: " prefix
                if data_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    logger.warning("Malformed SSE chunk: %s", data_str[:100])
                    continue

                # Error chunk
                if "error" in chunk:
                    raise RuntimeError(chunk["error"].get("message", str(chunk["error"])))

                # Content delta
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    if "content" in delta and delta["content"]:
                        result.content += delta["content"]

                    finish = choices[0].get("finish_reason")
                    if finish:
                        result.finish_reason = finish

                    # Tool calls in delta
                    if "tool_calls" in delta:
                        result.tool_calls.extend(delta["tool_calls"])

                # Session fork metadata (final chunk)
                if "session_fork" in chunk:
                    result.session_fork = chunk["session_fork"]

        return result
