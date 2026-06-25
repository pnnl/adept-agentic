"""
This module registers the AlphaFold tools with the MCP server.

It provides tools for:
1.  Fetching protein structure predictions from the AlphaFold EBI API.
2.  Storing summaries of these predictions in a vector store for RAG.
3.  Querying the stored summaries to find relevant predictions.
"""
from fastmcp import FastMCP, Context
from ...logger_config import get_logger
import httpx
import asyncio
import json
from typing import Dict, Any, Optional, List

from ..state_manager import create_session_if_not_exists # For session consistency
from .general_tools import get_stable_session_id, ensure_session_initialized # Common session helpers
from ..vector_store_manager import VectorStoreManager
from ...core.llm_agnostic_layer import LLMAgnosticClient, LLMServiceError

logger = get_logger(__name__)

# Global instance for LLM client, to be set by register_tools
_llm_client_instance: Optional[LLMAgnosticClient] = None
VECTOR_STORE_COLLECTION_NAME = "alphafold_predictions_main_v1"
ALPHAFOLD_API_BASE_URL = "https://alphafold.ebi.ac.uk/api/prediction/"

async def _ensure_session_alphafold(ctx: Context) -> str:
    """Ensures session is initialized for AlphaFold tools."""
    # Wrapper for ensure_session_initialized if specific logic is ever needed
    return await ensure_session_initialized(ctx)

async def get_alphafold_prediction_and_store(
    ctx: Context, uniprot_accession: str, timeout_seconds: int = 60, mcp_session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Fetches a protein structure prediction from the AlphaFold EBI API.

    It then stores a summary of the prediction in the vector store for RAG
    and returns the full API response.
    """
    session_id = await _ensure_session_alphafold(ctx) # mcp_session_id from Langchain is passed here
    await ctx.info(f"Session {session_id}: Fetching AlphaFold prediction for UniProt ID: {uniprot_accession}")

    if not _llm_client_instance:
        await ctx.error("LLM client not initialized for AlphaFold tool.")
        return {"error": "Internal server error: LLM client not available."}

    api_url = f"{ALPHAFOLD_API_BASE_URL}{uniprot_accession.strip()}"
    prediction_data: Optional[List[Dict[str, Any]]] = None

    try:
        async with httpx.AsyncClient(timeout=float(timeout_seconds)) as client:
            response = await client.get(api_url)
            response.raise_for_status() # Raises HTTPStatusError for 4xx/5xx responses
            prediction_data = response.json()

        if not prediction_data or not isinstance(prediction_data, list) or not prediction_data[0]:
            await ctx.warning(f"No valid prediction data found for UniProt ID {uniprot_accession} from AlphaFold EBI.")
            return {"uniprot_accession": uniprot_accession, "error": "No prediction data found or data in unexpected format."}

        # Process the first entry (usually the only one for a given accession)
        entry = prediction_data[0]
        await ctx.info(f"Successfully retrieved AlphaFold data for {uniprot_accession}. pLDDT: {entry.get('plddt')}")

        # Create a textual summary for RAG
        summary_text = (
            f"AlphaFold prediction for UniProt accession {entry.get('uniprotAccession', 'N/A')} "
            f"({entry.get('uniprotId', 'N/A')}, organism: {entry.get('organismScientificName', 'N/A')}). "
            f"Gene: {entry.get('gene', 'N/A')}. pLDDT score: {entry.get('plddt', 'N/A')}. "
            f"PTM score: {entry.get('ptmScore', 'N/A')}. "
            f"Description: {entry.get('uniprotDescription', 'N/A')}. "
            f"PDB URL: {entry.get('pdbUrl', 'N/A')}."
        )

        # Embed the summary
        try:
            embedding = await _llm_client_instance.acreate_embedding(input_texts=[summary_text])
            if not embedding or not embedding[0]:
                raise LLMServiceError("Embedding generation returned empty result.")
            
            vsm = VectorStoreManager()
            doc_id = entry['uniprotAccession'] # Use UniProt accession as the document ID
            
            # Create metadata dictionary and filter out any keys with None values, as ChromaDB doesn't support them.
            metadata_to_store_unfiltered = {
                "uniprot_accession": entry.get('uniprotAccession'),
                "uniprot_id": entry.get('uniprotId'),
                "organism": entry.get('organismScientificName'),
                "gene": entry.get('gene'),
                "plddt": entry.get('plddt'),
                "ptm_score": entry.get('ptmScore'),
                "pdb_url": entry.get('pdbUrl'),
                "cif_url": entry.get('cifUrl'),
                "entry_id": entry.get('entryId'),
                "summary_text": summary_text, # Store the summary text itself for easier retrieval
                "api_response_json": json.dumps(entry) # Optionally store the full entry
            }
            metadata_to_store = {k: v for k, v in metadata_to_store_unfiltered.items() if v is not None}
            
            vsm.add_documents(
                collection_name=VECTOR_STORE_COLLECTION_NAME,
                documents=[summary_text], # Document content is the summary
                embeddings=[embedding[0]],
                metadatas=[metadata_to_store],
                ids=[doc_id] # Using UniProt accession as ID, will update if exists
            )
            await ctx.info(f"Stored/Updated AlphaFold prediction summary for {uniprot_accession} in vector store.")
        except LLMServiceError as e:
            logger.error(f"Failed to embed or store AlphaFold summary for {uniprot_accession}: {e}", exc_info=True)
            await ctx.warning(f"Could not embed/store summary for {uniprot_accession}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during vector store operation for {uniprot_accession}: {e}", exc_info=True)
            await ctx.warning(f"Unexpected error storing summary for {uniprot_accession}: {e}")

        return {"uniprot_accession": uniprot_accession, "prediction_entry": entry, "status": "success"}

    except httpx.HTTPStatusError as e:
        error_message = f"AlphaFold API request failed for {uniprot_accession} with status {e.response.status_code}. Response: {e.response.text[:200]}"
        logger.error(error_message, exc_info=True)
        await ctx.error(f"AlphaFold API error: {e.response.status_code}")
        return {"uniprot_accession": uniprot_accession, "error": "Failed to fetch data from AlphaFold EBI.", "details": error_message}
    except httpx.RequestError as e:
        error_message = f"Request to AlphaFold EBI failed for {uniprot_accession}: {e}"
        logger.error(error_message, exc_info=True)
        await ctx.error("AlphaFold EBI request failed.")
        return {"uniprot_accession": uniprot_accession, "error": "Failed to connect to AlphaFold EBI.", "details": str(e)}
    except json.JSONDecodeError as e:
        error_message = f"Failed to parse JSON response from AlphaFold EBI for {uniprot_accession}: {e}"
        logger.error(error_message, exc_info=True)
        await ctx.error("AlphaFold EBI response parsing error.")
        return {"uniprot_accession": uniprot_accession, "error": "Invalid response format from AlphaFold EBI.", "details": str(e)}
    except Exception as e:
        error_message = f"An unexpected error occurred while fetching AlphaFold data for {uniprot_accession}: {e}"
        logger.error(error_message, exc_info=True)
        await ctx.error("Unexpected error during AlphaFold data retrieval.")
        return {"uniprot_accession": uniprot_accession, "error": "An unexpected error occurred.", "details": str(e)}


async def query_stored_alphafold_predictions(
    ctx: Context, query_text: str, top_k: int = 3, timeout_seconds: int = 60, mcp_session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Queries previously stored AlphaFold prediction summaries from the vector store.
    """
    session_id = await _ensure_session_alphafold(ctx)
    await ctx.info(f"Session {session_id}: Querying stored AlphaFold predictions with: '{query_text}'")

    if not _llm_client_instance:
        await ctx.error("LLM client not initialized for AlphaFold RAG tool.")
        return {"error": "Internal server error: LLM client not available."}

    try:
        query_embedding = await _llm_client_instance.acreate_embedding(input_texts=[query_text])
        if not query_embedding or not query_embedding[0]:
            raise LLMServiceError("Query embedding generation returned empty result.")

        vsm = VectorStoreManager()
        results = vsm.query_collection(
            collection_name=VECTOR_STORE_COLLECTION_NAME,
            query_embeddings=[query_embedding[0]],
            n_results=top_k,
            include=["metadatas", "documents", "distances"] # Include distances for relevance
        )

        if not results or not results.get("ids") or not results["ids"][0]:
            await ctx.info(f"No relevant stored AlphaFold predictions found for query: '{query_text}'")
            return {"query": query_text, "results": [], "message": "No matching AlphaFold predictions found in local store."}

        # Reconstruct results for easier consumption
        # The 'documents' field from ChromaDB contains the summary_text we stored.
        # The 'metadatas' field contains the detailed metadata.
        output_results = []
        for i in range(len(results["ids"][0])):
            output_results.append({
                "id": results["ids"][0][i],
                "document_summary": results["documents"][0][i] if results.get("documents") and results["documents"][0] else None,
                "metadata": results["metadatas"][0][i] if results.get("metadatas") and results["metadatas"][0] else None,
                "distance": results["distances"][0][i] if results.get("distances") and results["distances"][0] else None,
            })
        
        await ctx.info(f"Found {len(output_results)} relevant stored AlphaFold predictions for query: '{query_text}'")
        return {"query": query_text, "results": output_results}

    except LLMServiceError as e:
        logger.error(f"LLM service error during AlphaFold RAG query '{query_text}': {e}", exc_info=True)
        await ctx.error(f"LLM service error during RAG query: {e}")
        return {"error": f"Could not process RAG query due to LLM service error: {e}."}
    except Exception as e:
        logger.error(f"Unexpected error during AlphaFold RAG query '{query_text}': {e}", exc_info=True)
        await ctx.error(f"Unexpected error during RAG query: {e}")
        return {"error": f"An unexpected error occurred during RAG query: {e}."}
    
    
def register_tools(mcp: FastMCP, llm_client: LLMAgnosticClient):
    """Registers the AlphaFold tools with the FastMCP instance."""
    global _llm_client_instance
    _llm_client_instance = llm_client

    mcp.tool()(get_alphafold_prediction_and_store)
    mcp.tool()(query_stored_alphafold_predictions)
    logger.info("AlphaFold MCP tools registered.")