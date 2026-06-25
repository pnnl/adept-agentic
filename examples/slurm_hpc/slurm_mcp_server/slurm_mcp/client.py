"""
SLURM API Client
================

HTTP client for SLURM REST API with JWT authentication.
Includes JWTTokenManager for on-the-fly token generation from HMAC key.
"""

import time
import base64
from typing import Optional, Dict, Any

import httpx

try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None


class SlurmError(Exception):
    """SLURM API error with optional status code."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class JWTTokenManager:
    """
    Manages JWT tokens for Slurm REST API authentication.

    Prefers SLURM_JWT_KEY (generates tokens on-the-fly, never expires)
    over SLURM_SERVICE_JWT (static token, may expire).
    """

    def __init__(self, jwt_key: str = "", service_jwt: str = "", service_user: str = "root"):
        self._jwt_key_b64 = jwt_key
        self._service_jwt = service_jwt
        self._service_user = service_user
        self._cached_token: Optional[str] = None
        self._cached_token_exp: float = 0

    @property
    def has_hmac_key(self) -> bool:
        return bool(self._jwt_key_b64)

    @property
    def has_static_token(self) -> bool:
        return bool(self._service_jwt)

    def get_token(self, username: Optional[str] = None) -> str:
        """
        Get a valid JWT token for the Slurm REST API.

        Priority:
        1. SPIFFE JWT-SVID → JWT Bridge (RS256 → HS256) if SPIFFE_ENABLED=true
        2. HMAC key generation (if SLURM_JWT_KEY set)
        3. Static service JWT (if SLURM_SERVICE_JWT set)

        Note: slurmrestd 25.11.2 only supports HS256. When SPIFFE is enabled,
        the JWT bridge translates the SPIRE RS256 JWT-SVID into an HS256 token
        that slurmrestd accepts. The SPIFFE token is never sent directly to
        slurmrestd (it would be rejected).
        """
        # Try SPIFFE JWT-SVID with JWT bridge translation (highest priority)
        from .spiffe_auth import SPIFFE_ENABLED, get_jwt_svid
        if SPIFFE_ENABLED:
            svid_token = get_jwt_svid(audience="slurmrestd")
            if svid_token:
                # Translate RS256 SPIFFE JWT-SVID -> HS256 Slurm JWT via bridge
                from .jwt_bridge import get_jwt_bridge
                bridge = get_jwt_bridge()
                if bridge:
                    return bridge.translate(
                        svid_token,
                        username_override=username or self._service_user,
                    )
                # No bridge available — return raw SVID (will fail against slurmrestd
                # unless it's been configured for RS256, which stock Slurm does not do)
                return svid_token

        # Fall back to HMAC key generation
        if self.has_hmac_key:
            return self._generate_token(username or self._service_user)
        elif self.has_static_token:
            return self._service_jwt
        else:
            raise SlurmError(
                "No JWT credentials available. Set SLURM_JWT_KEY (base64-encoded HMAC key), "
                "SLURM_SERVICE_JWT (static token), or enable SPIFFE_ENABLED=true."
            )

    def _generate_token(self, username: str) -> str:
        """Generate a short-lived JWT token using the HMAC key."""
        if pyjwt is None:
            raise SlurmError("PyJWT library required for token generation. Install: pip install pyjwt")

        now = int(time.time())

        # Return cached token if still valid (with 60s buffer)
        if self._cached_token and self._cached_token_exp > now + 60:
            return self._cached_token

        try:
            key_bytes = base64.b64decode(self._jwt_key_b64)
        except Exception as e:
            raise SlurmError(f"Failed to decode SLURM_JWT_KEY (expected base64): {e}")

        payload = {
            "sun": username,  # SLURM User Name
            "iat": now,
            "exp": now + 3600,  # 1 hour validity
        }

        token = pyjwt.encode(payload, key_bytes, algorithm="HS256")
        self._cached_token = token
        self._cached_token_exp = payload["exp"]
        return token

    @property
    def username(self) -> str:
        return self._service_user


class SlurmClient:
    """
    Async HTTP client for SLURM REST API operations.

    Uses JWTTokenManager for authentication.
    """

    def __init__(self, config, token_manager: JWTTokenManager):
        self.config = config
        self.token_manager = token_manager
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Async context manager entry."""
        token = self.token_manager.get_token()
        username = self.token_manager.username

        # Use mTLS if SPIFFE is enabled
        ssl_context = None
        from .spiffe_auth import SPIFFE_ENABLED, get_mtls_ssl_context
        if SPIFFE_ENABLED:
            ssl_context = get_mtls_ssl_context()

        self._client = httpx.AsyncClient(
            base_url=self.config.api_url,
            headers={
                "X-SLURM-USER-NAME": username,
                "X-SLURM-USER-TOKEN": token,
                "User-Agent": "SlurmMCP/0.2.0",
            },
            timeout=httpx.Timeout(self.config.timeout),
            verify=ssl_context if ssl_context else self.config.verify_ssl,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def request(
        self, method: str, endpoint: str, **kwargs
    ) -> Dict[str, Any]:
        """
        Make HTTP request to SLURM API with error handling.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint path
            **kwargs: Additional request parameters

        Returns:
            JSON response data

        Raises:
            SlurmError: On various API errors
        """
        if not self._client:
            raise RuntimeError("SlurmClient must be used as async context manager")

        try:
            response = await self._client.request(method, endpoint, **kwargs)
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code

            if status_code == 401:
                raise SlurmError(
                    "SLURM authentication failed - invalid or expired token",
                    status_code=status_code,
                )
            elif status_code == 403:
                raise SlurmError(
                    "SLURM authorization denied - insufficient permissions",
                    status_code=status_code,
                )
            elif status_code == 400:
                raise SlurmError(
                    "Invalid SLURM request parameters",
                    status_code=status_code,
                )
            elif status_code == 404:
                raise SlurmError(
                    "SLURM resource not found",
                    status_code=status_code,
                )
            elif status_code >= 500:
                raise SlurmError(
                    f"SLURM server error: {status_code}",
                    status_code=status_code,
                )
            else:
                raise SlurmError(
                    f"SLURM API error: {status_code}",
                    status_code=status_code,
                )

        except httpx.RequestError as e:
            raise SlurmError(f"Failed to connect to SLURM API: {str(e)}")


def get_service_client():
    """
    Get a SlurmClient configured with service credentials from environment.

    Returns:
        Tuple of (username, SlurmClient context manager)
    """
    from .config import config

    token_manager = JWTTokenManager(
        jwt_key=config.jwt_key,
        service_jwt=config.service_jwt,
        service_user=config.service_user,
    )

    client = SlurmClient(config, token_manager)
    return token_manager.username, client
