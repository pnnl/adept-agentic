"""
This module defines the Pydantic schemas for the Gateway Registry API.

These schemas are used by FastAPI for request validation, response serialization,
and generating the OpenAPI documentation. They ensure that all data exchanged
with the API conforms to a well-defined structure.
"""
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List, Dict, Any, Union
import datetime
import ipaddress
import os
from urllib.parse import urlparse

# CIDR allowlist for A2A peer gateway registration.
# Private IPs are blocked by default (zero-trust). Operators must explicitly declare
# which network ranges contain trusted peers.
# Example: ALLOWED_PEER_CIDRS=10.16.17.0/24,10.0.0.0/24
_raw_cidrs = os.getenv("ALLOWED_PEER_CIDRS", "")
ALLOWED_PEER_NETWORKS: List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = []
for cidr in _raw_cidrs.split(","):
    cidr = cidr.strip()
    if cidr:
        try:
            ALLOWED_PEER_NETWORKS.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            pass  # Logged at startup via main.py; skip malformed entries here

class GatewayBase(BaseModel):
    """Base schema for gateway data."""
    model_config = ConfigDict(from_attributes=True)

    alias: str
    public_url: str
    internal_url: Optional[str] = None
    capabilities: Optional[List[str]] = []

class GatewayCreate(GatewayBase):
    """Schema for creating or updating a gateway registration with validation."""

    @field_validator('public_url', 'internal_url', mode='before')
    @classmethod
    def validate_url_and_ssrf(cls, v: Optional[str]) -> Optional[str]:
        """Validate URL format and prevent SSRF attacks."""
        if v is None:
            return v

        # Step 1: Validate URL format
        if not v or '://' not in v:
            raise ValueError(f"Invalid URL format: {v} (must include scheme like http:// or https://)")

        try:
            parsed = urlparse(v)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(f"Invalid URL: {v} (missing scheme or host)")

            if parsed.scheme not in ['http', 'https']:
                raise ValueError(f"Invalid URL scheme: {parsed.scheme} (must be http or https)")
        except ValueError:
            raise  # Re-raise our validation errors
        except Exception as e:
            raise ValueError(f"URL parsing failed: {v} - {str(e)}")

        # Step 2: SSRF prevention - block dangerous IPs
        try:
            hostname = parsed.hostname

            if not hostname:
                return v

            # Try to parse as IP address
            try:
                ip = ipaddress.ip_address(hostname)

                # Always block loopback and link-local (never valid for peer gateways)
                if ip.is_loopback or ip.is_link_local:
                    raise ValueError(
                        f"SSRF prevention: Loopback/link-local addresses not allowed: {hostname}"
                    )

                # Block AWS metadata endpoint
                if str(ip) == "169.254.169.254":
                    raise ValueError("SSRF prevention: AWS metadata endpoint not allowed")

                # Private IPs require explicit CIDR allowlist (zero-trust)
                if ip.is_private:
                    if not any(ip in network for network in ALLOWED_PEER_NETWORKS):
                        raise ValueError(
                            f"SSRF prevention: Private IP {hostname} not in ALLOWED_PEER_CIDRS. "
                            f"Configure ALLOWED_PEER_CIDRS env var with trusted CIDR ranges "
                            f"(e.g., ALLOWED_PEER_CIDRS=10.16.17.0/24,10.0.0.0/24)."
                        )

            except ValueError as ip_error:
                # Check if this is our validation error or just "not an IP"
                if "SSRF prevention" in str(ip_error):
                    raise  # Re-raise our validation errors

                # Not an IP address - hostname/domain is fine
                # Check for localhost patterns
                if hostname.lower() in ['localhost', '127.0.0.1', '0.0.0.0']:
                    raise ValueError(f"SSRF prevention: localhost not allowed: {hostname}")

        except ValueError:
            raise  # Re-raise validation errors

        return v

class GatewayHealthUpdate(BaseModel):
    """Schema for posting a health status update."""
    status: str
    details: Optional[str] = None

class Gateway(GatewayBase):
    """
    The main schema for a gateway, used for API responses.
    Includes all fields from the database model.
    """
    health_status: str
    last_health_check: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime] = None