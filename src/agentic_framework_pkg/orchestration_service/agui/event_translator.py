"""Translates LangGraph astream_events(v2) into AG-UI JSONL events.

Consumes an async iterator of LangGraph v2 event dicts and yields AG-UI
JSONL strings (one event per line) using the official ``ag-ui-protocol`` types.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Optional

from ag_ui.core import (
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from ...logger_config import get_logger
from .protocol import to_jsonl

logger = get_logger(__name__)

MAX_RESULT_SIZE = 200_000  # 200K chars ~50K tokens — must match TOOL_OUTPUT_MEDIUM_THRESHOLD


@dataclass
class TranslatorState:
    run_id: str
    thread_id: str
    current_message_id: Optional[str] = None
    message_in_progress: bool = False
    tool_call_map: Dict[str, str] = field(default_factory=dict)
    message_counter: int = 0
    event_counts: Dict[str, int] = field(default_factory=dict)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _count(state: TranslatorState, event_type: str) -> None:
    state.event_counts[event_type] = state.event_counts.get(event_type, 0) + 1


def _truncate_result(text: str) -> str:
    if len(text) <= MAX_RESULT_SIZE:
        return text
    return text[:MAX_RESULT_SIZE] + f"... [truncated, {len(text)} bytes total]"


async def translate_langgraph_to_agui(
    astream_events_iter: AsyncIterator[Dict[str, Any]],
    thread_id: str,
    run_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Translate LangGraph v2 stream events to AG-UI JSONL lines.

    Args:
        astream_events_iter: Async iterator from ``runnable.astream_events()``.
        thread_id: Thread/session identifier.
        run_id: Optional run identifier (generated if not provided).

    Yields:
        JSONL strings (each ending with ``\\n``).
    """
    state = TranslatorState(
        run_id=run_id or f"run_{_new_id()}",
        thread_id=thread_id,
    )

    # Emit RunStarted eagerly
    _count(state, "RUN_STARTED")
    yield to_jsonl(RunStartedEvent(thread_id=state.thread_id, run_id=state.run_id))

    try:
        async for event in astream_events_iter:
            event_kind = event.get("event", "")
            data = event.get("data", {})

            if event_kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk is None:
                    continue

                # Extract text content from AIMessageChunk
                content = ""
                if hasattr(chunk, "content"):
                    content = chunk.content if isinstance(chunk.content, str) else ""
                elif isinstance(chunk, dict):
                    content = chunk.get("content", "")

                if not content:
                    continue

                # Lazy TextMessageStart
                if not state.message_in_progress:
                    state.message_counter += 1
                    state.current_message_id = f"msg_{state.message_counter}"
                    state.message_in_progress = True
                    _count(state, "TEXT_MESSAGE_START")
                    yield to_jsonl(TextMessageStartEvent(
                        message_id=state.current_message_id,
                        role="assistant",
                    ))

                _count(state, "TEXT_MESSAGE_CONTENT")
                yield to_jsonl(TextMessageContentEvent(
                    message_id=state.current_message_id,
                    delta=content,
                ))

            elif event_kind == "on_chat_model_end":
                # Close any open text message
                if state.message_in_progress and state.current_message_id:
                    _count(state, "TEXT_MESSAGE_END")
                    yield to_jsonl(TextMessageEndEvent(
                        message_id=state.current_message_id,
                    ))
                    state.message_in_progress = False

                # Check for tool calls in the output
                output = data.get("output")
                tool_calls = []
                if hasattr(output, "tool_calls"):
                    tool_calls = output.tool_calls
                elif isinstance(output, dict):
                    tool_calls = output.get("tool_calls", [])

                for tc in (tool_calls or []):
                    tc_id = tc.get("id") or _new_id()
                    tc_name = tc.get("name", "unknown_tool")
                    tc_args = tc.get("args", {})
                    state.tool_call_map[tc_id] = tc_name

                    _count(state, "TOOL_CALL_START")
                    yield to_jsonl(ToolCallStartEvent(
                        tool_call_id=tc_id,
                        tool_call_name=tc_name,
                    ))
                    _count(state, "TOOL_CALL_ARGS")
                    yield to_jsonl(ToolCallArgsEvent(
                        tool_call_id=tc_id,
                        delta=json.dumps(tc_args) if isinstance(tc_args, dict) else str(tc_args),
                    ))

            elif event_kind == "on_tool_end":
                output = data.get("output")
                # Extract tool_call_id from the ToolMessage
                tc_id = None
                if hasattr(output, "tool_call_id"):
                    tc_id = output.tool_call_id
                elif isinstance(output, dict):
                    tc_id = output.get("tool_call_id")

                if tc_id is None:
                    tc_id = _new_id()

                # Extract result content
                result_str = ""
                if hasattr(output, "content"):
                    result_str = str(output.content)
                elif isinstance(output, dict):
                    result_str = str(output.get("content", output))
                else:
                    result_str = str(output)

                _count(state, "TOOL_CALL_END")
                yield to_jsonl(ToolCallEndEvent(tool_call_id=tc_id))
                _count(state, "TOOL_CALL_RESULT")
                yield to_jsonl(ToolCallResultEvent(
                    tool_call_id=tc_id,
                    message_id=f"tool_result_{tc_id}",
                    content=_truncate_result(result_str),
                    role="tool",
                ))

        # Stream completed successfully
        _count(state, "RUN_FINISHED")
        logger.info(
            f"[AG-UI] Translation complete: thread_id={state.thread_id}, "
            f"run_id={state.run_id}, events={state.event_counts}"
        )
        yield to_jsonl(RunFinishedEvent(thread_id=state.thread_id, run_id=state.run_id))

    except Exception as exc:
        logger.error(f"[AG-UI] Error during event translation: {exc}", exc_info=True)
        # Close any open message
        if state.message_in_progress and state.current_message_id:
            _count(state, "TEXT_MESSAGE_END")
            yield to_jsonl(TextMessageEndEvent(message_id=state.current_message_id))
        _count(state, "RUN_ERROR")
        yield to_jsonl(RunErrorEvent(message=str(exc), code="stream_error"))
