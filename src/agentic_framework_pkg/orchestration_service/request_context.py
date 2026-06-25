"""Request Context for Tool Execution

Carries HTTP request metadata through the agent creation pipeline to enable
tools to generate user-facing URLs with correct hostnames.

This module provides the RequestContext dataclass for threading request context
(X-Forwarded-Host, X-Forwarded-Proto, etc.) from HTTP endpoints through the
agent creation pipeline to tool wrappers, enabling proper URL generation for
presigned URLs and other tools that need external hostname information.

Key Features:
- Immutable dataclass (thread-safe)
- Extraction from FastAPI Request objects
- Base URL construction with multiple access pattern support
- Port forwarding detection for development workflows

Usage:
    # In router endpoint
    from fastapi import Request
    from .request_context import RequestContext

    async def endpoint(http_request: Request):
        context = RequestContext.from_request(http_request)
        # Pass context through service layer to agent creation
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RequestContext:
    """Immutable request context for tool execution.

    Carries HTTP request metadata (forwarded headers, client info) through the
    agent creation pipeline to enable tools to generate user-facing URLs with
    correct hostnames.

    Attributes:
        forwarded_host: Value of X-Forwarded-Host header (e.g., "api.agentic.local")
        forwarded_proto: Value of X-Forwarded-Proto header (e.g., "https")
        forwarded_port: Value of X-Forwarded-Port header (e.g., "443")
        remote_addr: Client IP address from X-Real-IP or direct connection
        user_agent: Client User-Agent header

    Example:
        >>> ctx = RequestContext(
        ...     forwarded_host="api.agentic.local",
        ...     forwarded_proto="https",
        ...     forwarded_port="443"
        ... )
        >>> ctx.get_base_url()
        'https://api.agentic.local'
    """

    forwarded_host: Optional[str] = None
    forwarded_proto: Optional[str] = None
    forwarded_port: Optional[str] = None
    remote_addr: Optional[str] = None
    user_agent: Optional[str] = None

    @classmethod
    def from_request(cls, request) -> "RequestContext":
        """Extract context from FastAPI Request object.

        Args:
            request: FastAPI Request object with headers and client info

        Returns:
            RequestContext with extracted headers

        Example:
            >>> from fastapi import Request
            >>> ctx = RequestContext.from_request(http_request)
            >>> ctx.forwarded_host
            'api.agentic.local'
        """
        return cls(
            forwarded_host=request.headers.get("X-Forwarded-Host"),
            forwarded_proto=request.headers.get("X-Forwarded-Proto"),
            forwarded_port=request.headers.get("X-Forwarded-Port"),
            remote_addr=request.headers.get("X-Real-IP") or request.client.host,
            user_agent=request.headers.get("User-Agent"),
        )

    def get_base_url(self) -> str:
        """Construct base URL from forwarded headers.

        Handles multiple access patterns:
        1. **External FQDN**: https://api.agentic.local (production)
        2. **Port forwarding**: http://localhost:8443 (development via SSH tunnel)
        3. **Direct access**: http://agent_gateway:8081 (container-to-container)

        Returns:
            Base URL with scheme and host (e.g., "https://api.agentic.local")

        Example:
            >>> # Production access
            >>> ctx = RequestContext(
            ...     forwarded_host="api.agentic.local",
            ...     forwarded_proto="https"
            ... )
            >>> ctx.get_base_url()
            'https://api.agentic.local'

            >>> # Port forwarding (development)
            >>> ctx = RequestContext(
            ...     forwarded_host="localhost",
            ...     forwarded_proto="http",
            ...     forwarded_port="8443"
            ... )
            >>> ctx.get_base_url()
            'http://localhost:8443'

            >>> # No forwarded headers (fallback)
            >>> ctx = RequestContext()
            >>> ctx.get_base_url()
            'http://localhost:8083'
        """
        if not self.forwarded_host:
            # Fallback chain: NGINX_EXTERNAL_URL → PUBLIC_BASE_URL → localhost
            # Use NGINX_EXTERNAL_URL or PUBLIC_BASE_URL from environment
            return (
                os.getenv("NGINX_EXTERNAL_URL")
                or os.getenv("PUBLIC_BASE_URL", "http://localhost:8083")
            )

        proto = self.forwarded_proto or "http"
        host = self.forwarded_host

        # Include port if non-standard (common for port forwarding scenarios)
        if self.forwarded_port and self.forwarded_port not in ("80", "443"):
            host = f"{host}:{self.forwarded_port}"

        return f"{proto}://{host}"

    @property
    def is_port_forwarding(self) -> bool:
        """Detect if request is via port forwarding.

        Port forwarding is common in development workflows where developers use
        SSH tunnels to access services:
        - ssh -L 8443:agent_gateway:8081 user@host
        - Results in: localhost:8443 → agent_gateway:8081

        Detection criteria:
        - Host is localhost or 127.0.0.1
        - Port is non-standard (not 80, 443, or 8081)

        Returns:
            True if request appears to be via port forwarding

        Example:
            >>> # Port forwarding scenario
            >>> ctx = RequestContext(
            ...     forwarded_host="localhost",
            ...     forwarded_port="8443"
            ... )
            >>> ctx.is_port_forwarding
            True

            >>> # Production scenario
            >>> ctx = RequestContext(
            ...     forwarded_host="api.agentic.local",
            ...     forwarded_port="443"
            ... )
            >>> ctx.is_port_forwarding
            False
        """
        if not self.forwarded_host:
            return False

        # Check for localhost patterns
        host_lower = self.forwarded_host.lower()
        is_localhost = host_lower in ("localhost", "127.0.0.1") or host_lower.startswith(
            "localhost:"
        )

        # Port forwarding typically uses non-standard ports
        # Ensure boolean result (not None) by using explicit bool conversion
        has_custom_port = bool(
            self.forwarded_port and self.forwarded_port not in ("80", "443", "8081")
        )

        return is_localhost and has_custom_port
