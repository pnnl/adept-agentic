"""
This module registers the PubChem tools with the MCP server.

It provides tools for searching for chemical compounds and retrieving their
properties, using the `pubchempy` library as a client for the PubChem API.
"""
from fastmcp import FastMCP, Context
from ...logger_config import get_logger
import asyncio
from typing import Dict, Any, List, Optional
import pubchempy as pcp # Import pubchempy

# Use the centralized logger
logger = get_logger(__name__)

# Helper for session ID (can be adapted from other tool files or a common utility)
# For PubChem, session state on MCP server might not be strictly necessary for basic queries.
# from .general_tools import ensure_session_initialized # If you need session state

def register_tools(mcp: FastMCP):
    """Registers the PubChem tools with the MCP server."""

    @mcp.tool()
    async def search_pubchem_by_name(ctx: Context, chemical_name: str, max_results: int = 5, timeout_seconds: int = 30, mcp_session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Searches PubChem for compounds by chemical name using `pubchempy`.
        """
        await ctx.info(f"Searching PubChem (pubchempy) for chemical name: '{chemical_name}', max_results: {max_results}")

        try:
            # pubchempy.get_compounds is synchronous, run in a thread
            compounds: List[pcp.Compound] = await asyncio.wait_for(
                asyncio.to_thread(
                    pcp.get_compounds, chemical_name, 'name', listkey_count=max_results
                ),
                timeout=float(timeout_seconds),
            )

            if not compounds:
                await ctx.info(f"No compounds found for '{chemical_name}' using pubchempy.")
                return {"query": chemical_name, "results": [], "message": "No compounds found for the given name."}

            results = []
            # Limit results explicitly, as listkey_count is a hint and might return more
            for compound in compounds[:max_results]:
                # pubchempy might return fewer synonyms than requested if not available
                syns = compound.synonyms[:5] if compound.synonyms else []
                results.append({"cid": compound.cid, "synonyms": syns, "title": compound.iupac_name or (syns[0] if syns else "N/A")})

            return {"query": chemical_name, "results": results}

        except pcp.PubChemPyError as e:
            err_msg = f"PubChemPy API request failed for '{chemical_name}': {e}"
            logger.error(err_msg, exc_info=True)
            await ctx.error(f"PubChemPy API error: {e}")
            return {"error": "Failed to fetch data from PubChem using pubchempy.", "details": err_msg}
        except Exception as e:
            err_msg = f"An unexpected error occurred during PubChem (pubchempy) search for '{chemical_name}': {e}"
            logger.error(err_msg, exc_info=True)
            await ctx.error("PubChem (pubchempy) search failed.")
            return {"error": "An unexpected error occurred during PubChem (pubchempy) search.", "details": str(e)}

    @mcp.tool()
    async def get_pubchem_compound_properties(ctx: Context, cid: int, properties: Optional[List[str]] = None, timeout_seconds: int = 30, mcp_session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves specified properties for a given PubChem Compound ID (CID).
        """
        await ctx.info(f"Fetching properties (pubchempy) for PubChem CID: {cid}")

        if properties is None:
            # These are common attributes of the pubchempy.Compound object
            properties = ["molecular_formula", "molecular_weight", "canonical_smiles", "isomeric_smiles", "inchi", "inchi_key", "iupac_name", "synonyms"]

        try:
            # pubchempy.Compound.from_cid is synchronous
            compound: Optional[pcp.Compound] = await asyncio.wait_for(
                asyncio.to_thread(pcp.Compound.from_cid, cid),
                timeout=float(timeout_seconds),
            )

            if not compound:
                await ctx.warning(f"Compound with CID {cid} not found using pubchempy.")
                return {"cid": cid, "properties": {}, "message": f"Compound with CID {cid} not found."}

            compound_props = {}
            for prop_name in properties:
                if hasattr(compound, prop_name):
                    value = getattr(compound, prop_name)
                    # Limit synonyms if requested
                    if prop_name == "synonyms" and isinstance(value, list):
                        compound_props[prop_name] = value[:5] # Get first 5 synonyms
                    else:
                        compound_props[prop_name] = value
                else:
                    compound_props[prop_name] = None # Property not available

            return {"cid": cid, "properties": compound_props}

        except pcp.PubChemPyError as e:
            err_msg = f"PubChemPy API property request failed for CID {cid}: {e}"
            logger.error(err_msg, exc_info=True)
            await ctx.error(f"PubChemPy API error: {e}")
            return {"error": f"Failed to fetch properties for CID {cid} from PubChem using pubchempy.", "details": err_msg}
        except Exception as e:
            err_msg = f"An unexpected error occurred fetching properties (pubchempy) for CID {cid}: {e}"
            logger.error(err_msg, exc_info=True)
            await ctx.error("PubChem (pubchempy) property retrieval failed.")
            return {"error": f"An unexpected error occurred for CID {cid} (pubchempy).", "details": str(e)}

    @mcp.tool()
    async def search_pubchem_by_query(ctx: Context, query: str, max_results: int = 5, timeout_seconds: int = 30, mcp_session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Searches PubChem for compounds by general query terms.
        """
        await ctx.info(f"Searching PubChem (pubchempy) for query: '{query}', max_results: {max_results}")

        try:
            # pubchempy.get_compounds is synchronous, run in a thread
            compounds: List[pcp.Compound] = await asyncio.wait_for(
                asyncio.to_thread(
                    pcp.get_compounds, query, 'name', listkey_count=max_results
                ),
                timeout=float(timeout_seconds),
            )

            if not compounds:
                await ctx.info(f"No compounds found for query '{query}' using pubchempy.")
                return {"query": query, "results": [], "message": "No compounds found for the given query."}

            results = []
            # Limit results explicitly, as listkey_count is a hint and might return more
            for compound in compounds[:max_results]:
                # pubchempy might return fewer synonyms than requested if not available
                syns = compound.synonyms[:5] if compound.synonyms else []
                results.append({"cid": compound.cid, "synonyms": syns, "title": compound.iupac_name or (syns[0] if syns else "N/A")})

            return {"query": query, "results": results}

        except pcp.PubChemPyError as e:
            err_msg = f"PubChemPy API request failed for query '{query}': {e}"
            logger.error(err_msg, exc_info=True)
            await ctx.error(f"PubChemPy API error: {e}")
            return {"error": "Failed to fetch data from PubChem using pubchempy.", "details": err_msg}
        except Exception as e:
            err_msg = f"An unexpected error occurred during PubChem (pubchempy) search for query '{query}': {e}"
            logger.error(err_msg, exc_info=True)
            await ctx.error("PubChem (pubchempy) search failed.")
            return {"error": "An unexpected error occurred during PubChem (pubchempy) search.", "details": str(e)}

    logger.info("PubChem MCP tools (using pubchempy) registered.")