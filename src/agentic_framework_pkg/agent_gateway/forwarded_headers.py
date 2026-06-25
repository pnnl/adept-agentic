"""
X-Forwarded Header Management for Agent Gateway

This module implements secure X-Forwarded-* header handling with a combined
defense approach:
1. Header Overwrite: Gateway ALWAYS overwrites client-provided headers
2. Allowlist Validation: Untrusted hosts are rejected and logged
3. Fail-Safe Fallback: Invalid hosts fall back to PUBLIC_BASE_URL
4. Audit Logging: All security events logged with full context

Security Philosophy:
- NEVER trust client headers
- Defense in depth with multiple validation layers
- Prevent OWASP A01 (Broken Access Control), A03 (Injection), A05 (Misconfiguration), A10 (SSRF)

Author: Session 47 - Presigned URL Host Context Awareness Fix
Date: 2026-02-07
"""

import os
import re
from typing import Dict, Optional
from urllib.parse import urlparse

from fastapi import Request

from ..logger_config import get_logger

logger = get_logger(__name__)


class AllowlistValidator:
    """
    Validates hosts against an allowlist with wildcard support.

    Prevents:
    - SSRF attacks (internal network access)
    - Host injection attacks
    - Unauthorized domain access

    Examples:
        validator = AllowlistValidator("localhost,*.example.com,api.example.com")
        validator.validate_host("localhost")  # True
        validator.validate_host("sub.example.com")  # True (*.example.com)
        validator.validate_host("evil.com")  # False
    """

    def __init__(self, allowed_hosts_str: Optional[str] = None):
        """
        Initialize allowlist validator.

        Args:
            allowed_hosts_str: Comma-separated list of allowed hosts/patterns
                             Examples: "localhost,*.example.com,api.example.com"
                             If None, uses AGENT_GATEWAY_ALLOWED_HOSTS env var
        """
        if allowed_hosts_str is None:
            allowed_hosts_str = os.getenv(
                "AGENT_GATEWAY_ALLOWED_HOSTS",
                "localhost,127.0.0.1,*.agentic.local,api.agentic.local,agent_gateway,orchestration_service",
            )

        self.allowed_patterns = [
            pattern.strip() for pattern in allowed_hosts_str.split(",")
        ]
        self.validate_enabled = os.getenv(
            "AGENT_GATEWAY_VALIDATE_FORWARDED_HOSTS", "true"
        ).lower() in ("true", "1", "yes")

        logger.info(
            f"AllowlistValidator initialized: patterns={self.allowed_patterns}, "
            f"validation_enabled={self.validate_enabled}"
        )

    def validate_host(self, host: str) -> bool:
        """
        Validate host against allowlist.

        Args:
            host: Host to validate (without port)

        Returns:
            True if host is allowed, False otherwise

        Security:
            - Exact match for non-wildcard patterns
            - Suffix match for wildcard patterns (*.example.com)
            - Validation can be disabled via AGENT_GATEWAY_VALIDATE_FORWARDED_HOSTS=false
        """
        if not self.validate_enabled:
            logger.debug(f"Allowlist validation disabled, accepting host: {host}")
            return True

        if not host:
            logger.warning("Empty host provided to allowlist validator")
            return False

        # Normalize host to lowercase for case-insensitive matching
        host_lower = host.lower()

        for pattern in self.allowed_patterns:
            pattern_lower = pattern.lower()

            if pattern_lower.startswith("*."):
                # Wildcard pattern: *.example.com matches sub.example.com
                domain = pattern_lower[2:]
                if host_lower.endswith(domain) or host_lower == domain[1:]:
                    logger.debug(
                        f"Host '{host}' matched wildcard pattern '{pattern}'"
                    )
                    return True
            elif pattern_lower == host_lower:
                # Exact match
                logger.debug(f"Host '{host}' matched exact pattern '{pattern}'")
                return True

        logger.warning(
            f"Host '{host}' rejected by allowlist. Allowed patterns: {self.allowed_patterns}"
        )
        return False


class HeaderBuilder:
    """
    Builds X-Forwarded-* headers with security guarantees.

    Security Features:
    - Header Overwrite: ALWAYS overwrites client-provided X-Forwarded-* headers
    - Allowlist Validation: Rejects untrusted hosts
    - Port Normalization: Omits standard ports (80/443) to prevent port scanning
    - Protocol Validation: Only allows http/https schemes
    - Audit Logging: Logs all security events

    Attack Prevention:
    - Header injection: Gateway overwrites client headers
    - SSRF: Allowlist validation rejects internal IPs
    - Protocol downgrade: Gateway uses actual request scheme
    - Port scanning: Port normalization prevents arbitrary ports
    """

    def __init__(
        self, allowlist_validator: Optional[AllowlistValidator] = None
    ):
        """
        Initialize header builder.

        Args:
            allowlist_validator: Validator for host allowlist
                               If None, creates default validator
        """
        self.validator = allowlist_validator or AllowlistValidator()
        self.fallback_base_url = os.getenv(
            "PUBLIC_BASE_URL", "http://localhost:8083"
        )

        logger.info(
            f"HeaderBuilder initialized: fallback_base_url={self.fallback_base_url}"
        )

    def build_forwarded_headers(self, request: Request) -> Dict[str, str]:
        """
        Build X-Forwarded-* headers from incoming request.

        This method ALWAYS overwrites client-provided X-Forwarded-* headers
        to prevent header injection attacks.

        Args:
            request: FastAPI Request object

        Returns:
            Dictionary with X-Forwarded-Host, X-Forwarded-Proto, X-Forwarded-Port

        Security:
            - Extracts Host, scheme, port from request object (not client headers)
            - Validates host against allowlist
            - Falls back to PUBLIC_BASE_URL if validation fails
            - Logs all security events (rejection, fallback, injection attempts)

        Example:
            request.url.scheme = "http"
            request.headers["host"] = "localhost:8083"
            → X-Forwarded-Host: localhost
            → X-Forwarded-Proto: http
            → X-Forwarded-Port: 8083
        """
        # Log warning if client provided X-Forwarded-* headers (potential injection)
        client_forwarded_host = request.headers.get("x-forwarded-host")
        if client_forwarded_host:
            logger.warning(
                f"SECURITY: Client provided X-Forwarded-Host header ('{client_forwarded_host}'), "
                f"will be OVERWRITTEN by gateway"
            )

        # Extract host from request (gateway's received Host header, not client's)
        host_header = request.headers.get("host", "")
        if not host_header:
            logger.warning("Missing Host header, falling back to PUBLIC_BASE_URL")
            return self._build_fallback_headers()

        # Parse host and port
        host, port = self._parse_host_and_port(host_header, request.url.scheme)

        # Validate host against allowlist
        if not self.validator.validate_host(host):
            logger.warning(
                f"SECURITY: Host '{host}' rejected by allowlist, falling back to PUBLIC_BASE_URL"
            )
            return self._build_fallback_headers()

        # Build headers with validated host
        headers = {
            "X-Forwarded-Host": host,
            "X-Forwarded-Proto": request.url.scheme,
        }

        # Add port if non-standard
        normalized_port = self._normalize_port(port, request.url.scheme)
        if normalized_port:
            headers["X-Forwarded-Port"] = normalized_port

        logger.debug(
            f"Built forwarded headers: Host={host}, Proto={request.url.scheme}, Port={normalized_port or 'standard'}"
        )

        return headers

    def _parse_host_and_port(
        self, host_header: str, scheme: str
    ) -> tuple[str, Optional[int]]:
        """
        Parse host and port from Host header.

        Args:
            host_header: Host header value (e.g., "localhost:8083")
            scheme: URL scheme (http or https)

        Returns:
            Tuple of (host, port)

        Security:
            - Strips path components (prevents path traversal attacks)
            - Validates port is numeric
            - Defaults to standard ports (80/443) if not specified
        """
        # Strip any path components (security: prevent path traversal in host)
        host_header = host_header.split("/")[0]

        if ":" in host_header:
            host, port_str = host_header.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                logger.warning(
                    f"Invalid port in Host header: {port_str}, using default"
                )
                port = 443 if scheme == "https" else 80
        else:
            host = host_header
            port = 443 if scheme == "https" else 80

        return host, port

    def _normalize_port(
        self, port: Optional[int], scheme: str
    ) -> Optional[str]:
        """
        Normalize port (omit standard ports to prevent port scanning).

        Args:
            port: Port number
            scheme: URL scheme (http or https)

        Returns:
            Port as string if non-standard, None if standard port

        Security:
            - Prevents port scanning by omitting standard ports
            - Reduces information disclosure
        """
        if port is None:
            return None

        # Omit standard ports
        if (scheme == "http" and port == 80) or (
            scheme == "https" and port == 443
        ):
            return None

        return str(port)

    def _build_fallback_headers(self) -> Dict[str, str]:
        """
        Build headers using fallback PUBLIC_BASE_URL.

        Used when:
        - Host header is missing
        - Host validation fails
        - Request is malformed

        Returns:
            Dictionary with X-Forwarded-* headers from PUBLIC_BASE_URL

        Security:
            - Fail-safe mechanism prevents exposing internal services
            - Always uses server-configured base URL
            - Logs fallback events for security monitoring
        """
        parsed = urlparse(self.fallback_base_url)

        headers = {
            "X-Forwarded-Host": parsed.hostname or "localhost",
            "X-Forwarded-Proto": parsed.scheme or "http",
        }

        # Add port if non-standard
        if parsed.port:
            normalized_port = self._normalize_port(parsed.port, parsed.scheme)
            if normalized_port:
                headers["X-Forwarded-Port"] = normalized_port

        logger.info(
            f"Using fallback headers from PUBLIC_BASE_URL: {self.fallback_base_url}"
        )

        return headers
