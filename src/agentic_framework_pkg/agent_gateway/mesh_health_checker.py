"""
This module implements the MeshHealthChecker, a background service responsible
for monitoring the health of all gateways in the mesh and ensuring this gateway's
own registration is up-to-date.

Architectural Role:
-   **Resilience:** The health checker provides resilience to the gateway mesh.
    If this gateway's registration is lost from the registry (e.g., due to a
    registry restart), the health checker will detect this and automatically
    re-register the gateway.
-   **Monitoring:** It periodically probes the `/health` endpoint of all registered
    gateways. This allows for a centralized view of the mesh's overall health,
    which is exposed through the Management UI.
-   **Decentralized Probing:** Each gateway runs its own health checker, creating a
    decentralized monitoring system where each node is responsible for verifying
    the state of the network.
"""
import asyncio
import httpx
import os
from ..logger_config import get_logger
from .registration import register_gateway_with_registry

logger = get_logger(__name__)

class MeshHealthChecker:
    """
    A background service that periodically checks the health of all gateways
    in the mesh and performs self-healing registration.
    """
    def __init__(self, check_interval: int = 60):
        """
        Initializes the MeshHealthChecker.

        Args:
            check_interval: The interval in seconds between health checks.
        """
        self.check_interval = check_interval
        self._task = None
        self.registry_url = os.getenv("GATEWAY_REGISTRY_URL", "http://gateway_registry:8086")
        self.alias = os.getenv("AGENT_GATEWAY_ALIAS")

    async def start(self):
        """Starts the background health checking task."""
        if self._task is None:
            self._task = asyncio.create_task(self._main_loop())
            logger.info(f"Gateway Mesh Health Checker started. Will check every {self.check_interval} seconds.")

    async def stop(self):
        """Stops the background health checking task."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Gateway Mesh Health Checker stopped.")

    async def _main_loop(self):
        """
        The main loop that periodically checks gateway health and performs
        self-registration if needed.
        """
        await asyncio.sleep(5) # Initial delay to allow network to stabilize
        while True:
            try:
                logger.info("Running gateway mesh health checks...")
                
                # --- Self-Healing Registration Check ---
                gateways = await self._fetch_registered_gateways()
                
                if gateways is None:
                    # This indicates a network error. Log it and wait for the next cycle.
                    # Do not attempt to re-register on a network failure.
                    logger.warning("Could not verify gateway registration due to a registry connection issue. Will retry on the next cycle.")
                elif self.alias and not any(g.get("alias") == self.alias for g in gateways):
                    # If we successfully fetched the list and we are not in it, re-register.
                    logger.warning(f"Gateway '{self.alias}' not found in registry. Attempting self-registration...")
                    try:
                        await register_gateway_with_registry()
                        # Re-fetch gateways after attempting registration to have the latest list for health probing
                        gateways = await self._fetch_registered_gateways()
                        if gateways is None: # If fetch fails again, skip probing for this cycle
                            continue
                    except Exception as e:
                        logger.error(f"Self-registration attempt failed during health check: {e}", exc_info=True)
                else:
                    logger.info(f"Gateway '{self.alias}' is correctly registered.")

                # --- Health Probing of Other Gateways ---
                if gateways: # Only probe if we have a list of gateways
                    async with httpx.AsyncClient(timeout=10) as tls_client, \
                               httpx.AsyncClient(timeout=10, verify=False) as insecure_client:
                        tasks = [
                            self._check_and_update_gateway(tls_client, insecure_client, gw)
                            for gw in gateways
                        ]
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        for i, result in enumerate(results):
                            if isinstance(result, Exception):
                                logger.warning(f"Error checking gateway '{gateways[i].get('alias')}': {result}")

            except Exception as e:
                logger.error(f"Error in health check loop: {e}", exc_info=True)
            
            await asyncio.sleep(self.check_interval)

    async def _fetch_registered_gateways(self) -> list | None:
        """
        Fetches the list of registered gateways from the registry service.

        Returns:
            A list of gateways on success, or None on failure.
        """
        headers = {}
        # If registry auth is enabled, we need to include our S2S token.
        if os.getenv("REGISTRY_AUTH_ENABLED", "true").lower() == "true":
            from .registration import get_s2s_token
            token = await get_s2s_token()
            if not token:
                logger.warning("Health checker could not obtain S2S token to communicate with registry. Will retry on next cycle.")
                return None
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.registry_url}/v1/gateways/", headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.RequestError as e:
            logger.warning(f"Failed to fetch registered gateways from registry (network error): {e}")
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to fetch registered gateways from registry (status error): {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching gateways: {e}", exc_info=True)
            return None

    async def _check_and_update_gateway(
        self,
        tls_client: httpx.AsyncClient,
        insecure_client: httpx.AsyncClient,
        gateway: dict,
    ):
        """
        Checks a single gateway's health using a two-phase TLS probe strategy
        and posts the status back to the registry.

        Phase 1: Probe with full TLS verification.
          - Success → Healthy (valid cert, host reachable)
        Phase 2 (on TLS failure): Retry without TLS verification.
          - Success → Healthy (TLS Warning) (host reachable, cert invalid/self-signed)
          - Failure → Unhealthy (host unreachable)

        This provides a comprehensive view of both certificate validity and
        host availability for cross-cloud gateway meshes.

        Args:
            tls_client: httpx.AsyncClient with default TLS verification.
            insecure_client: httpx.AsyncClient with verify=False.
            gateway: A dictionary representing the gateway to check.
        """
        alias = gateway.get('alias')
        health_status = "Unhealthy"
        error_details = "Unknown"
        tls_valid = None

        # Prefer internal URL for local checks, fall back to public
        probe_url = gateway.get('internal_url') or gateway.get('public_url')
        if not probe_url:
            logger.warning(f"Gateway '{alias}' has no probe URL; cannot perform health check.")
            error_details = "No URL configured for probing."
        else:
            health_url = f"{probe_url.rstrip('/')}/health"
            is_https = probe_url.lower().startswith("https://")

            # Phase 1: Probe with full TLS verification
            phase1_ok = False
            phase1_error = None
            try:
                response = await tls_client.get(health_url)
                response.raise_for_status()
                if response.json().get("status") == "ok":
                    health_status = "Healthy"
                    error_details = None
                    tls_valid = True if is_https else None
                    phase1_ok = True
                else:
                    error_details = "Health endpoint returned non-ok status."
                    phase1_ok = True  # Host reachable, just bad response
            except Exception as e:
                phase1_error = str(e)
                logger.debug(f"Phase 1 (TLS verified) probe for '{alias}' failed: {phase1_error}")

            # Phase 2: If Phase 1 failed, retry without TLS verification
            # to distinguish cert issues from host unreachable
            if not phase1_ok:
                try:
                    response = await insecure_client.get(health_url)
                    response.raise_for_status()
                    if response.json().get("status") == "ok":
                        health_status = "Healthy"
                        tls_valid = False
                        error_details = f"TLS verification failed: {phase1_error}"
                        logger.info(
                            f"Gateway '{alias}' is reachable but has TLS issues: {phase1_error}"
                        )
                    else:
                        error_details = "Health endpoint returned non-ok status (insecure probe)."
                except Exception as e2:
                    error_details = str(e2)
                    logger.warning(
                        f"Health check for gateway '{alias}' at {probe_url} failed "
                        f"(both TLS and insecure probes): {e2}"
                    )

        # Build update payload with TLS status
        update_payload = {"status": health_status, "details": error_details}
        if tls_valid is not None:
            update_payload["tls_valid"] = tls_valid

        # Update the registry with the result (requires S2S auth)
        try:
            update_url = f"{self.registry_url}/v1/gateways/{alias}/health"
            headers = {}
            if os.getenv("REGISTRY_AUTH_ENABLED", "true").lower() == "true":
                from .registration import get_s2s_token
                token = await get_s2s_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                else:
                    logger.warning(f"Could not obtain S2S token for health update of '{alias}'")
            await insecure_client.post(update_url, json=update_payload, headers=headers)
        except Exception as e:
            logger.error(f"Failed to update health status for gateway '{alias}' in registry: {e}")

# Global instance
health_checker = MeshHealthChecker()
