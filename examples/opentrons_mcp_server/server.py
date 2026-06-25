"""
Opentrons MCP Server

FastMCP server providing Opentrons liquid handling protocol execution.
"""

import logging
from typing import Union
from fastmcp import FastMCP, Context

# Support both standalone (Docker) and subpackage (examples.opentrons_mcp_server) imports
try:
    from .tools.protocol_execution import execute_opentrons_protocol
    from .protocol_validator import ProtocolSchema
except ImportError:
    from tools.protocol_execution import execute_opentrons_protocol
    from protocol_validator import ProtocolSchema

logger = logging.getLogger("opentrons_mcp_server")

# Initialize FastMCP server
# NOTE: stateless_http=True is passed to http_app() in main.py, not here.
mcp = FastMCP("Opentrons MCP Server")


def register_tools():
    """Register all Opentrons tools with FastMCP."""

    @mcp.tool()
    async def execute_opentrons_protocol_tool(
        protocol_json: Union[ProtocolSchema, dict],
        dry_run: bool = True,
        mcp_session_id: str = None,
        ctx: Context = None,
    ) -> dict:
        """Execute an Opentrons liquid handling protocol on a robot or simulator.

        Validates and executes liquid transfer protocols on Opentrons OT-2 robots.
        Supports 96-well and 384-well plates with p10, p20, p300, and p1000 pipettes.
        Runs in dry-run (validation only) mode by default — set dry_run=false to execute
        on hardware.

        Protocol JSON structure:
            {
                "protocol_name": "My Transfer",
                "plate_type": "96-well",
                "transfers": [
                    {"source_well": "A1", "dest_well": "B1", "volume_ul": 50.0, "tip_type": "p300_single"}
                ]
            }

        Well coordinates: A1–H12 (96-well) or A1–P24 (384-well).
        Tip types: p10_single, p20_single, p300_single, p1000_single.
        Volume limits enforced per tip type (e.g., p300 max 300 µL).

        Args:
            protocol_json: Protocol specification with protocol_name, plate_type, and transfers array.
            dry_run: If true, validates the protocol without executing on hardware (default: true).
            mcp_session_id: Session ID for resource isolation across concurrent users.

        Returns:
            dict with status ("validated" or "success"), protocol_name, transfer_count, and execution_log.
        """
        # Normalize: accept both Pydantic model (FastMCP coercion) and raw dict (JSON-RPC)
        if isinstance(protocol_json, ProtocolSchema):
            input_type = "ProtocolSchema"
            protocol_dict = protocol_json.model_dump()
        elif isinstance(protocol_json, dict):
            input_type = "dict"
            protocol_dict = protocol_json
        else:
            input_type = type(protocol_json).__name__
            protocol_dict = dict(protocol_json)

        protocol_name = protocol_dict.get("protocol_name", "unnamed")
        transfer_count = len(protocol_dict.get("transfers", []))

        logger.info(
            "[TOOL_CALL] execute_opentrons_protocol_tool | "
            "protocol=%s | transfers=%d | dry_run=%s | "
            "input_type=%s | session=%s",
            protocol_name, transfer_count, dry_run,
            input_type, mcp_session_id or "none",
        )

        try:
            result = await execute_opentrons_protocol(
                protocol_json=protocol_dict,
                dry_run=dry_run,
                ctx=ctx,
                mcp_session_id=mcp_session_id,
            )
            logger.info(
                "[TOOL_RESULT] execute_opentrons_protocol_tool | "
                "protocol=%s | status=%s | dry_run=%s",
                protocol_name, result.get("status", "unknown"), dry_run,
            )
            return result
        except Exception as e:
            logger.error(
                "[TOOL_ERROR] execute_opentrons_protocol_tool | "
                "protocol=%s | error=%s | dry_run=%s | session=%s",
                protocol_name, str(e), dry_run, mcp_session_id or "none",
            )
            raise


# Register tools on import
register_tools()
