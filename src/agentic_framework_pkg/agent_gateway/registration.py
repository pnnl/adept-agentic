"""
This module handles the self-registration process for the Agent Gateway.

On startup, the gateway uses the functions in this module to announce its
presence to the central Gateway Registry service. This makes it discoverable
by other gateways in the mesh, enabling A2A (Agent-to-Agent) communication.
"""
import os
import httpx
import jwt  # PyJWT library to decode without validation
from ..logger_config import get_logger
from ..core.secrets_manager import get_secret

logger = get_logger(__name__)

async def get_s2s_token() -> str | None:
    """
    Fetches a service-to-service (S2S) JWT from Keycloak.

    This function uses the gateway's own client credentials (Client ID and Secret)
    to authenticate with Keycloak via the OAuth 2.0 Client Credentials grant type.
    The resulting token identifies the gateway itself, not an end-user, and is
    used for secure communication with other internal services like the Gateway Registry.

    Returns:
        The access token string if successful, otherwise None.
    """
    client_id = get_secret("AGENT_GATEWAY_CLIENT_ID")
    client_secret = get_secret("AGENT_GATEWAY_CLIENT_SECRET")

    # Instrumentation to check environment variables at runtime
    secret_status = "is set" if client_secret else "is NOT set or empty"
    secret_length = len(client_secret) if client_secret else 0
    logger.info(f"S2S AUTH PRE-FLIGHT CHECK: client_id='{client_id}', secret {secret_status}, secret_length={secret_length}")
    logger.debug(f"Full environment for debugging:\n{os.environ}")

    keycloak_url = os.getenv("KEYCLOAK_URL", "http://keycloak:8180")
    realm = os.getenv("KEYCLOAK_REALM", "master")

    if not all([client_id, client_secret]):
        logger.error("S2S AUTH: AGENT_GATEWAY_CLIENT_ID or AGENT_GATEWAY_CLIENT_SECRET not configured.")
        return None

    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }
    try:
        logger.debug(f"S2S AUTH: Requesting S2S token from Keycloak at {token_url} for client_id '{client_id}'.")
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=payload)
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data["access_token"]
            
            # For debugging, decode the token to log claims without validation
            try:
                unverified_header = jwt.get_unverified_header(access_token)
                logger.debug(f"S2S AUTH: Successfully obtained S2S token. Algorithm: {unverified_header.get('alg')}")
                decoded_token = jwt.decode(access_token, options={"verify_signature": False})
                logger.debug(f"S2S AUTH: Successfully obtained S2S token. Claims: sub={decoded_token.get('sub')}, exp={decoded_token.get('exp')}, client_id={decoded_token.get('clientId')}")
            except Exception as e:
                logger.warning(f"S2S AUTH: Could not decode obtained token for debugging purposes: {e}")

            return access_token
    except httpx.HTTPStatusError as e:
        logger.error(f"S2S AUTH: Failed to get S2S token from Keycloak. Status: {e.response.status_code}, Response: {e.response.text}", exc_info=True)
        # More verbose logging
        logger.error(f"S2S AUTH PAYLOAD SENT: {payload}")
        logger.error(f"S2S AUTH RESPONSE HEADERS: {e.response.headers}")
        return None
    except Exception as e:
        logger.error(f"S2S AUTH: An unexpected error occurred while getting S2S token: {e}", exc_info=True)
        return None

async def register_gateway_with_registry():
    """
    Registers this gateway instance with the central Gateway Registry service.

    It constructs a payload containing its public alias, public-facing URL for A2A
    communication, and an optional internal URL for local health checks. If registry
    authentication is enabled, it first obtains an S2S token to authorize the request.
    """
    alias = os.getenv("AGENT_GATEWAY_ALIAS")
    public_url = os.getenv("PUBLIC_GATEWAY_URL")
    service_name = os.getenv("AGENT_GATEWAY_SERVICE_NAME")
    registry_url = os.getenv("GATEWAY_REGISTRY_URL", "http://gateway_registry:8086")
    registry_auth_enabled = os.getenv("REGISTRY_AUTH_ENABLED", "true").lower() == "true"

    if not all([alias, public_url, registry_url]):
        logger.warning("REGISTRY: Self-registration skipped: Key environment variables (ALIAS, PUBLIC_URL, REGISTRY_URL) are not set.")
        return

    a2a_public_url = f"{public_url.rstrip('/')}/a2a"
    a2a_internal_url = f"http://{service_name}:8081/a2a" if service_name else None

    # Read capabilities from environment variable (comma-separated), falling back to defaults
    default_capabilities = ["RAG", "HPC-BLAST", "CodeExecution"]
    env_capabilities = os.getenv("AGENT_GATEWAY_CAPABILITIES", "")
    capabilities = [c.strip() for c in env_capabilities.split(",") if c.strip()] or default_capabilities

    registration_payload = {
        "alias": alias,
        "public_url": a2a_public_url,
        "internal_url": a2a_internal_url,
        "capabilities": capabilities,
    }

    headers = {"Content-Type": "application/json"}
    
    if registry_auth_enabled:
        logger.info("REGISTRY: Auth is enabled, fetching S2S token for self-registration.")
        token = await get_s2s_token()
        if not token:
            logger.warning("REGISTRY: Could not obtain S2S token for self-registration. Will retry on next health check cycle.")
            return
        headers["Authorization"] = f"Bearer {token}"
    else:
        logger.info("REGISTRY: Auth is disabled, proceeding with self-registration without a token.")

    logger.debug(f"REGISTRY: Attempting to register with Gateway Registry at {registry_url}. Headers: {list(headers.keys())}, Payload: {registration_payload}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(f"{registry_url}/v1/gateways", json=registration_payload, headers=headers)
            response.raise_for_status()
            logger.info(f"REGISTRY: Successfully registered with Gateway Registry. Response Status: {response.status_code}, Body: {response.json()}")
        except httpx.RequestError as e:
            logger.warning(f"REGISTRY: Could not connect to Gateway Registry at {registry_url} (network error). Will retry on next health check cycle. Error: {e}")
            return
        except httpx.HTTPStatusError as e:
            logger.warning(f"REGISTRY: Gateway Registry returned an error (status error). Will retry on next health check cycle. Status: {e.response.status_code}, Body: {e.response.text}")
            return
