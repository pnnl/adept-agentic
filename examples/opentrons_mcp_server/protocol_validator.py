"""
Opentrons Protocol Validator

Validates liquid handling protocols against schema and safety rules.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Literal
import re


class TransferSchema(BaseModel):
    """Schema for a single liquid transfer."""

    source_well: str = Field(..., description="Source well (e.g., 'A1')")
    dest_well: str = Field(..., description="Destination well (e.g., 'B1')")
    volume_ul: float = Field(
        ..., ge=0.1, le=1000.0, description="Volume in microliters (0.1-1000)"
    )
    tip_type: Literal["p10_single", "p20_single", "p300_single", "p1000_single"] = (
        Field(..., description="Pipette tip type")
    )

    @validator("source_well", "dest_well")
    def validate_well_format(cls, v):
        """Validate well coordinate (A1-H12 for 96-well plate)."""
        if not re.match(r"^[A-H](?:[1-9]|1[0-2])$", v):
            raise ValueError(f"Invalid well coordinate: {v}. Must be A1-H12.")
        return v


class ProtocolSchema(BaseModel):
    """Schema for Opentrons liquid handling protocol."""

    protocol_name: str = Field(..., description="Human-readable protocol name")
    protocol_version: str = Field(default="1.0", description="Protocol version")
    plate_type: Literal["96-well", "384-well"] = Field(
        default="96-well", description="Plate format"
    )
    transfers: List[TransferSchema] = Field(
        ..., min_items=1, max_items=96, description="List of transfers (1-96)"
    )


class OpentronProtocolValidator:
    """Validates Opentrons protocols against schema and safety rules."""

    def validate(self, protocol_json: dict) -> tuple[bool, list]:
        """
        Validate protocol against schema and safety rules.

        Args:
            protocol_json: Protocol specification dictionary

        Returns:
            (is_valid, error_list)
        """
        errors = []

        # 1. Schema validation
        try:
            protocol = ProtocolSchema(**protocol_json)
        except Exception as e:
            errors.append(f"Schema validation failed: {e}")
            return False, errors

        # 2. Safety rules
        # Rule: Total volume per well doesn't exceed plate capacity
        well_volumes = {}
        for transfer in protocol.transfers:
            well_volumes[transfer.dest_well] = (
                well_volumes.get(transfer.dest_well, 0) + transfer.volume_ul
            )

        max_volume = 300.0 if protocol.plate_type == "96-well" else 100.0
        for well, volume in well_volumes.items():
            if volume > max_volume:
                errors.append(
                    f"Well {well} exceeds maximum volume: {volume}μL > {max_volume}μL"
                )

        # Rule: Validate tip types match volume ranges
        for transfer in protocol.transfers:
            if transfer.tip_type == "p10_single" and transfer.volume_ul > 10.0:
                errors.append(
                    f"Transfer volume {transfer.volume_ul}μL exceeds p10 tip capacity (10μL)"
                )
            elif transfer.tip_type == "p20_single" and transfer.volume_ul > 20.0:
                errors.append(
                    f"Transfer volume {transfer.volume_ul}μL exceeds p20 tip capacity (20μL)"
                )
            elif transfer.tip_type == "p300_single" and transfer.volume_ul > 300.0:
                errors.append(
                    f"Transfer volume {transfer.volume_ul}μL exceeds p300 tip capacity (300μL)"
                )
            elif transfer.tip_type == "p1000_single" and transfer.volume_ul > 1000.0:
                errors.append(
                    f"Transfer volume {transfer.volume_ul}μL exceeds p1000 tip capacity (1000μL)"
                )

        return len(errors) == 0, errors
