"""
This module provides the /v1/threads/{thread_id}/runs API endpoints for the Orchestration Service.

DEPRECATED: The Runs API is deprecated as part of the Assistants API deprecation.
Please use /v1/responses/completions for new implementations.
This API is maintained for backward compatibility only.

It handles the execution of agent runs.
"""

import time
import uuid
import asyncio
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, List

from ...persistence_v2 import AsyncPostgresSaver
from ...persistence import AsyncSessionLocal
from ....core.auth import AuthCredentials
from ...auth import get_forwarded_user
from ....logger_config import get_logger
from ...scientific_workflow.langchain_agent import ScientificWorkflowAgent
from ...hybrid_orchestration import (
    hybrid_service,
)  # Phase 3: Import shared checkpointer
from ...models import Assistant, Run, RunStep
from sqlalchemy.future import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

router = APIRouter()
logger = get_logger(__name__)


# Phase 3B.2: Session fork metadata for Runs API
class SessionForkMetadata(BaseModel):
    """
    Metadata about session fork event (Phase 3B).

    Returned when context truncation triggers sub-session forking.
    Clients should switch to forked_session_id for subsequent requests.
    """

    forked_session_id: str
    parent_session_id: str
    generation: int
    fork_reason: str
    bootstrap_message_count: int

    class Config:
        # Exclude None values from JSON response
        exclude_none = True


async def extract_user_input_from_thread(thread_id: str) -> str:
    """
    Extract the latest user message from a thread for execution.

    This maintains the conversation context from the checkpointer.
    """
    try:
        checkpointer = hybrid_service.checkpointer  # Phase 3: Use shared singleton
        checkpoint_tuple = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        )

        if checkpoint_tuple and checkpoint_tuple.checkpoint.get(
            "channel_values", {}
        ).get("messages"):
            messages = checkpoint_tuple.checkpoint["channel_values"]["messages"]
            # Find the latest human message
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    logger.info(
                        f"[EXTRACT_INPUT] Found user input from thread '{thread_id}': '{msg.content[:100]}...'"
                    )
                    return msg.content

        logger.warning(
            f"[EXTRACT_INPUT] No user message found in thread '{thread_id}', using default"
        )
        return "Continue the conversation."

    except Exception as e:
        logger.error(
            f"[EXTRACT_INPUT] Failed to extract user input from thread '{thread_id}': {e}"
        )
        return "Hello"


async def extract_conversation_history_from_thread(
    thread_id: str,
) -> List[Dict[str, str]]:
    """
    Extract conversation history from thread for multi-tier session context.

    This ensures the enhanced invoke maintains full conversation context
    and supports multi-tier session management (session_id, mcp_session_id, etc.)
    """
    try:
        checkpointer = hybrid_service.checkpointer  # Phase 3: Use shared singleton
        checkpoint_tuple = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        )

        chat_history = []
        if checkpoint_tuple and checkpoint_tuple.checkpoint.get(
            "channel_values", {}
        ).get("messages"):
            messages = checkpoint_tuple.checkpoint["channel_values"]["messages"]
            # Convert to chat history format (excluding the last message which becomes user_input)
            for msg in messages[:-1]:  # Exclude last message
                if isinstance(msg, HumanMessage):
                    chat_history.append({"role": "user", "content": msg.content})
                elif isinstance(msg, AIMessage):
                    # Handle AIMessage with potential tool calls
                    message_data = {"role": "assistant", "content": msg.content}
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        message_data["tool_calls"] = msg.tool_calls
                    chat_history.append(message_data)
                elif isinstance(msg, ToolMessage):
                    # Include tool messages to maintain OpenAI conversation format
                    chat_history.append(
                        {
                            "role": "tool",
                            "content": msg.content,
                            "tool_call_id": getattr(msg, "tool_call_id", "unknown"),
                        }
                    )

        logger.info(
            f"[EXTRACT_HISTORY] Extracted {len(chat_history)} conversation turns from thread '{thread_id}'"
        )
        return chat_history

    except Exception as e:
        logger.error(
            f"[EXTRACT_HISTORY] Failed to extract conversation history from thread '{thread_id}': {e}"
        )
        return []


class RunModel(BaseModel):
    id: str
    object: str = "thread.run"
    thread_id: str
    assistant_id: str
    status: str
    created_at: int
    model: str
    instructions: str
    tools: List[Dict] = []
    metadata: Optional[Dict] = Field(None, alias="metadata_")
    session_fork: Optional[SessionForkMetadata] = None  # Phase 3B.2: Fork metadata

    class Config:
        from_attributes = True
        exclude_none = True  # Exclude None values from JSON response


class RunCreateRequest(BaseModel):
    assistant_id: str


async def execute_run_background(
    thread_id: str, assistant_id: str, run_id: str, user: AuthCredentials
):
    """The actual agent execution logic that runs in the background."""
    logger.info(
        f"[AGENT_EXECUTION] Starting background execution for run '{run_id}' on thread '{thread_id}'."
    )

    async with AsyncSessionLocal() as session:
        async with session.begin():
            try:
                logger.info(
                    f"[AGENT_EXECUTION] Setting run '{run_id}' status to 'in_progress'..."
                )
                # Set status to in_progress
                await session.execute(
                    update(Run).where(Run.id == run_id).values(status="in_progress")
                )
                logger.info(
                    f"[AGENT_EXECUTION] Run '{run_id}' status updated to 'in_progress'."
                )

                logger.info(
                    f"[AGENT_EXECUTION] Initializing checkpointer for thread '{thread_id}'..."
                )
                # Fetch the latest message from the thread to use as input
                checkpointer = (
                    hybrid_service.checkpointer
                )  # Phase 3: Use shared singleton
                logger.info(
                    f"[AGENT_EXECUTION] Fetching checkpoint tuple for thread '{thread_id}'..."
                )
                checkpoint_tuple = await checkpointer.aget_tuple(
                    {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
                )
                logger.info(
                    f"[AGENT_EXECUTION] Checkpoint tuple result: {checkpoint_tuple is not None}"
                )

                from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

                if checkpoint_tuple and checkpoint_tuple.checkpoint.get(
                    "channel_values", {}
                ).get("messages"):
                    # Existing thread with message history - extract for agent context
                    messages = checkpoint_tuple.checkpoint["channel_values"]["messages"]
                    last_message = messages[-1] if messages else None
                    history_for_agent = messages[:-1] if messages else []
                    logger.info(
                        f"[AGENT_EXECUTION] Found {len(messages)} existing messages in thread '{thread_id}'. Last message type: {type(last_message).__name__ if last_message else None}"
                    )
                else:
                    # Fresh thread or no message history yet - start with empty context
                    messages = []
                    last_message = None
                    history_for_agent = []
                    logger.info(
                        f"[AGENT_EXECUTION] No message history found for thread '{thread_id}' - starting fresh"
                    )

                if not last_message or not isinstance(last_message, HumanMessage):
                    logger.warning(
                        f"[AGENT_EXECUTION] Run '{run_id}' started, but the last message in thread '{thread_id}' is not from a user. Proceeding with empty input."
                    )
                    user_input_for_agent = ""
                    if last_message:
                        history_for_agent.append(last_message)
                else:
                    user_input_for_agent = last_message.content
                    logger.info(
                        f"[AGENT_EXECUTION] Extracted user input for agent: '{user_input_for_agent[:100]}...'"
                    )

                # Convert LangChain messages to the dict format arun expects for chat_history
                logger.info(
                    f"[AGENT_EXECUTION] Converting {len(history_for_agent)} messages to chat history format..."
                )
                chat_history_for_arun = []
                for msg in history_for_agent:
                    if isinstance(msg, HumanMessage):
                        chat_history_for_arun.append(
                            {"role": "user", "content": msg.content}
                        )
                    elif isinstance(msg, AIMessage):
                        # Handle AIMessage with potential tool calls
                        message_data = {"role": "assistant", "content": msg.content}
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            message_data["tool_calls"] = msg.tool_calls
                            logger.info(
                                f"[AGENT_EXECUTION] Including {len(msg.tool_calls)} tool_calls in AIMessage"
                            )
                        chat_history_for_arun.append(message_data)
                    elif isinstance(msg, ToolMessage):
                        # Include tool messages to maintain OpenAI conversation format
                        tool_msg = {
                            "role": "tool",
                            "content": msg.content,
                            "tool_call_id": getattr(msg, "tool_call_id", "unknown"),
                        }
                        chat_history_for_arun.append(tool_msg)
                        logger.info(
                            f"[AGENT_EXECUTION] Including ToolMessage with tool_call_id: {tool_msg['tool_call_id']}"
                        )
                    else:
                        logger.warning(
                            f"[AGENT_EXECUTION] Skipping unknown message type: {type(msg).__name__}"
                        )
                logger.info(
                    f"[AGENT_EXECUTION] Converted chat history contains {len(chat_history_for_arun)} messages."
                )

                # Enhanced validation: Check for tool_calls pairing issues
                logger.info(
                    "[AGENT_EXECUTION] Validating tool_calls pairing in chat history..."
                )
                try:
                    _validate_tool_calls_pairing(chat_history_for_arun)
                    logger.info(
                        "[AGENT_EXECUTION] Tool_calls pairing validation passed."
                    )
                except ValueError as e:
                    logger.error(
                        f"[AGENT_EXECUTION] Tool_calls pairing validation failed: {e}"
                    )
                    # Continue execution but log the issue for debugging
                    logger.warning(
                        "[AGENT_EXECUTION] Continuing execution despite tool_calls pairing issue..."
                    )

                logger.info(
                    f"[AGENT_EXECUTION] Fetching assistant config for assistant '{assistant_id}'..."
                )
                result = await session.execute(
                    select(Assistant).where(Assistant.id == assistant_id)
                )
                assistant_config = result.scalars().first()

                if not assistant_config:
                    raise ValueError(f"Assistant with ID '{assistant_id}' not found.")

                logger.info(
                    f"[AGENT_EXECUTION] Assistant config found: model={assistant_config.model}, instructions length={len(assistant_config.instructions or '') if assistant_config.instructions else 0}"
                )

                logger.info(
                    "[AGENT_EXECUTION] Creating ScientificWorkflowAgent instance..."
                )
                agent = await ScientificWorkflowAgent.create(
                    mcp_session_id=thread_id,
                    thread_id_override=thread_id,
                    checkpointer=checkpointer,
                    user_credentials=user,
                    system_prompt_override=assistant_config.instructions,
                )
                logger.info(
                    f"[AGENT_EXECUTION] ScientificWorkflowAgent created successfully. Tool count: {len(agent.tools)}"
                )

                logger.info(
                    f"[AGENT_EXECUTION] Starting agent.arun execution with user_input='{user_input_for_agent}', chat_history_len={len(chat_history_for_arun)}"
                )
                result = await agent.arun(
                    user_input=user_input_for_agent, chat_history=chat_history_for_arun
                )
                logger.info(
                    f"[AGENT_EXECUTION] Agent.arun completed successfully with output length: {len(result.get('output', '')) if result else 0}"
                )

                logger.info(
                    f"[AGENT_EXECUTION] Setting run '{run_id}' status to 'completed'..."
                )
                await session.execute(
                    update(Run).where(Run.id == run_id).values(status="completed")
                )
                logger.info(
                    f"[AGENT_EXECUTION] Background execution for run '{run_id}' completed successfully."
                )

            except Exception as e:
                logger.error(
                    f"[AGENT_EXECUTION] Background execution for run '{run_id}' failed at step: {e}",
                    exc_info=True,
                )
                # The transaction will be rolled back by the context manager
                # We need to update the status to failed in a separate transaction
                logger.info(
                    f"[AGENT_EXECUTION] Setting run '{run_id}' status to 'failed'..."
                )

    # Handle the failure status update in a separate transaction to ensure it's committed
    if "e" in locals():  # If there was an exception
        async with AsyncSessionLocal() as failure_session:
            async with failure_session.begin():
                logger.info(
                    f"[AGENT_EXECUTION] Updating failed run '{run_id}' status in separate transaction..."
                )
                await failure_session.execute(
                    update(Run).where(Run.id == run_id).values(status="failed")
                )
                logger.info(
                    f"[AGENT_EXECUTION] Run '{run_id}' marked as failed in separate transaction."
                )


@router.post("", response_model=RunModel)
async def create_run(
    thread_id: str,
    request: RunCreateRequest,
    user: AuthCredentials = Depends(get_forwarded_user),
):
    logger.info(
        f"[ORCHESTRATION_SERVICE] Creating run for thread '{thread_id}' with assistant '{request.assistant_id}' - UNIFIED EXECUTION"
    )

    run_id = f"run_{uuid.uuid4().hex}"
    created_at = int(time.time())

    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(Assistant).where(Assistant.id == request.assistant_id)
            )
            assistant_config = result.scalars().first()
            if not assistant_config:
                raise HTTPException(
                    status_code=404,
                    detail=f"Assistant with ID '{request.assistant_id}' not found.",
                )

            # Create run in "in_progress" status (will complete synchronously)
            new_run = Run(
                id=run_id,
                thread_id=thread_id,
                assistant_id=request.assistant_id,
                status="in_progress",  # Start as in_progress since we'll complete synchronously
                created_at=created_at,
                model=assistant_config.model,
                instructions=assistant_config.instructions,
                tools=assistant_config.tools,
                metadata_={},
                owner_id=user.user_id,
            )

            session.add(new_run)
            await session.flush()
            await session.refresh(new_run)

    try:
        # Extract user input from thread's latest message
        user_input = await extract_user_input_from_thread(thread_id)

        # Import the enhanced invoke function from app.py
        from ...app import enhanced_invoke_agent

        # Execute synchronously via enhanced invoke (no background tasks!)
        logger.info(
            f"[UNIFIED_EXECUTION] Executing run '{run_id}' synchronously via enhanced_invoke_agent"
        )

        # Extract conversation history for session context
        chat_history = await extract_conversation_history_from_thread(thread_id)

        result = await enhanced_invoke_agent(
            user_input=user_input,
            thread_id=thread_id,
            assistant_id=request.assistant_id,
            user=user,
            chat_history=chat_history,
            context={"run_id": run_id, "execution_mode": "assistant_api"},
        )

        # Phase 3B.2: Extract fork metadata from result
        full_graph_state = result.get("full_graph_state", {})
        forked_session_id = full_graph_state.get("forked_session_id")
        fork_metadata_dict = full_graph_state.get("fork_metadata")

        # Build run metadata with fork information
        run_metadata = {
            "output_length": len(result.get("output", "")),
            "execution_type": "unified",
        }

        # Phase 3B.2: Add fork metadata to run metadata if fork occurred
        session_fork = None
        if forked_session_id and fork_metadata_dict:
            logger.info(
                f"[FORK_PROPAGATION_RUNS] Session forked: {thread_id} -> {forked_session_id}, "
                f"generation={fork_metadata_dict.get('generation')}, "
                f"reason={fork_metadata_dict.get('fork_reason')}"
            )
            run_metadata["forked_session_id"] = forked_session_id
            run_metadata["parent_session_id"] = fork_metadata_dict.get(
                "parent_session_id", thread_id
            )
            run_metadata["fork_generation"] = fork_metadata_dict.get("generation", 0)
            run_metadata["fork_reason"] = fork_metadata_dict.get(
                "fork_reason", "unknown"
            )
            run_metadata["bootstrap_message_count"] = fork_metadata_dict.get(
                "bootstrap_message_count", 0
            )

            # Build SessionForkMetadata for response
            session_fork = SessionForkMetadata(
                forked_session_id=forked_session_id,
                parent_session_id=fork_metadata_dict.get(
                    "parent_session_id", thread_id
                ),
                generation=fork_metadata_dict.get("generation", 0),
                fork_reason=fork_metadata_dict.get("fork_reason", "unknown"),
                bootstrap_message_count=fork_metadata_dict.get(
                    "bootstrap_message_count", 0
                ),
            )

        # Update run to completed status with fork metadata
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(status="completed", metadata_=run_metadata)
                )

        logger.info(
            f"[UNIFIED_EXECUTION] Run '{run_id}' completed successfully with unified execution"
        )

        # Return the completed run with fork metadata
        new_run.status = "completed"
        new_run.metadata_ = run_metadata
        run_model = RunModel.model_validate(new_run)
        run_model.session_fork = (
            session_fork  # Phase 3B.2: Add fork metadata to response
        )
        return run_model

    except Exception as e:
        logger.error(f"[UNIFIED_EXECUTION] Run '{run_id}' failed: {e}", exc_info=True)

        # Update run to failed status
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(
                        status="failed",
                        metadata_={"error": str(e), "execution_type": "unified"},
                    )
                )

        new_run.status = "failed"
        return RunModel.model_validate(new_run)


class ToolOutput(BaseModel):
    tool_call_id: str
    output: str


class SubmitToolOutputsRequest(BaseModel):
    tool_outputs: List[ToolOutput]


@router.post("/{run_id}/submit_tool_outputs", response_model=RunModel)
async def submit_tool_outputs(
    thread_id: str,
    run_id: str,
    request: SubmitToolOutputsRequest,
    user: AuthCredentials = Depends(get_forwarded_user),
):
    logger.info(f"[ORCHESTRATION_SERVICE] Submitting tool outputs for run '{run_id}'")

    logger.info(f"Tool outputs for run {run_id}: {request.tool_outputs}")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = (
                update(Run)
                .where(Run.id == run_id)
                .where(Run.owner_id == user.user_id)
                .values(status="completed")
                .returning(Run)
            )
            result = await session.execute(stmt)
            updated_run = result.scalars().first()

            if not updated_run:
                raise HTTPException(
                    status_code=404, detail="Run not found or permission denied."
                )

    return RunModel.model_validate(updated_run)


class RunList(BaseModel):
    object: str = "list"
    data: List[RunModel]


@router.post("/{run_id}/cancel", response_model=RunModel)
async def cancel_run(
    thread_id: str, run_id: str, user: AuthCredentials = Depends(get_forwarded_user)
):
    logger.info(f"[ORCHESTRATION_SERVICE] Cancelling run '{run_id}'")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = (
                update(Run)
                .where(Run.id == run_id)
                .where(Run.owner_id == user.user_id)
                .values(status="cancelled")
                .returning(Run)
            )
            result = await session.execute(stmt)
            updated_run = result.scalars().first()

            if not updated_run:
                raise HTTPException(
                    status_code=404, detail="Run not found or permission denied."
                )

    return RunModel.model_validate(updated_run)


class RunStepModel(BaseModel):
    id: str
    object: str = "thread.run.step"
    run_id: str
    thread_id: str
    assistant_id: str
    status: str
    step_details: Dict
    last_error: Optional[Dict]
    created_at: int
    completed_at: Optional[int]
    failed_at: Optional[int]
    cancelled_at: Optional[int]
    expires_at: Optional[int]
    metadata: Optional[Dict] = Field(None, alias="metadata_")

    class Config:
        from_attributes = True


class RunStepList(BaseModel):
    object: str = "list"
    data: List[RunStepModel]


@router.get("/{run_id}/steps", response_model=RunStepList)
async def list_run_steps(
    thread_id: str, run_id: str, user: AuthCredentials = Depends(get_forwarded_user)
):
    logger.info(f"[ORCHESTRATION_SERVICE] Listing run steps for run '{run_id}'")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RunStep)
            .where(RunStep.run_id == run_id)
            .where(RunStep.thread_id == thread_id)
            .where(RunStep.owner_id == user.user_id)
        )
        run_steps_list = result.scalars().all()

    return RunStepList(
        data=[RunStepModel.model_validate(run_step) for run_step in run_steps_list]
    )


@router.get("/{run_id}/steps/{step_id}", response_model=RunStepModel)
async def retrieve_run_step(
    thread_id: str,
    run_id: str,
    step_id: str,
    user: AuthCredentials = Depends(get_forwarded_user),
):
    logger.info(
        f"[ORCHESTRATION_SERVICE] Retrieving run step '{step_id}' for run '{run_id}'"
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RunStep)
            .where(RunStep.id == step_id)
            .where(RunStep.run_id == run_id)
            .where(RunStep.thread_id == thread_id)
            .where(RunStep.owner_id == user.user_id)
        )
        run_step = result.scalars().first()

    if not run_step:
        raise HTTPException(status_code=404, detail="Run step not found")

    return RunStepModel.model_validate(run_step)


@router.get("", response_model=RunList)
async def list_runs(
    thread_id: str, user: AuthCredentials = Depends(get_forwarded_user)
):
    logger.info(f"[ORCHESTRATION_SERVICE] Listing runs for thread '{thread_id}'")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Run)
            .where(Run.thread_id == thread_id)
            .where(Run.owner_id == user.user_id)
        )
        runs_list = result.scalars().all()

    return RunList(data=[RunModel.model_validate(run) for run in runs_list])


@router.get("/{run_id}", response_model=RunModel)
async def retrieve_run(
    thread_id: str, run_id: str, user: AuthCredentials = Depends(get_forwarded_user)
):
    logger.info(
        f"[ORCHESTRATION_SERVICE] Retrieving run '{run_id}' for thread '{thread_id}'"
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Run)
            .where(Run.id == run_id)
            .where(Run.thread_id == thread_id)
            .where(Run.owner_id == user.user_id)
        )
        run = result.scalars().first()

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Phase 3B.2: Extract fork metadata from run metadata if present
    run_model = RunModel.model_validate(run)
    if run.metadata_ and "forked_session_id" in run.metadata_:
        logger.info(
            f"[FORK_METADATA_RETRIEVE] Run '{run_id}' contains fork metadata: "
            f"forked_session={run.metadata_.get('forked_session_id')}, "
            f"generation={run.metadata_.get('fork_generation')}"
        )
        run_model.session_fork = SessionForkMetadata(
            forked_session_id=run.metadata_["forked_session_id"],
            parent_session_id=run.metadata_.get("parent_session_id", thread_id),
            generation=run.metadata_.get("fork_generation", 0),
            fork_reason=run.metadata_.get("fork_reason", "unknown"),
            bootstrap_message_count=run.metadata_.get("bootstrap_message_count", 0),
        )

    return run_model


def _validate_tool_calls_pairing(chat_history: List[Dict]) -> None:
    """
    Validate that every assistant message with tool_calls has corresponding tool messages.

    Args:
        chat_history: List of message dictionaries in OpenAI format

    Raises:
        ValueError: If tool_calls are not properly paired with tool responses
    """
    pending_tool_calls = {}  # tool_call_id -> assistant_message_index

    for i, msg in enumerate(chat_history):
        role = msg.get("role", "")

        if role == "assistant" and "tool_calls" in msg:
            # Record all tool_calls that need responses
            for tool_call in msg["tool_calls"]:
                tool_call_id = tool_call.get("id")
                if tool_call_id:
                    pending_tool_calls[tool_call_id] = i

        elif role == "tool":
            # Mark this tool_call_id as responded to
            tool_call_id = msg.get("tool_call_id")
            if tool_call_id and tool_call_id in pending_tool_calls:
                del pending_tool_calls[tool_call_id]

    # Check if any tool_calls remain unresponded
    if pending_tool_calls:
        missing_ids = list(pending_tool_calls.keys())
        raise ValueError(
            f"Assistant messages with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'. "
            f"The following tool_call_ids did not have response messages: {', '.join(missing_ids)}"
        )
