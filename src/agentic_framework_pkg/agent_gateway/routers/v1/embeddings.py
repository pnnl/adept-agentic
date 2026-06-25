"""
This module provides the OpenAI-compatible `/v1/embeddings` endpoint.

It acts as a proxy to a configurable backend embedding model, using the `litellm`
library to abstract away the specific provider (e.g., OpenAI, Azure, local models).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Union, Any, Dict
import litellm
from ....logger_config import get_logger

router = APIRouter()
logger = get_logger(__name__)

# --- Pydantic Models for OpenAI Compatibility ---

class EmbeddingRequest(BaseModel):
    """OpenAI-compatible request model for embeddings."""
    input: Union[str, List[str]] = Field(..., description="The input text or texts to embed.")
    model: str = Field(..., description="The ID of the model to use for embedding.")
    encoding_format: str = Field(default="float", description="The format of the returned embeddings.")

class EmbeddingData(BaseModel):
    """Represents a single embedding vector."""
    object: str = "embedding"
    embedding: List[float]
    index: int

class Usage(BaseModel):
    """Usage statistics for the embedding request."""
    prompt_tokens: int
    total_tokens: int

class EmbeddingResponse(BaseModel):
    """OpenAI-compatible response model for embeddings."""
    object: str = "list"
    data: List[EmbeddingData]
    model: str
    usage: Usage

# --- Embedding Endpoint ---

@router.post("/embeddings", response_model=EmbeddingResponse, summary="Create Text Embeddings")
async def create_embeddings(request: EmbeddingRequest):
    """
    Creates and returns embeddings for a given input text.

    This endpoint uses the `litellm` library to call the specified embedding
    model, providing a unified interface for various underlying model providers.
    """
    logger.info(f"Received request on /v1/embeddings for model '{request.model}'")
    
    try:
        # Use litellm's embedding function to call the underlying model.
        response = await litellm.aembedding(
            model=request.model,
            input=request.input
        )

        # Convert the litellm response to the OpenAI-compatible format.
        embedding_data = [
            EmbeddingData(embedding=item['embedding'], index=item['index'])
            for item in response.data
        ]

        # Extract usage stats from the litellm response
        usage = Usage(
            prompt_tokens=response.usage.prompt_tokens,
            total_tokens=response.usage.total_tokens
        )

        # Construct the final response
        final_response = EmbeddingResponse(
            data=embedding_data,
            model=response.model, # Use the model name returned by litellm
            usage=usage
        )
        
        logger.info(f"Successfully generated embeddings with model '{response.model}'.")
        return final_response

    except Exception as e:
        # litellm raises exceptions from the underlying provider.
        logger.error(f"Error generating embeddings with litellm: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred while generating embeddings: {e}")