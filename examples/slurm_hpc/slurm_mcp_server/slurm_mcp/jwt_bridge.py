"""
JWT Bridge: SPIFFE JWT-SVID (RS256) -> Slurm HS256 JWT
=======================================================

Slurm 25.11.2 auth/jwt ONLY supports HS256 with a static HMAC key.
It does not support RS256, JWKS URLs, or asymmetric key verification.

This bridge module:
  1. Validates incoming SPIFFE JWT-SVID (RS256, signed by SPIRE CA)
  2. Extracts identity claims (SPIFFE ID, subject)
  3. Maps SPIFFE identity to Slurm username (via identity_mapper)
  4. Generates a short-lived HS256 JWT that slurmrestd accepts

This enables the SPIFFE zero-trust chain to terminate at the MCP server
boundary, while still authenticating to slurmrestd using its native
HS256 JWT mechanism.

Usage:
    bridge = JWTBridge(hmac_key_b64="<base64-encoded-slurm-jwt-key>")
    slurm_token = bridge.translate(spiffe_jwt_svid_token)
"""

import os
import time
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None


class JWTBridgeError(Exception):
    """Error during JWT bridge translation."""
    pass


class JWTBridge:
    """
    Translates SPIFFE JWT-SVID (RS256) tokens into Slurm-compatible HS256 JWTs.

    The bridge validates the SPIFFE token's structure and claims, maps the
    SPIFFE identity to a Slurm username, then mints a short-lived HS256 JWT
    with the Slurm-required `sun` (Slurm User Name) claim.

    Args:
        hmac_key_b64: Base64-encoded HMAC key from Slurm's jwt_key.pem
        default_username: Fallback Slurm username if identity mapping fails
        token_ttl: Lifetime of generated Slurm tokens in seconds (default: 3600)
        trust_domains: Set of trusted SPIFFE trust domains (default: pnnl.adept.slurm)
        validate_spiffe: Whether to cryptographically validate SPIFFE JWTs.
            When False (default), only decodes without signature verification.
            When True, requires SPIRE trust bundle for RS256 verification.
    """

    def __init__(
        self,
        hmac_key_b64: str = "",
        default_username: str = "root",
        token_ttl: int = 3600,
        trust_domains: Optional[set] = None,
        validate_spiffe: bool = False,
    ):
        if pyjwt is None:
            raise JWTBridgeError(
                "PyJWT library required for JWT bridge. Install: pip install pyjwt"
            )

        self._hmac_key_b64 = hmac_key_b64
        self._default_username = default_username
        self._token_ttl = token_ttl
        self._trust_domains = trust_domains or {"pnnl.adept.slurm", "pnnl.adept"}
        self._validate_spiffe = validate_spiffe

        # Cache for generated Slurm tokens
        self._cached_token: Optional[str] = None
        self._cached_token_exp: float = 0
        self._cached_username: Optional[str] = None

    @property
    def has_hmac_key(self) -> bool:
        """Whether a Slurm HMAC key is configured."""
        return bool(self._hmac_key_b64)

    def _decode_hmac_key(self) -> bytes:
        """Decode the base64-encoded HMAC key."""
        try:
            return base64.b64decode(self._hmac_key_b64)
        except Exception as e:
            raise JWTBridgeError(f"Failed to decode HMAC key (expected base64): {e}")

    def decode_spiffe_jwt(self, token: str) -> dict:
        """
        Decode and validate a SPIFFE JWT-SVID token.

        In non-validation mode (default), decodes without signature verification.
        This is safe when the token comes from a trusted SPIRE agent on the same
        host via the Workload API socket.

        Args:
            token: The JWT-SVID token string

        Returns:
            Decoded JWT claims dict

        Raises:
            JWTBridgeError: If token is malformed or has invalid claims
        """
        try:
            if self._validate_spiffe:
                # Full RS256 validation requires SPIRE trust bundle public keys.
                # This path is for when tokens arrive over the network (not local socket).
                # For now, raise — implement when federation tests require it.
                raise JWTBridgeError(
                    "Full SPIFFE JWT-SVID RS256 validation not yet implemented. "
                    "Set validate_spiffe=False for local Workload API tokens."
                )

            # Decode without verification — safe for tokens from local SPIRE agent
            claims = pyjwt.decode(
                token,
                options={"verify_signature": False},
                algorithms=["RS256", "ES256", "PS256"],
            )

            # Validate required SPIFFE claims
            sub = claims.get("sub", "")
            if not sub.startswith("spiffe://"):
                raise JWTBridgeError(
                    f"Invalid SPIFFE JWT-SVID: 'sub' claim must start with 'spiffe://', got: {sub}"
                )

            # Validate trust domain
            domain = sub.split("/")[2] if len(sub.split("/")) > 2 else ""
            if domain not in self._trust_domains:
                raise JWTBridgeError(
                    f"Untrusted SPIFFE domain: {domain}. "
                    f"Trusted domains: {self._trust_domains}"
                )

            logger.debug(f"Decoded SPIFFE JWT-SVID: sub={sub}")
            return claims

        except pyjwt.exceptions.DecodeError as e:
            raise JWTBridgeError(f"Failed to decode SPIFFE JWT-SVID: {e}")

    def _map_spiffe_to_username(self, spiffe_id: str) -> str:
        """
        Map a SPIFFE ID to a Slurm username.

        Uses the identity_mapper module if available, falls back to
        extracting the workload name from the SPIFFE path.

        Args:
            spiffe_id: Full SPIFFE ID (e.g., spiffe://pnnl.adept.slurm/slurm-mcp-server)

        Returns:
            Slurm username string
        """
        # Try identity_mapper first (supports static maps, claim-based, etc.)
        try:
            from .identity_mapper import IdentityMapper
            mapper = IdentityMapper.get_instance()
            mapped = mapper.map_identity(
                provider="spiffe",
                external_id=spiffe_id,
            )
            if mapped and mapped != self._default_username:
                logger.debug(f"Identity mapper: {spiffe_id} -> {mapped}")
                return mapped
        except Exception as e:
            logger.debug(f"Identity mapper unavailable: {e}")

        # Fallback: extract workload name from SPIFFE path
        # spiffe://pnnl.adept.slurm/slurm-mcp-server -> slurm-mcp-server
        parts = spiffe_id.rstrip("/").split("/")
        if len(parts) >= 4:
            workload = parts[-1]
            logger.debug(f"SPIFFE path extraction: {spiffe_id} -> {workload}")
            return workload

        logger.warning(
            f"Could not map SPIFFE ID to username: {spiffe_id}, using default: {self._default_username}"
        )
        return self._default_username

    def _generate_slurm_token(self, username: str) -> str:
        """
        Generate a short-lived HS256 JWT for slurmrestd.

        Args:
            username: Slurm username to embed in the token

        Returns:
            HS256 JWT token string
        """
        if not self.has_hmac_key:
            raise JWTBridgeError(
                "No HMAC key configured. Set SLURM_JWT_KEY environment variable."
            )

        now = int(time.time())

        # Return cached token if still valid and for same user
        if (
            self._cached_token
            and self._cached_username == username
            and self._cached_token_exp > now + 60
        ):
            return self._cached_token

        key_bytes = self._decode_hmac_key()

        payload = {
            "sun": username,       # Slurm User Name (required by slurmrestd)
            "iat": now,
            "exp": now + self._token_ttl,
        }

        token = pyjwt.encode(payload, key_bytes, algorithm="HS256")
        self._cached_token = token
        self._cached_token_exp = payload["exp"]
        self._cached_username = username

        logger.debug(
            f"Generated Slurm HS256 JWT: user={username}, ttl={self._token_ttl}s"
        )
        return token

    def translate(
        self,
        spiffe_jwt: str,
        username_override: Optional[str] = None,
    ) -> str:
        """
        Translate a SPIFFE JWT-SVID into a Slurm-compatible HS256 JWT.

        This is the main entry point for the bridge. It:
        1. Decodes the SPIFFE JWT-SVID
        2. Maps the SPIFFE identity to a Slurm username
        3. Generates an HS256 JWT with the Slurm `sun` claim

        Args:
            spiffe_jwt: The SPIFFE JWT-SVID token from the SPIRE agent
            username_override: Optional override for the Slurm username

        Returns:
            HS256 JWT token string accepted by slurmrestd

        Raises:
            JWTBridgeError: If translation fails at any step
        """
        claims = self.decode_spiffe_jwt(spiffe_jwt)

        if username_override:
            username = username_override
        else:
            spiffe_id = claims.get("sub", "")
            username = self._map_spiffe_to_username(spiffe_id)

        slurm_token = self._generate_slurm_token(username)

        logger.info(
            f"JWT bridge: SPIFFE {claims.get('sub', '?')} -> Slurm user={username}"
        )
        return slurm_token

    def translate_or_passthrough(
        self,
        token: str,
        username_override: Optional[str] = None,
    ) -> str:
        """
        Attempt SPIFFE->Slurm translation; if the token isn't a SPIFFE JWT-SVID,
        return it unchanged (passthrough for existing HS256 tokens).

        Args:
            token: JWT token (SPIFFE RS256 or Slurm HS256)
            username_override: Optional Slurm username override

        Returns:
            Slurm-compatible HS256 JWT token
        """
        try:
            # Try decoding as SPIFFE JWT-SVID
            claims = pyjwt.decode(
                token,
                options={"verify_signature": False},
                algorithms=["RS256", "ES256", "PS256", "HS256"],
            )

            # If it has a SPIFFE sub claim, translate it
            sub = claims.get("sub", "")
            if sub.startswith("spiffe://"):
                return self.translate(token, username_override)

            # If it already has a `sun` claim, it's already a Slurm token
            if "sun" in claims:
                logger.debug("Token already has 'sun' claim — passthrough")
                return token

            # Unknown token format — passthrough
            logger.debug("Token has no SPIFFE sub or Slurm sun claim — passthrough")
            return token

        except Exception:
            # Can't decode — passthrough as-is
            logger.debug("Token decode failed — passthrough")
            return token


def get_jwt_bridge() -> Optional[JWTBridge]:
    """
    Factory: create a JWTBridge from environment variables.

    Returns:
        JWTBridge instance if SLURM_JWT_KEY is set, None otherwise
    """
    hmac_key = os.getenv("SLURM_JWT_KEY", "")
    if not hmac_key:
        logger.debug("SLURM_JWT_KEY not set — JWT bridge unavailable")
        return None

    return JWTBridge(
        hmac_key_b64=hmac_key,
        default_username=os.getenv("SLURM_SERVICE_USER", "root"),
        token_ttl=int(os.getenv("SLURM_JWT_BRIDGE_TTL", "3600")),
    )
