"""
SPIFFE Workload Identity Authentication
========================================

Provides JWT-SVID and x509-SVID authentication for Slurm MCP server.
Replaces HMAC-based JWTTokenManager when SPIFFE_ENABLED=true.

Requires:
    - SPIRE agent running with Workload API socket
    - py-spiffe >= 0.8.0
    - Workload entry registered for this container
"""

import os
import ssl
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Feature flag
SPIFFE_ENABLED = os.getenv("SPIFFE_ENABLED", "false").lower() in ("true", "1", "yes")
SPIFFE_ENDPOINT_SOCKET = os.getenv(
    "SPIFFE_ENDPOINT_SOCKET", "unix:///run/spire/sockets/agent.sock"
)

# Lazy-loaded SPIFFE client
_workload_client = None


def _get_workload_client():
    """Get or create the SPIFFE Workload API client (lazy singleton)."""
    global _workload_client
    if _workload_client is not None:
        return _workload_client

    try:
        from spiffe import WorkloadApiClient
    except ImportError:
        logger.error(
            "spiffe not installed. Install with: pip install spiffe"
        )
        return None

    try:
        _workload_client = WorkloadApiClient(spiffe_socket=SPIFFE_ENDPOINT_SOCKET)
        logger.info(f"SPIFFE WorkloadApiClient connected to {SPIFFE_ENDPOINT_SOCKET}")
        return _workload_client
    except Exception as e:
        logger.error(f"Failed to create SPIFFE WorkloadApiClient: {e}")
        return None


def get_jwt_svid(audience: str = "slurmrestd") -> Optional[str]:
    """
    Fetch a JWT-SVID from the local SPIRE agent.

    Args:
        audience: The intended audience for the JWT-SVID (default: "slurmrestd")

    Returns:
        JWT-SVID token string, or None if SPIFFE is not available
    """
    if not SPIFFE_ENABLED:
        return None

    client = _get_workload_client()
    if client is None:
        return None

    try:
        jwt_svid_set = client.fetch_jwt_svids(
            audiences=[audience],
        )
        if jwt_svid_set and len(jwt_svid_set) > 0:
            svid = jwt_svid_set[0]
            logger.debug(
                f"Fetched JWT-SVID: spiffe_id={svid.spiffe_id}, audience={audience}"
            )
            return svid.token
        else:
            logger.warning("No JWT-SVIDs returned from SPIRE agent")
            return None
    except Exception as e:
        logger.warning(f"Failed to fetch JWT-SVID: {e}")
        return None


def get_x509_svid() -> Optional[Tuple[bytes, bytes, bytes]]:
    """
    Fetch an x509-SVID from the local SPIRE agent.

    Returns:
        Tuple of (cert_pem, key_pem, bundle_pem) or None if not available
    """
    if not SPIFFE_ENABLED:
        return None

    client = _get_workload_client()
    if client is None:
        return None

    try:
        x509_svid = client.fetch_x509_svid()
        if x509_svid:
            logger.debug(f"Fetched x509-SVID: spiffe_id={x509_svid.spiffe_id}")
            return (
                x509_svid.cert_chain_pem,
                x509_svid.private_key_pem,
                x509_svid.bundle_pem,
            )
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch x509-SVID: {e}")
        return None


def get_mtls_ssl_context() -> Optional[ssl.SSLContext]:
    """
    Create an SSL context using x509-SVID for mTLS connections.

    Returns:
        ssl.SSLContext configured for mTLS, or None if not available
    """
    svid = get_x509_svid()
    if svid is None:
        return None

    cert_pem, key_pem, bundle_pem = svid

    try:
        import tempfile

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2

        # Write PEM data to temp files (ssl module requires file paths)
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as cert_f:
            cert_f.write(cert_pem)
            cert_path = cert_f.name
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as key_f:
            key_f.write(key_pem)
            key_path = key_f.name
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as ca_f:
            ca_f.write(bundle_pem)
            ca_path = ca_f.name

        ctx.load_cert_chain(cert_path, key_path)
        ctx.load_verify_locations(ca_path)
        ctx.verify_mode = ssl.CERT_REQUIRED

        # Clean up temp files
        for path in (cert_path, key_path, ca_path):
            try:
                os.unlink(path)
            except OSError:
                pass

        logger.info("Created mTLS SSL context from x509-SVID")
        return ctx
    except Exception as e:
        logger.error(f"Failed to create mTLS SSL context: {e}")
        return None
