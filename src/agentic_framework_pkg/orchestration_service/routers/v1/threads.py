"""
This module provides the /v1/threads API endpoints for the Orchestration Service.

DEPRECATED: The Threads API is deprecated as part of the Assistants API deprecation.
Please use /v1/responses/completions for new implementations.
This API is maintained for backward compatibility only.

It handles the creation of conversation threads and the messages within them,
persisting the conversation state to the database using the LangGraph checkpointer.
"""
import time
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, HTTPException, Response
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any

from langchain_core.messages import HumanMessage, AIMessage

from ...persistence_v2 import AsyncPostgresSaver
from ....core.auth import AuthCredentials
from ...auth import get_forwarded_user
from ....logger_config import get_logger
from ...hybrid_orchestration import hybrid_service

router = APIRouter()
logger = get_logger(__name__)

# Deprecation warning configuration
DEPRECATION_WARNING_HEADER = (
    '299 - "The Threads API is deprecated. '
    'Please migrate to Response API (/v1/responses/chat/completions). '
    'See: https://docs.adept.ai/migration/assistants-to-response"'
)

def add_deprecation_warning(response: Response, endpoint: str, user_id: str):
    """
    Add HTTP 299 deprecation warning header and log deprecated API usage.

    Args:
        response: FastAPI Response object
        endpoint: The endpoint path being accessed
        user_id: The user ID accessing the endpoint
    """
    response.headers["Warning"] = DEPRECATION_WARNING_HEADER
    response.headers["X-API-Deprecated"] = "true"
    response.headers["X-API-Deprecation-Date"] = "2025-12-16"
    response.headers["X-API-Sunset-Date"] = "2026-03-16"  # 3 months notice

    logger.warning(
        "DEPRECATED_API_USAGE",
        extra={
            "endpoint": endpoint,
            "user_id": user_id,
            "api": "threads",
            "migration_guide": "https://docs.adept.ai/migration/assistants-to-response",
            "deprecation_date": "2025-12-16",
            "sunset_date": "2026-03-16"
        }
    )

# --- Pydantic Models for OpenAI Compatibility ---

class ThreadModel(BaseModel):
    id: str
    object: str = "thread"
    created_at: int
    metadata: Optional[Dict] = None

    class Config:
        from_attributes = True

class ThreadUpdateRequest(BaseModel):
    metadata: Optional[Dict] = None

class MessageContentText(BaseModel):
    value: str
    annotations: List = []

class MessageContent(BaseModel):
    type: str = "text"
    text: MessageContentText

class MessageModel(BaseModel):
    id: str
    object: str = "thread.message"
    created_at: int
    thread_id: str
    role: str
    content: List[MessageContent]
    assistant_id: Optional[str] = None
    run_id: Optional[str] = None
    file_ids: List[str] = Field(default_factory=list)
    metadata: Optional[Dict] = None

    class Config:
        from_attributes = True

class MessageList(BaseModel):
    object: str = "list"
    data: List[MessageModel]

class MessageUpdateRequest(BaseModel):
    metadata: Optional[Dict] = None

# --- API Endpoints ---

@router.post("/", response_model=ThreadModel)
@router.post("", response_model=ThreadModel)
async def create_thread(response: Response, user: AuthCredentials = Depends(get_forwarded_user)):
    """Creates a new conversation thread and its initial empty checkpoint."""
    # Add deprecation warning to response
    add_deprecation_warning(response, "/v1/threads (POST)", user.user_id)

    logger.info(f"[ORCHESTRATION_SERVICE] Handling POST /v1/threads/ for user: {user.username}")
    thread_id = f"thread_{uuid.uuid4().hex}"
    created_at = int(time.time())

    checkpointer = hybrid_service.checkpointer  # Phase 2: Use shared singleton
    checkpoint_id = f"init_{uuid.uuid4().hex[:24]}"
    initial_checkpoint = {
        "v": 2,
        "id": checkpoint_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel_values": {"messages": []},
        "channel_versions": {"messages": "1"},
        "versions_seen": {},
        "pending_sends": [],
        "updated_channels": None,
    }
    await checkpointer.aput(
        config={"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint=initial_checkpoint,
        metadata={"owner_id": user.user_id, "created_at": created_at, "metadata": {}},
        new_versions={"messages": "1"},
    )
    
    logger.info(f"Created new thread '{thread_id}' for user '{user.user_id}'.")
    return ThreadModel(id=thread_id, created_at=created_at, metadata={})

class ThreadList(BaseModel):
    object: str = "list"
    data: List[ThreadModel]

@router.get("", response_model=ThreadList)
async def list_threads(user: AuthCredentials = Depends(get_forwarded_user)):
    """Lists all threads for the current user."""
    logger.info(f"[ORCHESTRATION_SERVICE] Handling GET /v1/threads/ for user: {user.username}")
    
    threads = []
    # TODO: Implement thread listing via checkpointer when needed
    
    logger.info(f"Listed {len(threads)} threads for user '{user.user_id}'.")
    return ThreadList(data=threads)

@router.get("/{thread_id}", response_model=ThreadModel)
async def get_thread(thread_id: str, user: AuthCredentials = Depends(get_forwarded_user)):
    checkpointer = hybrid_service.checkpointer  # Phase 2: Use shared singleton
    checkpoint_tuple = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    if not checkpoint_tuple or checkpoint_tuple.metadata.get("owner_id") != user.user_id:
        raise HTTPException(status_code=404, detail="Thread not found")
    return ThreadModel(
        id=thread_id,
        created_at=checkpoint_tuple.metadata.get("created_at", 0),
        metadata=checkpoint_tuple.metadata.get("metadata", {})
    )

@router.post("/{thread_id}", response_model=ThreadModel)
async def update_thread(
    thread_id: str,
    request: ThreadUpdateRequest,
    user: AuthCredentials = Depends(get_forwarded_user)
):
    """Updates a thread's metadata."""
    logger.info(f"[ORCHESTRATION_SERVICE] Handling POST /v1/threads/{thread_id} for user: {user.username}")
    
    checkpointer = hybrid_service.checkpointer  # Phase 2: Use shared singleton
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if not checkpoint_tuple or checkpoint_tuple.metadata.get("owner_id") != user.user_id:
        raise HTTPException(status_code=404, detail="Thread not found or permission denied.")
        
    checkpoint = checkpoint_tuple.checkpoint
    metadata = checkpoint_tuple.metadata
    
    metadata["metadata"] = request.metadata

    await checkpointer.aput(config, checkpoint, metadata, new_versions={})
    
    logger.info(f"Successfully updated metadata for thread '{thread_id}'.")
    return ThreadModel(
        id=thread_id,
        created_at=metadata.get("created_at", 0),
        metadata=metadata.get("metadata", {})
    )

@router.delete("/{thread_id}")
async def delete_thread(thread_id: str, user: AuthCredentials = Depends(get_forwarded_user)):
    """Deletes a thread and its associated checkpoint from the database."""
    logger.info(f"[ORCHESTRATION_SERVICE] Handling DELETE /v1/threads/{thread_id} for user: {user.username}")
    
    checkpointer = hybrid_service.checkpointer  # Phase 2: Use shared singleton
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if not checkpoint_tuple or checkpoint_tuple.metadata.get("owner_id") != user.user_id:
        raise HTTPException(status_code=404, detail="Thread not found or permission denied.")
        
    await checkpointer.adelete(config)
    
    logger.info(f"Successfully deleted thread '{thread_id}'.")
    return {"id": thread_id, "object": "thread.deleted", "deleted": True}

@router.post("/{thread_id}/messages", response_model=MessageModel)
async def create_message(
    thread_id: str,
    request: Request,
    user: AuthCredentials = Depends(get_forwarded_user)
):
    """Adds a message to an existing thread."""
    body = await request.json()
    role = body.get("role")
    content = body.get("content")
    
    if not role or not content or role != "user":
        raise HTTPException(status_code=400, detail="Only user messages can be added with this endpoint.")

    logger.info(f"Adding message to thread '{thread_id}' for user '{user.username}'")

    checkpointer = hybrid_service.checkpointer  # Phase 2: Use shared singleton
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}  # LangGraph requires checkpoint_ns

    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")
    
    checkpoint = checkpoint_tuple.checkpoint
    
    new_message = HumanMessage(content=content)
    checkpoint["channel_values"]["messages"].append(new_message)

    await checkpointer.aput(config, checkpoint, checkpoint_tuple.metadata, new_versions={})
    
    message_id = f"msg_{uuid.uuid4().hex}"
    created_at = int(time.time())
    
    response_message = MessageModel(
        id=message_id,
        thread_id=thread_id,
        created_at=created_at,
        role=role,
        content=[MessageContent(text=MessageContentText(value=content))]
    )
    
    logger.info(f"Successfully added message {message_id} to thread {thread_id}.")
    return response_message


@router.get("/{thread_id}/messages", response_model=MessageList)
async def list_messages(
    thread_id: str,
    user: AuthCredentials = Depends(get_forwarded_user)
):
    """Lists all messages in a given thread."""
    logger.info(f"Listing messages for thread '{thread_id}' for user '{user.username}'")
    
    checkpointer = hybrid_service.checkpointer  # Phase 2: Use shared singleton
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")

    messages_from_checkpoint = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
    
    response_data = []
    for msg in reversed(messages_from_checkpoint):
        if isinstance(msg, (HumanMessage, AIMessage)):
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            response_data.append(
                MessageModel(
                    id=f"msg_{uuid.uuid4().hex}",
                    thread_id=thread_id,
                    created_at=int(time.time()),
                    role=role,
                    content=[MessageContent(text=MessageContentText(value=msg.content))]
                )
            )
            
    return MessageList(data=response_data)

@router.get("/{thread_id}/messages/{message_id}", response_model=MessageModel)
async def retrieve_message(
    thread_id: str,
    message_id: str,
    user: AuthCredentials = Depends(get_forwarded_user)
):
    """Retrieves a specific message from a thread."""
    logger.info(f"Retrieving message '{message_id}' from thread '{thread_id}' for user '{user.username}'")
    
    checkpointer = hybrid_service.checkpointer  # Phase 2: Use shared singleton
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")

    messages_from_checkpoint = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
    if not messages_from_checkpoint:
        raise HTTPException(status_code=404, detail=f"Message '{message_id}' not found in thread '{thread_id}'.")

    latest_message = messages_from_checkpoint[-1]
    role = "user" if isinstance(latest_message, HumanMessage) else "assistant"
    
    return MessageModel(
        id=message_id,
        thread_id=thread_id,
        created_at=int(time.time()),
        role=role,
        content=[MessageContent(text=MessageContentText(value=latest_message.content))]
    )

@router.post("/{thread_id}/messages/{message_id}", response_model=MessageModel)
async def update_message(
    thread_id: str,
    message_id: str,
    request: MessageUpdateRequest,
    user: AuthCredentials = Depends(get_forwarded_user)
):
    """Updates a message's metadata."""
    logger.info(f"Updating message '{message_id}' in thread '{thread_id}' for user '{user.username}'")
    
    checkpointer = hybrid_service.checkpointer  # Phase 2: Use shared singleton
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")

    messages_from_checkpoint = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
    if not messages_from_checkpoint:
        raise HTTPException(status_code=404, detail=f"Message '{message_id}' not found.")

    latest_message = messages_from_checkpoint[-1]
    role = "user" if isinstance(latest_message, HumanMessage) else "assistant"

    return MessageModel(
        id=message_id,
        thread_id=thread_id,
        created_at=int(time.time()),
        role=role,
        content=[MessageContent(text=MessageContentText(value=latest_message.content))],
        metadata=request.metadata
    )