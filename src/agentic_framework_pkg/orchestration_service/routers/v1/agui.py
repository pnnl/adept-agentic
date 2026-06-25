"""AG-UI Protocol Router - Orchestration Service

Provides a ``POST /run`` endpoint that streams real-time JSONL events from
the LangGraph agent execution pipeline using ``astream_events(v2)``.

Wire format: newline-delimited JSON (one AG-UI event per line).
"""

import os
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func

from ....core.auth import AuthCredentials
from ...auth import get_forwarded_user
from ....logger_config import get_logger
from ...hybrid_orchestration import hybrid_service
from ...agui.event_translator import translate_langgraph_to_agui
from ...agui.protocol import MetaEvent
from ...persistence import get_async_session
from ...models.session_models import SessionMessage

router = APIRouter()
logger = get_logger(__name__)


class AGUIRunRequest(BaseModel):
    thread_id: str
    messages: List[Dict[str, Any]]
    model: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    state: Optional[Dict[str, Any]] = None


async def _get_next_message_index(session_id: str) -> int:
    """Get the next available message index for a session."""
    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(func.max(SessionMessage.message_index)).where(
                    SessionMessage.session_id == session_id
                )
            )
            max_index = result.scalar()
            return (max_index or -1) + 1
    except Exception as e:
        logger.error(f"[AG-UI] Failed to get next message index for {session_id}: {e}")
        return 0


async def _persist_post_stream(
    agent,
    session_id: str,
    mcp_session: str,
    user_input: str,
    model_name: str,
    run_id: str,
    user: AuthCredentials,
) -> None:
    """Post-stream persistence: messages, tool outputs, cost tracking.

    Non-blocking -- all errors are logged and swallowed. The stream has
    already completed successfully; these are supplementary operations.
    """
    if os.getenv("SESSION_PERSISTENCE_ENABLED", "false").lower() != "true":
        logger.debug("[AG-UI] SESSION_PERSISTENCE_ENABLED is false, skipping post-stream persistence")
        return

    try:
        checkpoint_tuple = await agent.checkpointer.aget_tuple(
            {"configurable": {"thread_id": session_id}}
        )
        if not checkpoint_tuple or not checkpoint_tuple.checkpoint:
            logger.warning(f"[AG-UI] No checkpoint found for thread_id={session_id}, skipping persistence")
            return

        cv = checkpoint_tuple.checkpoint.get("channel_values", {})

        # --- R2: Save full tool outputs ---
        full_tool_outputs = cv.get("full_tool_outputs", [])
        if full_tool_outputs:
            try:
                await agent.checkpointer.save_tool_outputs(
                    thread_id=session_id,
                    checkpoint_id=f"agui_{uuid.uuid4().hex[:24]}",
                    full_outputs=full_tool_outputs,
                    config={
                        "configurable": {
                            "session_id": session_id,
                            "mcp_session_id": mcp_session,
                        }
                    },
                )
                logger.info(f"[AG-UI] Saved {len(full_tool_outputs)} tool outputs for thread_id={session_id}")
            except Exception as e:
                logger.error(f"[AG-UI] Failed to save tool outputs: {e}", exc_info=True)

        # --- R1: Save user + assistant messages ---
        assistant_content = ""
        tool_call_ids = []
        try:
            messages = cv.get("messages", [])

            # Extract tool_call_ids and last AI message without tool_calls
            for msg in reversed(messages):
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_call_ids.extend(
                        tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                        for tc in msg.tool_calls
                    )
                if hasattr(msg, "type") and msg.type == "ai":
                    if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                        if not assistant_content:
                            assistant_content = msg.content if hasattr(msg, "content") else str(msg)

            message_index = await _get_next_message_index(session_id)

            await hybrid_service.session_manager.persistence.save_message(
                session_id=session_id,
                message_role="user",
                message_content=user_input,
                message_index=message_index,
                context_layer="active",
                message_metadata={
                    "source": "agui",
                    "api_type": "ag-ui",
                    "run_id": run_id,
                },
            )

            await hybrid_service.session_manager.persistence.save_message(
                session_id=session_id,
                message_role="assistant",
                message_content=assistant_content,
                message_index=message_index + 1,
                tool_call_ids=tool_call_ids if tool_call_ids else None,
                context_layer="active",
                message_metadata={
                    "source": "agui",
                    "api_type": "ag-ui",
                    "run_id": run_id,
                    "model": model_name,
                },
            )
            logger.info(
                f"[AG-UI] Persisted 2 messages for thread_id={session_id} at index {message_index}"
            )
        except Exception as e:
            logger.error(f"[AG-UI] Failed to persist messages: {e}", exc_info=True)

        # --- R4: Session cost tracking ---
        try:
            prompt_tokens = len(user_input.split())
            completion_tokens = len(assistant_content.split()) if assistant_content else 0
            total_tokens = prompt_tokens + completion_tokens
            estimated_cost = total_tokens * 0.00003  # Simplified estimate

            await hybrid_service.session_manager.persistence.update_session_cost(
                session_id=session_id, tokens=total_tokens, cost=estimated_cost
            )
            logger.info(
                f"[AG-UI] Cost tracking: thread_id={session_id}, tokens={total_tokens}, cost=${estimated_cost:.6f}"
            )
        except Exception as e:
            logger.error(f"[AG-UI] Failed to update session cost: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"[AG-UI] Post-stream persistence failed: {e}", exc_info=True)


@router.post("/run")
async def agui_run(
    request: AGUIRunRequest,
    http_request: Request,
    user: AuthCredentials = Depends(get_forwarded_user),
):
    """Stream AG-UI JSONL events for a single agent turn.

    Returns a ``text/plain`` streaming response where each line is a JSON
    object representing an AG-UI event.
    """
    logger.info(
        f"[AG-UI] Processing run for user={user.username}, thread_id={request.thread_id}"
    )

    # Session context (reuses pattern from responses.py:268-330)
    session_id = request.thread_id

    # Fork resolution
    from ...context_compaction_fork_mapping import resolve_fork

    original_session_id = session_id
    resolved_session_id = await resolve_fork(session_id)
    if resolved_session_id != session_id:
        logger.info(f"[AG-UI] Fork resolved: {session_id} -> {resolved_session_id}")
        session_id = resolved_session_id

    mcp_session = original_session_id

    # Build request context for agent pool lookup
    request_context = {
        "thread_id": session_id,
        "session_id": session_id,
        "mcp_session_id": mcp_session,
        "multi_agent_session_id": None,
        "gateway_session_id": None,
        "user_credentials": user,
        "interaction_type": "agui",
    }

    try:
        agent = await hybrid_service.invoke_agent_openai_compat(request_context)
    except Exception as e:
        logger.error(f"[AG-UI] Failed to get agent: {e}", exc_info=True)
        # D6.3 hardening: Do not expose internal error details to clients
        raise HTTPException(status_code=500, detail="Agent initialization failed. Please try again.")

    # Build chat history from all but last message
    chat_history = []
    if request.messages and len(request.messages) > 1:
        for msg in request.messages[:-1]:
            chat_history.append(
                {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            )

    run_id = f"run_{uuid.uuid4().hex[:12]}"

    # Extract user input for persistence
    user_input = ""
    if request.messages:
        user_input = request.messages[-1].get("content", "")

    model_name = request.model or "agentic-framework:scientific-agent-v1"

    async def generate():
        start_time = time.monotonic()
        event_count = 0
        try:
            events_iter = agent.astream_agui(
                messages=request.messages,
                thread_id=session_id,
                chat_history=chat_history,
            )
            async for line in translate_langgraph_to_agui(
                events_iter, thread_id=session_id, run_id=run_id
            ):
                event_count += 1
                yield line

            # --- R3: Fork metadata MetaEvent (after RUN_FINISHED) ---
            try:
                checkpoint_tuple = await agent.checkpointer.aget_tuple(
                    {"configurable": {"thread_id": session_id}}
                )
                if checkpoint_tuple and checkpoint_tuple.checkpoint:
                    cv = checkpoint_tuple.checkpoint.get("channel_values", {})
                    forked_session_id = cv.get("forked_session_id")
                    fork_metadata_dict = cv.get("fork_metadata")
                    if forked_session_id and fork_metadata_dict:
                        logger.info(
                            f"[AG-UI] Fork detected: {session_id} -> {forked_session_id}, "
                            f"generation={fork_metadata_dict.get('generation')}"
                        )
                        yield MetaEvent(
                            key="session_fork",
                            value={
                                "forked_session_id": forked_session_id,
                                "parent_session_id": fork_metadata_dict.get("parent_session_id", ""),
                                "generation": fork_metadata_dict.get("generation", 0),
                                "fork_reason": fork_metadata_dict.get("fork_reason", "unknown"),
                                "bootstrap_message_count": fork_metadata_dict.get("bootstrap_message_count", 0),
                            },
                        ).to_jsonl()
                        event_count += 1
            except Exception as e:
                logger.error(f"[AG-UI] Fork metadata check failed: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"[AG-UI] Stream generation error: {e}", exc_info=True)
            from ...agui.protocol import RunErrorEvent
            yield RunErrorEvent(message=str(e), code="stream_error").model_dump_json(by_alias=True, exclude_none=True) + "\n"
        finally:
            elapsed = time.monotonic() - start_time
            logger.info(
                f"[AG-UI] Stream completed: thread_id={session_id}, "
                f"run_id={run_id}, events={event_count}, "
                f"elapsed={elapsed:.2f}s, user={user.username}"
            )

            # --- Post-stream persistence (R1, R2, R4) ---
            await _persist_post_stream(
                agent=agent,
                session_id=session_id,
                mcp_session=mcp_session,
                user_input=user_input,
                model_name=model_name,
                run_id=run_id,
                user=user,
            )

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )
