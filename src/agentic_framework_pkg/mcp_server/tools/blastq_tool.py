"""
This module provides tools for interacting with the NCBI BLAST web service
using the `BioPython` library.

This implementation is the successor to the deprecated `blast_tool.py` module.
It is more robust and reliable as it uses a dedicated bioinformatics library
to handle the complexities of the NCBI API.

Architectural Role:
-   **Bioinformatics Tool Provider:** Exposes core bioinformatics functionality
    (BLASTP for protein and BLASTN for nucleotide searches) as MCP tools.
-   **Executor Logic:** Contains the logic for calling the external NCBI service,
    parsing the XML results, and formatting them into a structured JSON response
    for the agent.
"""
from fastmcp import FastMCP, Context
from ..state_manager import create_session_if_not_exists
from ...logger_config import get_logger
import asyncio
import uuid
import logging # For type hinting

# Import Biopython modules for BLAST
from Bio.Blast import NCBIWWW
from Bio.Blast import NCBIXML
from typing import Dict, Any, Optional, List
import json # For potential JSONDecodeError if NCBI returns non-XML

# Use the centralized logger
logger = get_logger(__name__)

# Helper for session ID - consider making this a common utility
async def ensure_session_initialized_blastq(ctx: Context):
    """Helper to ensure the session exists in the database for blastq_tool."""
    session_id = get_stable_session_id_blastq(ctx)
    client_id = ctx.client_id if hasattr(ctx, 'client_id') else None
    await create_session_if_not_exists(session_id, client_id)
    return session_id

def get_stable_session_id_blastq(ctx: Context) -> str:
    """Gets a stable session ID for blastq_tool."""
    if hasattr(ctx, 'session_id') and ctx.session_id:
        return ctx.session_id
    if ctx.request_id:
        return ctx.request_id
    logger.warning("BLASTQ Tool: Could not determine a stable session ID. Generating a new one.")
    return str(uuid.uuid4())

def register_tools(mcp: FastMCP):
    """Registers the BioPython-based BLAST tools with the MCP server."""
    # Set NCBI contact info as recommended
    # Replace with actual contact info if deploying publicly
    NCBIWWW.email = "paul.rigor@pnnl.gov"
    NCBIWWW.tool = "AgenticFrameworkMCP_BlastQ"

    @mcp.tool()
    async def perform_blastp_search_biopython(sequence: str, ctx: Context, database: str = "nr", expect: float = 10.0, hitlist_size: int = 10, timeout_seconds: int = 120, mcp_session_id: str = None) -> Dict[str, Any]:
        """
        Performs a protein sequence homology search (BLASTP) using BioPython.
        
        Args:
            sequence: The protein sequence to search with.
            database: The BLAST database to search against (e.g., 'nr', 'swissprot').
            expect: The E-value threshold.
            hitlist_size: The maximum number of hits to return.
            ctx: The FastMCP context object.
            mcp_session_id: The MCP session ID.

        Returns:
            A dictionary containing the search results or an error message.
        """
        session_id = await ensure_session_initialized_blastq(ctx)
        await ctx.info(f"Session {session_id}: Submitting BLASTP (Biopython) search for sequence (first 20 chars: {sequence[:20]}...) against {database}")

        try:
            result_handle = await asyncio.wait_for(
                asyncio.to_thread(
                    NCBIWWW.qblast,
                    "blastp", database, sequence,
                    expect=expect, hitlist_size=hitlist_size, format_type="XML"
                ),
                timeout=float(timeout_seconds),
            )
            logger.info(f"BLASTP (Biopython) qblast call completed for session {session_id}.")

            blast_record = await asyncio.wait_for(
                asyncio.to_thread(NCBIXML.read, result_handle),
                timeout=float(timeout_seconds),
            )
            result_handle.close()
            logger.info(f"BLASTP (Biopython) results parsed for session {session_id}.")

            hits = blast_record.alignments
            if not hits:
                await ctx.info(f"BLASTP (Biopython) search returned no hits for session {session_id}.")
                return {"query": sequence[:20]+"...", "database": database, "results": [], "message": "BLAST search completed, but found no hits."}

            truncated_hits = []
            for hit_alignment in hits: # Renamed 'hit' to 'hit_alignment' to avoid conflict with HSP's hit attribute
                accession = hit_alignment.hit_id # or hit_alignment.accession depending on Biopython version/XML structure
                title = hit_alignment.hit_def
                hsp_summary = None
                if hit_alignment.hsps:
                    best_hsp = hit_alignment.hsps[0]
                    hsp_summary = {
                        "bit_score": best_hsp.bits, "score": best_hsp.score, "evalue": best_hsp.expect,
                        "identity_percent": (best_hsp.identities / best_hsp.align_length) * 100 if best_hsp.align_length > 0 else 0,
                        "query_from": best_hsp.query_start, "query_to": best_hsp.query_end,
                        "hit_from": best_hsp.sbjct_start, "hit_to": best_hsp.sbjct_end,
                        "align_len": best_hsp.align_length,
                    }
                truncated_hits.append({"accession": accession, "title": title, "hsp_summary": hsp_summary})

            await ctx.info(f"Successfully retrieved {len(truncated_hits)} BLASTP (Biopython) hits for session {session_id}.")
            return {"query": sequence[:20]+"...", "database": database, "results": truncated_hits}
        except Exception as e:
            error_message = f"An unexpected error occurred during BLASTP (Biopython) search: {e}"
            logger.error(error_message, exc_info=True)
            await ctx.error("BLASTP (Biopython) search failed.")
            return {"error": "An unexpected error occurred during BLASTP (Biopython) search.", "details": str(e)}

    @mcp.tool()
    async def perform_blastn_search_biopython(sequence: str, ctx: Context, database: str = "nt", expect: float = 10.0, hitlist_size: int = 10, timeout_seconds: int = 120, mcp_session_id: str = None) -> Dict[str, Any]:
        """
        Performs a nucleotide sequence homology search (BLASTN) using BioPython.
        
        Args:
            sequence: The nucleotide sequence to search with.
            database: The BLAST database to search against (e.g., 'nt', 'refseq_rna').
            expect: The E-value threshold.
            hitlist_size: The maximum number of hits to return.
            ctx: The FastMCP context object.
            mcp_session_id: The MCP session ID.

        Returns:
            A dictionary containing the search results or an error message.
        """
        session_id = await ensure_session_initialized_blastq(ctx)
        await ctx.info(f"Session {session_id}: Submitting BLASTN (Biopython) search for sequence (first 20 chars: {sequence[:20]}...) against {database}")

        try:
            result_handle = await asyncio.wait_for(
                asyncio.to_thread(
                    NCBIWWW.qblast,
                    "blastn", database, sequence,
                    expect=expect, hitlist_size=hitlist_size, format_type="XML"
                ),
                timeout=float(timeout_seconds),
            )
            logger.info(f"BLASTN (Biopython) qblast call completed for session {session_id}.")

            blast_record = await asyncio.wait_for(
                asyncio.to_thread(NCBIXML.read, result_handle),
                timeout=float(timeout_seconds),
            )
            result_handle.close()
            logger.info(f"BLASTN (Biopython) results parsed for session {session_id}.")

            hits = blast_record.alignments
            if not hits:
                await ctx.info(f"BLASTN (Biopython) search returned no hits for session {session_id}.")
                return {"query": sequence[:20]+"...", "database": database, "results": [], "message": "BLAST search completed, but found no hits."}

            truncated_hits = []
            for hit_alignment in hits:
                accession = hit_alignment.hit_id
                title = hit_alignment.hit_def
                hsp_summary = None
                if hit_alignment.hsps:
                    best_hsp = hit_alignment.hsps[0]
                    hsp_summary = {
                        "bit_score": best_hsp.bits, "score": best_hsp.score, "evalue": best_hsp.expect,
                        "identity_percent": (best_hsp.identities / best_hsp.align_length) * 100 if best_hsp.align_length > 0 else 0,
                        "query_from": best_hsp.query_start, "query_to": best_hsp.query_end,
                        "hit_from": best_hsp.sbjct_start, "hit_to": best_hsp.sbjct_end,
                        "align_len": best_hsp.align_length,
                    }
                truncated_hits.append({"accession": accession, "title": title, "hsp_summary": hsp_summary})

            await ctx.info(f"Successfully retrieved {len(truncated_hits)} BLASTN (Biopython) hits for session {session_id}.")
            return {"query": sequence[:20]+"...", "database": database, "results": truncated_hits}
        except Exception as e:
            error_message = f"An unexpected error occurred during BLASTN (Biopython) search: {e}"
            logger.error(error_message, exc_info=True)
            await ctx.error("BLASTN (Biopython) search failed.")
            return {"error": "An unexpected error occurred during BLASTN (Biopython) search.", "details": str(e)}

    logger.info("BLASTQ (Biopython) MCP tool registered.")