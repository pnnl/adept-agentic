"""JSONL streaming client for ADEPT AG-UI Protocol.

Parses newline-delimited JSON events from POST /v1/ag-ui/run,
accumulates TEXT_MESSAGE_CONTENT deltas, collects TOOL_CALL sequences,
and handles META_EVENT for session forks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .base import BaseAdeptClient

logger = logging.getLogger(__name__)


@dataclass
class ToolCallInfo:
    """Accumulated tool call from AG-UI events."""

    tool_call_id: str
    name: str = ""
    arguments: str = ""
    result: Optional[str] = None


@dataclass
class AGUIResult:
    """Accumulated result from an AG-UI JSONL stream."""

    content: str = ""
    thread_id: str = ""
    run_id: str = ""
    tool_calls: list[ToolCallInfo] = field(default_factory=list)
    session_fork: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class AGUIClient:
    """Client for ADEPT AG-UI Protocol (JSONL streaming)."""

    def __init__(self, base_client: BaseAdeptClient) -> None:
        self._client = base_client

    async def run(
        self,
        messages: list[dict[str, str]],
        thread_id: Optional[str] = None,
    ) -> AGUIResult:
        """Send a run request and accumulate the JSONL event stream."""
        payload: dict[str, Any] = {"messages": messages}
        if thread_id:
            payload["thread_id"] = thread_id

        result = AGUIResult()
        active_tool_calls: dict[str, ToolCallInfo] = {}

        stream_ctx = await self._client.post_stream(
            "/ag-ui/run", json=payload
        )
        async with stream_ctx as stream:
            async for line in stream.aiter_lines():
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Malformed JSONL line: %s", line[:100])
                    continue

                event_type = event.get("type", "")

                if event_type == "RUN_STARTED":
                    result.thread_id = event.get("threadId", "")
                    result.run_id = event.get("runId", "")

                elif event_type == "TEXT_MESSAGE_CONTENT":
                    result.content += event.get("delta", "")

                elif event_type == "TOOL_CALL_START":
                    tc_id = event.get("toolCallId", "")
                    tc = ToolCallInfo(
                        tool_call_id=tc_id,
                        name=event.get("toolCallName", ""),
                    )
                    active_tool_calls[tc_id] = tc

                elif event_type == "TOOL_CALL_ARGS":
                    tc_id = event.get("toolCallId", "")
                    if tc_id in active_tool_calls:
                        active_tool_calls[tc_id].arguments += event.get("delta", "")

                elif event_type == "TOOL_CALL_END":
                    tc_id = event.get("toolCallId", "")
                    if tc_id in active_tool_calls:
                        result.tool_calls.append(active_tool_calls.pop(tc_id))

                elif event_type == "TOOL_CALL_RESULT":
                    tc_id = event.get("toolCallId", "")
                    # Find matching tool call (may already be in result list)
                    for tc in result.tool_calls:
                        if tc.tool_call_id == tc_id:
                            tc.result = event.get("content", "")
                            break

                elif event_type == "META_EVENT":
                    key = event.get("key", "")
                    if key == "session_fork":
                        result.session_fork = event.get("value")

                elif event_type == "RUN_ERROR":
                    result.error = event.get("message", "Unknown error")

                elif event_type == "RUN_FINISHED":
                    pass  # Stream complete

        # Move any remaining active tool calls to results
        for tc in active_tool_calls.values():
            result.tool_calls.append(tc)

        if result.error:
            raise RuntimeError(f"AG-UI run error: {result.error}")

        return result
