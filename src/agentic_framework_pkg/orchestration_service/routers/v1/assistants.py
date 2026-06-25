"""
This module provides the /v1/assistants API endpoints for the Orchestration Service.

DEPRECATED: The Assistants API is deprecated in favor of the Responses API.
Please use /v1/responses/completions for new implementations.
This API is maintained for backward compatibility only.
"""
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from functools import wraps

from ....core.auth import AuthCredentials
from ...auth import get_forwarded_user
from ...config import AGENT_CONFIGURATIONS
from ....logger_config import get_logger
from ...persistence import AsyncSessionLocal, Assistant
from sqlalchemy.future import select
from sqlalchemy import delete, update, func
from sqlalchemy.dialects.postgresql import insert
from ...openai_pagination import OpenAIPaginatedResponse, get_pagination_params, OpenAIPaginator, OpenAIPaginationParams

router = APIRouter()
logger = get_logger(__name__)

# Deprecation warning configuration
DEPRECATION_WARNING_HEADER = (
    '299 - "The Assistants API is deprecated. '
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
            "api": "assistants",
            "migration_guide": "https://docs.adept.ai/migration/assistants-to-response",
            "deprecation_date": "2025-12-16",
            "sunset_date": "2026-03-16"
        }
    )

class AssistantModel(BaseModel):
    id: str
    object: str = "assistant"
    created_at: int
    name: Optional[str] = None
    description: Optional[str] = None
    model: str
    instructions: Optional[str] = None
    tools: List[Dict] = []
    # OpenAI API compatibility fields
    file_ids: List[str] = []
    metadata_: Optional[Dict[str, Any]] = Field(None, alias="metadata")

    class Config:
        from_attributes = True
        populate_by_name = True  # Allow both field name and alias

class AssistantList(OpenAIPaginatedResponse[AssistantModel]):
    pass

class AssistantCreateRequest(BaseModel):
    model: str
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = Field(None)
    tools: List[Dict] = Field([])
    # OpenAI API compatibility - additional fields
    file_ids: Optional[List[str]] = Field([], description="List of file IDs attached to assistant")
    metadata_: Optional[Dict[str, Any]] = Field(None, alias="metadata", description="Set of 16 key-value pairs")

@router.post("", response_model=AssistantModel)
async def create_assistant(
    request: AssistantCreateRequest,
    response: Response,
    user: AuthCredentials = Depends(get_forwarded_user)
):
    # Add deprecation warning to response
    add_deprecation_warning(response, "/v1/assistants (POST)", user.user_id)

    logger.info(f"[ORCHESTRATION_SERVICE] Handling POST /v1/assistants/ for user: {user.username}")
    
    if request.model not in AGENT_CONFIGURATIONS:
        from ...openai_error_handler import OpenAIErrorFormatter
        error_response = OpenAIErrorFormatter.format_error(
            message=f"The model '{request.model}' does not exist",
            type="invalid_request_error",
            param="model",
            code="model_not_found"
        )
        raise HTTPException(status_code=400, detail=error_response)
    
    assistant_id = f"asst_{uuid.uuid4().hex}"
    created_at = int(time.time())
    
    assistant_data = {
        "id": assistant_id,
        "created_at": created_at,
        "name": request.name,
        "description": request.description,
        "model": request.model,
        "instructions": request.instructions,
        "tools": request.tools,
        "file_ids": request.file_ids or [],
        "metadata_": request.metadata_,
        "owner_id": user.user_id
    }

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Use ORM approach instead of raw insert for SQLAlchemy 2.0 compatibility
            assistant_obj = Assistant(
                id=assistant_id,
                created_at=created_at,
                name=request.name,
                description=request.description,
                model=request.model,
                instructions=request.instructions,
                tools=request.tools,
                owner_id=user.user_id,
                # OpenAI API compatibility fields
                file_ids=request.file_ids or [],
                metadata_=request.metadata_
            )
            session.add(assistant_obj)
    
    logger.info(f"Successfully created and persisted assistant '{assistant_id}' for user '{user.user_id}'.")
    return AssistantModel(**assistant_data)

class AssistantUpdateRequest(BaseModel):
    model: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    tools: Optional[List[Dict]] = None
    # OpenAI API compatibility fields
    file_ids: Optional[List[str]] = None
    metadata_: Optional[Dict[str, Any]] = Field(None, alias="metadata")

@router.post("/{assistant_id}", response_model=AssistantModel)
async def update_assistant(
    assistant_id: str,
    request: AssistantUpdateRequest,
    response: Response,
    user: AuthCredentials = Depends(get_forwarded_user)
):
    # Add deprecation warning to response
    add_deprecation_warning(response, f"/v1/assistants/{assistant_id} (POST)", user.user_id)

    logger.info(f"Updating assistant {assistant_id} for user {user.username}")
    
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(Assistant).where(Assistant.id == assistant_id).where(Assistant.owner_id == user.user_id)
            )
            assistant = result.scalars().first()

            if not assistant:
                from ...openai_error_handler import OpenAIErrorFormatter
                error_response = OpenAIErrorFormatter.format_error(
                    message="Assistant not found or permission denied",
                    type="not_found_error",
                    code="assistant_not_found"
                )
                raise HTTPException(status_code=404, detail=error_response)

            update_data = request.dict(exclude_unset=True)
            
            if not update_data:
                return AssistantModel.model_validate(assistant)

            # Use ORM approach instead of raw update for SQLAlchemy 2.0 compatibility
            for field, value in update_data.items():
                setattr(assistant, field, value)
            
            await session.refresh(assistant)
            
            updated_assistant = assistant

    return AssistantModel.model_validate(updated_assistant)

@router.get("/{assistant_id}", response_model=AssistantModel)
async def get_assistant(assistant_id: str, response: Response, user: AuthCredentials = Depends(get_forwarded_user)):
    # Add deprecation warning to response
    add_deprecation_warning(response, f"/v1/assistants/{assistant_id} (GET)", user.user_id)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Assistant).where(Assistant.id == assistant_id))
        assistant = result.scalars().first()
    if not assistant:
        from ...openai_error_handler import OpenAIErrorFormatter
        error_response = OpenAIErrorFormatter.format_error(
            message="Assistant not found",
            type="not_found_error",
            code="assistant_not_found"
        )
        raise HTTPException(status_code=404, detail=error_response)
    
    # Convert SQLAlchemy object to dict for proper serialization
    assistant_data = {
        "id": assistant.id,
        "created_at": assistant.created_at,
        "name": assistant.name,
        "description": assistant.description,
        "model": assistant.model,
        "instructions": assistant.instructions,
        "tools": assistant.tools or [],
        "file_ids": assistant.file_ids or [],
        "metadata_": assistant.metadata_ or {}  # Use metadata_ for Pydantic field
    }
    return AssistantModel.model_validate(assistant_data)

@router.get("", response_model=AssistantList)
async def list_assistants(
    response: Response,
    user: AuthCredentials = Depends(get_forwarded_user),
    pagination: OpenAIPaginationParams = Depends(get_pagination_params)
):
    # Add deprecation warning to response
    add_deprecation_warning(response, "/v1/assistants (GET)", user.user_id)

    async with AsyncSessionLocal() as session:
        # Base query using the ORM model
        query = select(Assistant).where(Assistant.owner_id == user.user_id)
        
        # Count total items for has_more logic later
        count_query = select(func.count()).select_from(query.alias())
        total_count_result = await session.execute(count_query)
        total_count = total_count_result.scalar_one()

        # Apply ordering
        if pagination.order == "desc":
            query = query.order_by(Assistant.created_at.desc())
        else:
            query = query.order_by(Assistant.created_at.asc())
        
        query = query.limit(pagination.limit)
        
        result = await session.execute(query)
        user_assistants = result.scalars().all()

    # Convert SQLAlchemy objects to proper dict format
    serialized_assistants = []
    for assistant in user_assistants:
        assistant_data = {
            "id": assistant.id,
            "created_at": assistant.created_at,
            "name": assistant.name,
            "description": assistant.description,
            "model": assistant.model,
            "instructions": assistant.instructions,
            "tools": assistant.tools or [],
            "file_ids": assistant.file_ids or [],
            "metadata_": assistant.metadata_ or {}  # Use metadata_ for Pydantic field
        }
        serialized_assistants.append(AssistantModel.model_validate(assistant_data).dict())
    
    # Use the paginator to format the response
    paginated_data = OpenAIPaginator.paginate_results(
        items=serialized_assistants,
        params=pagination,
        total_count=total_count
    )
    
    return paginated_data

@router.delete("/{assistant_id}")
async def delete_assistant(assistant_id: str, response: Response, user: AuthCredentials = Depends(get_forwarded_user)):
    # Add deprecation warning to response
    add_deprecation_warning(response, f"/v1/assistants/{assistant_id} (DELETE)", user.user_id)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = delete(Assistant).where(Assistant.id == assistant_id).where(Assistant.owner_id == user.user_id)
            result = await session.execute(stmt)
            if result.rowcount == 0:
                from ...openai_error_handler import OpenAIErrorFormatter
                error_response = OpenAIErrorFormatter.format_error(
                    message="Assistant not found or you do not have permission to delete it",
                    type="not_found_error",
                    code="assistant_not_found"
                )
                raise HTTPException(status_code=404, detail=error_response)
    return {"id": assistant_id, "object": "assistant.deleted", "deleted": True}
