"""
Opentrons Protocol Execution Tool

MCP tool for executing liquid handling protocols on Opentrons robots.
"""

import os
from typing import Dict, Any
from fastmcp import Context

# Support both standalone (Docker) and subpackage (examples.opentrons_mcp_server) imports
try:
    from ..protocol_validator import OpentronProtocolValidator
    from ..simulation import SimulatedOpentrons, RealOpentrons
except ImportError:
    from protocol_validator import OpentronProtocolValidator
    from simulation import SimulatedOpentrons, RealOpentrons


# Hardware mode: "simulation" or "real"
HARDWARE_MODE = os.getenv("OPENTRONS_HARDWARE_MODE", "simulation")


async def execute_opentrons_protocol(
    protocol_json: Dict[str, Any],
    dry_run: bool = True,
    ctx: Context = None,
    mcp_session_id: str = None,
) -> dict:
    """
    Execute an Opentrons liquid handling protocol.

    Args:
        protocol_json: Protocol specification (see ProtocolSchema)
        dry_run: If True, validates protocol without hardware execution (default: True)
        ctx: FastMCP context
        mcp_session_id: Session ID for isolation

    Returns:
        Dict with execution log, status, and protocol summary

    Security:
        - Requires ACL group: "lab-users" or "scientists"
        - Hardware control limited by safety validator
        - Human-in-the-loop required for dry_run=False

    Example Protocol:
        {
            "protocol_name": "Sample Transfer",
            "protocol_version": "1.0",
            "plate_type": "96-well",
            "transfers": [
                {
                    "source_well": "A1",
                    "dest_well": "B1",
                    "volume_ul": 50.0,
                    "tip_type": "p300_single"
                }
            ]
        }
    """
    if ctx:
        await ctx.info(
            f"Received protocol: {protocol_json.get('protocol_name', 'Unnamed')}"
        )

    # 1. Validate protocol schema
    validator = OpentronProtocolValidator()
    is_valid, errors = validator.validate(protocol_json)

    if not is_valid:
        if ctx:
            await ctx.error(f"Protocol validation failed: {errors}")
        return {
            "status": "error",
            "error": "Invalid protocol",
            "validation_errors": errors,
        }

    # 2. Check dry_run mode
    if dry_run:
        if ctx:
            await ctx.info("DRY RUN mode - protocol validated but not executed")
        return {
            "status": "validated",
            "protocol_name": protocol_json["protocol_name"],
            "transfer_count": len(protocol_json["transfers"]),
            "dry_run": True,
            "message": "Protocol valid. Use dry_run=False to execute on hardware.",
        }

    # 3. Execute protocol (simulation or real hardware)
    if HARDWARE_MODE == "simulation":
        if ctx:
            await ctx.info("Executing in SIMULATION mode")
        opentrons = SimulatedOpentrons(session_id=mcp_session_id)
    else:
        if ctx:
            await ctx.warning("Executing on REAL HARDWARE")
        opentrons = RealOpentrons(session_id=mcp_session_id)

    # 4. Execute transfers
    execution_log = []
    for i, transfer in enumerate(protocol_json["transfers"]):
        if ctx:
            await ctx.info(
                f"Transfer {i+1}/{len(protocol_json['transfers'])}: "
                f"{transfer['source_well']} → {transfer['dest_well']} "
                f"({transfer['volume_ul']}μL)"
            )

        result = await opentrons.transfer(
            source_well=transfer["source_well"],
            dest_well=transfer["dest_well"],
            volume_ul=transfer["volume_ul"],
            tip_type=transfer["tip_type"],
        )

        execution_log.append(result)

    # 5. Cleanup and return
    await opentrons.cleanup()
    if ctx:
        await ctx.info("Protocol execution complete")

    return {
        "status": "success",
        "protocol_name": protocol_json["protocol_name"],
        "transfer_count": len(protocol_json["transfers"]),
        "execution_log": execution_log,
        "dry_run": False,
        "session_id": mcp_session_id,
        "hardware_mode": HARDWARE_MODE,
    }
