"""
A2A gateway registration for multi-VM ADEPT mesh.
"""

import asyncio
import httpx
import os
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


class A2ARegistrar:
    """Manages A2A gateway registration in mesh topology.

    Phase 1 A2A Registration:
    - Uses nginx_proxy routing for external access (https://api.agentic.local/internal/registry)
    - Requires /etc/hosts entry: 127.0.0.1 api.agentic.local (for local testing)
    - Or set PUBLIC_HOSTNAME environment variable for production deployments
    """

    def __init__(
        self,
        registry_url: str = None,
        keycloak_url: str = None,
        keycloak_realm: str = "master"
    ):
        # Use PUBLIC_HOSTNAME or fall back to api.agentic.local (requires /etc/hosts)
        if registry_url is None:
            hostname = os.getenv("PUBLIC_HOSTNAME", "api.agentic.local")
            registry_url = f"https://{hostname}/internal/registry"

        if keycloak_url is None:
            keycloak_url = "http://localhost:8180"

        self.registry_url = registry_url
        self.keycloak_url = keycloak_url
        self.keycloak_realm = keycloak_realm

        logger.debug(f"A2ARegistrar initialized: registry_url={self.registry_url}, keycloak_url={self.keycloak_url}")

    @staticmethod
    def _discover_credential_from_files(name: str) -> Optional[str]:
        """
        Discover a credential value from the credentials directory.

        Searches (in order):
        1. deployment/local/docker-compose/.env-keycloak-credentials-dir/{name}
        2. .env-keycloak-credentials-dir/{name}
        3. /app/credentials/{name}  (inside Docker container)

        Args:
            name: Credential file name (e.g., "VALIDATION_RUNNER_CLIENT_ID")

        Returns:
            Credential value or None
        """
        # Try to find project root by walking up from this file
        search_dirs = []

        # Walk up from this module's directory to find project root
        module_dir = os.path.dirname(os.path.abspath(__file__))
        candidate = module_dir
        for _ in range(6):
            candidate = os.path.dirname(candidate)
            cred_dir = os.path.join(
                candidate,
                "deployment", "local", "docker-compose",
                ".env-keycloak-credentials-dir",
            )
            if os.path.isdir(cred_dir):
                search_dirs.append(cred_dir)
                break

        # Also check project-root-level credentials dir
        for _ in range(6):
            candidate = os.path.dirname(candidate) if candidate != "/" else "/"
            root_cred = os.path.join(candidate, ".env-keycloak-credentials-dir")
            if os.path.isdir(root_cred):
                search_dirs.append(root_cred)
                break

        # CWD-relative fallbacks
        cwd = os.getcwd()
        search_dirs.extend([
            os.path.join(cwd, "deployment", "local", "docker-compose", ".env-keycloak-credentials-dir"),
            os.path.join(cwd, ".env-keycloak-credentials-dir"),
        ])

        # Docker container path
        search_dirs.append("/app/credentials")

        for d in search_dirs:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                try:
                    with open(path, "r") as f:
                        value = f.read().strip()
                    if value:
                        logger.debug(f"Discovered {name} from {path}")
                        return value
                except OSError:
                    continue

        return None

    async def get_auth_token(self) -> Optional[str]:
        """
        Get authentication token for registry operations.

        Credential discovery priority:
        1. Environment variables (VALIDATION_RUNNER_CLIENT_ID/SECRET)
        2. Credential files from project credentials directory

        Returns:
            JWT access token or None if authentication fails
        """
        client_id = os.getenv("VALIDATION_RUNNER_CLIENT_ID")
        client_secret = os.getenv("VALIDATION_RUNNER_CLIENT_SECRET")

        # Fallback: discover from credential files
        if not client_id:
            client_id = self._discover_credential_from_files("VALIDATION_RUNNER_CLIENT_ID")
        if not client_secret:
            client_secret = self._discover_credential_from_files("VALIDATION_RUNNER_CLIENT_SECRET")

        if not client_id or not client_secret:
            logger.warning(
                "VALIDATION_RUNNER credentials not found in env vars or credentials directory. "
                "Set VALIDATION_RUNNER_CLIENT_ID/SECRET or check "
                "deployment/local/docker-compose/.env-keycloak-credentials-dir/"
            )
            return None

        token_endpoint = f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/token"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    token_endpoint,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret
                    }
                )
                response.raise_for_status()
                return response.json().get("access_token")

        except Exception as e:
            logger.error(f"Failed to get auth token: {e}")
            return None

    async def register_peer(
        self,
        alias: str,
        public_url: str,
        description: str = "",
        tags: List[str] = None
    ) -> bool:
        """
        Register a peer gateway in the mesh.

        Args:
            alias: Gateway alias (e.g., "vm2-gateway")
            public_url: Gateway's public URL (e.g., "https://vm2.api.agentic.local")
            description: Human-readable description
            tags: List of tags for categorization

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Registering peer gateway: {alias} ({public_url})")

        # Build capabilities list
        capabilities = []
        if description:
            capabilities.append(f"description:{description}")
        if tags:
            capabilities.extend([f"tag:{tag}" for tag in tags])

        payload = {
            "alias": alias,
            "public_url": public_url,
            "capabilities": capabilities
        }

        # Get auth token
        token = await self.get_auth_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                response = await client.post(
                    f"{self.registry_url}/v1/gateways",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                logger.info(f"Peer '{alias}' registered successfully")
                return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Registration failed: {e.response.status_code} {e.response.text}")
            return False

        except Exception as e:
            logger.error(f"Registration error: {e}")
            return False

    async def list_peers(self) -> List[dict]:
        """
        List all registered gateway peers.

        Returns:
            List of gateway dictionaries
        """
        token = await self.get_auth_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                response = await client.get(
                    f"{self.registry_url}/v1/gateways/",
                    headers=headers
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Failed to list peers: {e}")
            return []

    async def test_connection(self, alias: str) -> bool:
        """
        Test connectivity to a registered peer gateway.

        Args:
            alias: Gateway alias to test

        Returns:
            True if connection succeeds, False otherwise
        """
        logger.info(f"Testing connection to {alias}")

        try:
            # Get gateway info from registry
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                response = await client.get(f"{self.registry_url}/v1/gateways/{alias}")
                response.raise_for_status()
                gateway = response.json()

            peer_url = gateway.get("public_url", gateway.get("base_url"))

            # Test health endpoint
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                response = await client.get(f"{peer_url.rstrip('/v1')}/health")
                response.raise_for_status()
                logger.info(f"Connection to {alias} successful")
                return True

        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
