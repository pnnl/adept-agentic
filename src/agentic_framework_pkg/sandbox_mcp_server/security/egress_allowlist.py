"""
Sandbox egress allowlist — Pydantic model and YAML config loader.

Validates operator-provided egress rules. Fail-closed on any error:
if the config is missing, empty, or malformed, ALL external egress is denied.
"""

import ipaddress
import logging
import re
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

FQDN_PATTERN = re.compile(
    r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.[a-z0-9-]{1,63})*\.[a-z]{2,}$"
)


class EgressRule(BaseModel):
    """A single approved egress destination (host:port or host:all-ports)."""

    host: str
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    comment: str = Field(min_length=1, description="Operator justification for this rule")

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        v = v.strip().lower()

        if not v:
            raise ValueError("Host cannot be empty")

        if "*" in v or "?" in v:
            raise ValueError(f"Wildcards not allowed in host: {v}")

        if v in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            raise ValueError(f"Loopback/localhost not allowed: {v}")

        if "/" in v:
            raise ValueError(f"CIDR notation not allowed (use individual hosts): {v}")

        try:
            addr = ipaddress.ip_address(v)
            if addr.is_loopback or addr.is_unspecified:
                raise ValueError(f"Loopback/unspecified address not allowed: {v}")
            return v
        except ValueError as e:
            if "Loopback" in str(e) or "unspecified" in str(e):
                raise
            pass

        if not FQDN_PATTERN.match(v):
            raise ValueError(f"Invalid hostname format: {v}")

        return v


class SandboxEgressAllowlist(BaseModel):
    """Top-level egress allowlist configuration."""

    version: int = Field(ge=1, le=1, description="Config schema version")
    rules: list[EgressRule] = Field(
        default_factory=list,
        max_length=50,
        description="Approved egress destinations (max 50 rules)",
    )


def load_and_validate(config_path: Path) -> SandboxEgressAllowlist:
    """Load and validate egress allowlist. Fail-closed on any error."""
    try:
        if not config_path.exists() or not config_path.is_file():
            logger.info(
                "SECURITY: No egress allowlist config at %s — denying ALL external egress (secure default)",
                config_path,
            )
            return SandboxEgressAllowlist(version=1, rules=[])

        raw = yaml.safe_load(config_path.read_text())
        if raw is None:
            logger.info(
                "SECURITY: Empty egress allowlist config at %s — denying ALL external egress",
                config_path,
            )
            return SandboxEgressAllowlist(version=1, rules=[])

        allowlist = SandboxEgressAllowlist(**raw)
        logger.info(
            "SECURITY: Egress allowlist loaded — %d rules from %s",
            len(allowlist.rules),
            config_path,
        )
        return allowlist

    except Exception as e:
        logger.error(
            "SECURITY: Egress allowlist validation FAILED — denying ALL egress. "
            "Error: %s. Fix config at %s and restart the container.",
            e,
            config_path,
        )
        return SandboxEgressAllowlist(version=1, rules=[])
