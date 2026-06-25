"""
This module registers the UniProt tools with the MCP server.

It provides tools for querying the UniProt database for protein information,
using accession IDs or gene names.
"""
from fastmcp import FastMCP, Context
from ..state_manager import create_session_if_not_exists # Assuming session logic might be needed later
from ...logger_config import get_logger
import httpx
import json
import uuid # Needed if session ID generation is kept local
import logging # For type hinting
from typing import Dict, Any

# Use the centralized logger
logger = get_logger(__name__)

# Helper for session ID - consider making this a common utility
async def ensure_session_initialized_uniprot(ctx: Context):
    """Helper to ensure the session exists in the database."""
    # Re-using the logic from general_tools or make it a common utility
    session_id = get_stable_session_id_uniprot(ctx) # Use a distinct one if needed or refactor
    client_id = ctx.client_id if hasattr(ctx, 'client_id') else None
    await create_session_if_not_exists(session_id, client_id)
    return session_id

def get_stable_session_id_uniprot(ctx: Context) -> str:
    """Gets a stable session ID for the UniProt tool context."""
    if hasattr(ctx, 'session_id') and ctx.session_id:
        return ctx.session_id
    if ctx.request_id:
        return ctx.request_id
    logger.warning("UniProt Tool: Could not determine a stable session ID. Generating a new one.")
    return str(uuid.uuid4())

def register_tools(mcp: FastMCP):
    """Registers the UniProt tools with the MCP server."""

    @mcp.tool()
    async def query_uniprot_by_accession(accession_id: str, ctx: Context, timeout_seconds: int = 30, mcp_session_id: str = None) -> Dict[str, Any]:
        """
        Queries the UniProt database for a given protein accession ID.
        """
        # Consider refactoring session initialization to a common utility if used by many tools.
        session_id = await ensure_session_initialized_uniprot(ctx)
        await ctx.info(f"Session {session_id}: Querying UniProt for accession ID: {accession_id}")

        uniprot_api_url = f"https://rest.uniprot.org/uniprotkb/{accession_id}?format=json"

        try:
            async with httpx.AsyncClient(timeout=float(timeout_seconds)) as client:
                response = await client.get(uniprot_api_url)
                response.raise_for_status() # Raises HTTPStatusError for 4xx/5xx responses

                data = response.json()
                await ctx.info(f"Successfully retrieved data for UniProt ID {accession_id}")

                # Truncate the data to include only key fields
                truncated_data: Dict[str, Any] = {
                    "accession": data.get("accession"),
                    "id": data.get("id"),
                    "proteinDescription": data.get("proteinDescription"),
                    "genes": data.get("genes"), # List of gene objects
                    "organism": data.get("organism"), # Organism object
                    "sequenceLength": data.get("sequence", {}).get("length"),
                    "sequenceMass": data.get("sequence", {}).get("mass"),
                    # Include some key features or comments if they exist
                    "featuresSummary": [f.get("type") for f in data.get("features", []) if f.get("type") in ["Domain", "Binding site", "Active site", "Chain", "Peptide"]],
                    "commentsSummary": [c.get("type") for c in data.get("comments", []) if c.get("type") in ["Function", "Subunit structure", "Interaction", "Disease"]]
                }

                return truncated_data
        except httpx.HTTPStatusError as e:
            error_message = f"UniProt API request failed for {accession_id} with status {e.response.status_code}. Response: {e.response.text[:200]}"
            logger.error(error_message, exc_info=True)
            await ctx.error(f"UniProt API error: {e.response.status_code}")
            return {"error": "Failed to fetch data from UniProt.", "details": error_message}
        except httpx.RequestError as e:
            error_message = f"Request to UniProt failed for {accession_id}: {e}"
            logger.error(error_message, exc_info=True)
            await ctx.error("UniProt request failed.")
            return {"error": "Failed to connect to UniProt.", "details": str(e)}
        except json.JSONDecodeError as e:
            error_message = f"Failed to parse JSON response from UniProt for {accession_id}: {e}"
            logger.error(error_message, exc_info=True)
            await ctx.error("UniProt response parsing error.")
            return {"error": "Invalid response format from UniProt.", "details": str(e)}

    @mcp.tool()
    async def query_uniprot_by_gene(gene_query: str, ctx: Context, organism_id: str = "9606", limit: int = 5, timeout_seconds: int = 30, mcp_session_id: str = None) -> Dict[str, Any]:
        """
        Queries the UniProt database for proteins associated with a given gene.
        """
        session_id = await ensure_session_initialized_uniprot(ctx)
        await ctx.info(f"Session {session_id}: Querying UniProt for gene: '{gene_query}', organism: {organism_id}, limit: {limit}")

        # Construct the query: search for the gene name/symbol within the specified organism
        # Using 'gene_exact' for a more precise match if available, otherwise 'gene'
        # UniProt query syntax: (gene:GENE_NAME OR gene_exact:GENE_NAME) AND organism_id:ORGANISM_ID
        # For simplicity, we'll try gene first. For more complex queries, the syntax can be expanded.
        # query_string = f"(gene:{gene_query}) AND (organism_id:{organism_id})"
        # A simpler query focusing on the gene name, then filtering by organism in results if needed, or relying on UniProt's ranking.
        # For more precise results, including organism_id in the query is better.
        query_string = f"gene:{gene_query} AND organism_id:{organism_id}"
        
        uniprot_search_url = f"https://rest.uniprot.org/uniprotkb/search?query={query_string}&format=json&size={limit}"

        try:
            async with httpx.AsyncClient(timeout=float(timeout_seconds)) as client:
                response = await client.get(uniprot_search_url)
                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])

                if not results:
                    await ctx.info(f"No UniProt entries found for gene query: '{gene_query}' in organism {organism_id}")
                    return {"query": gene_query, "organism_id": organism_id, "results": [], "message": "No matching entries found."}

                # Truncate each result to key fields
                truncated_results = []
                for entry in results:
                    truncated_entry = {
                        "accession": entry.get("primaryAccession"),
                        "id": entry.get("uniProtkbId"),
                        "proteinDescription": entry.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value"),
                        "geneNames": [gn.get("geneName", {}).get("value") for gn in entry.get("genes", []) if gn.get("geneName")],
                        "organism": entry.get("organism", {}).get("scientificName"),
                    }
                    truncated_results.append(truncated_entry)
                
                await ctx.info(f"Successfully retrieved {len(truncated_results)} entries for gene query '{gene_query}'")
                return {"query": gene_query, "organism_id": organism_id, "results": truncated_results}

        except httpx.HTTPStatusError as e:
            error_message = f"UniProt API search failed for gene '{gene_query}' with status {e.response.status_code}. Response: {e.response.text[:200]}"
            logger.error(error_message, exc_info=True)
            await ctx.error(f"UniProt API search error: {e.response.status_code}")
            return {"error": "Failed to search UniProt by gene.", "details": error_message}
        except Exception as e: # Catch other errors like httpx.RequestError, json.JSONDecodeError
            error_message = f"An error occurred while searching UniProt for gene '{gene_query}': {e}"
            logger.error(error_message, exc_info=True)
            await ctx.error("UniProt gene search failed.")
            return {"error": "An unexpected error occurred during UniProt gene search.", "details": str(e)}

    logger.info("UniProt query MCP tool registered.")