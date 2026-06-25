"""REST API transport for Tahoma (slurmrestd) cluster operations.

Implements SlurmTransport using httpx + JWT authentication against
slurmrestd. Reuses the shared SlurmClient and JWTTokenManager from
the parent package.

This transport is used when:
  - TAHOMA_TRANSPORT_MODE=rest (forced REST)
  - TAHOMA_TRANSPORT_MODE=auto AND slurmrestd is reachable
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from ..client import JWTTokenManager, SlurmClient, SlurmError
from ..transport import ClusterInfo, JobResult, SlurmTransport

logger = logging.getLogger(__name__)


class TahomaRESTConfig:
    """Adapter to make TahomaConfig fields accessible with the interface SlurmClient expects."""

    def __init__(self, config):
        self._config = config

    @property
    def api_url(self) -> str:
        return self._config.rest_api_url

    @property
    def timeout(self) -> int:
        return self._config.rest_timeout

    @property
    def verify_ssl(self) -> bool:
        return False

    @property
    def api_version(self) -> str:
        return self._config.rest_api_version


class TahomaRESTTransport(SlurmTransport):
    """REST API transport for Tahoma cluster via slurmrestd.

    Uses httpx AsyncClient with JWT HS256 auth (same pattern as
    the local Docker slurmrestd). Lazy-connects on first operation.
    """

    def __init__(self, config):
        self._config = config
        self._rest_config = TahomaRESTConfig(config)
        self._token_manager = JWTTokenManager(
            jwt_key=config.jwt_key,
            service_jwt=config.service_jwt,
            service_user=config.username,
        )
        self._client: Optional[SlurmClient] = None
        self._active_client: Optional[SlurmClient] = None

    async def _get_client(self) -> SlurmClient:
        """Get or create the async HTTP client."""
        if self._active_client is None:
            client = SlurmClient(self._rest_config, self._token_manager)
            self._active_client = await client.__aenter__()
        return self._active_client

    async def submit_job(
        self,
        script: str,
        job_name: str,
        partition: Optional[str] = None,
        account: Optional[str] = None,
        nodes: int = 1,
        ntasks: int = 1,
        cpus_per_task: int = 1,
        memory: Optional[str] = None,
        time_limit: str = "01:00:00",
        working_directory: Optional[str] = None,
        array: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> JobResult:
        """Submit a job via slurmrestd POST /slurm/{version}/job/submit.

        Note: session_id is accepted for ABC compliance but workspace
        persistence is not supported via slurmrestd — the REST API handles
        script content inline. Use SSH transport for workspace features.
        """
        effective_partition = partition or self._config.default_partition or None
        effective_account = account or self._config.default_account or None
        effective_workdir = working_directory or self._config.resolved_working_directory

        job_spec: Dict[str, Any] = {
            "name": job_name,
            "nodes": str(nodes),
            "tasks": str(ntasks),
            "cpus_per_task": str(cpus_per_task),
            "time_limit": {"minutes": _parse_time_limit_minutes(time_limit)},
            "current_working_directory": effective_workdir,
            "environment": ["PATH=/usr/bin:/bin:/usr/sbin:/sbin"],
        }

        if effective_partition:
            job_spec["partition"] = effective_partition
        if effective_account:
            job_spec["account"] = effective_account
        if memory:
            job_spec["memory_per_node"] = {"number": _parse_memory_mb(memory)}
        if array:
            job_spec["array"] = array

        payload = {"script": script, "job": job_spec}

        try:
            client = await self._get_client()
            version = self._config.rest_api_version
            response = await client.request(
                "POST",
                f"/slurm/{version}/job/submit",
                json=payload,
            )
            job_id = str(response.get("job_id", ""))
            if not job_id:
                return JobResult(
                    success=False,
                    error="No job_id in REST response",
                    raw_data=response,
                )
            return JobResult(
                success=True,
                job_id=job_id,
                output=f"Submitted batch job {job_id}",
                raw_data=response,
            )
        except SlurmError as e:
            return JobResult(success=False, error=str(e))
        except Exception as e:
            return JobResult(success=False, error=f"REST submit failed: {e}")

    async def get_job_status(self, job_id: str) -> JobResult:
        """Query job status via GET /slurm/{version}/job/{job_id}."""
        try:
            client = await self._get_client()
            version = self._config.rest_api_version
            response = await client.request(
                "GET", f"/slurm/{version}/job/{job_id}"
            )
            jobs = response.get("jobs", [])
            if jobs:
                return JobResult(
                    success=True,
                    job_id=job_id,
                    output=str(jobs[0].get("job_state", "UNKNOWN")),
                    raw_data=jobs[0],
                )
            return JobResult(
                success=False,
                job_id=job_id,
                error=f"Job {job_id} not found",
            )
        except SlurmError as e:
            return JobResult(success=False, job_id=job_id, error=str(e))
        except Exception as e:
            return JobResult(
                success=False, job_id=job_id, error=f"REST query failed: {e}"
            )

    async def cancel_job(self, job_id: str) -> JobResult:
        """Cancel a job via DELETE /slurm/{version}/job/{job_id}."""
        try:
            client = await self._get_client()
            version = self._config.rest_api_version
            await client.request(
                "DELETE", f"/slurm/{version}/job/{job_id}"
            )
            return JobResult(success=True, job_id=job_id, output="Cancelled")
        except SlurmError as e:
            return JobResult(success=False, job_id=job_id, error=str(e))
        except Exception as e:
            return JobResult(
                success=False, job_id=job_id, error=f"REST cancel failed: {e}"
            )

    async def list_jobs(
        self, user: Optional[str] = None, state: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List jobs via GET /slurm/{version}/jobs."""
        try:
            client = await self._get_client()
            version = self._config.rest_api_version
            response = await client.request("GET", f"/slurm/{version}/jobs")
            jobs = response.get("jobs", [])

            if user:
                jobs = [j for j in jobs if j.get("user_name") == user]
            if state:
                jobs = [
                    j
                    for j in jobs
                    if _match_job_state(j.get("job_state"), state)
                ]
            return jobs
        except (SlurmError, Exception) as e:
            logger.warning("REST list_jobs failed: %s", e)
            return []

    async def get_cluster_info(self) -> ClusterInfo:
        """Get cluster info via GET /slurm/{version}/nodes + /partitions."""
        nodes: List[Dict[str, Any]] = []
        partitions: List[Dict[str, Any]] = []
        jobs: List[Dict[str, Any]] = []

        try:
            client = await self._get_client()
            version = self._config.rest_api_version

            node_resp = await client.request(
                "GET", f"/slurm/{version}/nodes"
            )
            nodes = node_resp.get("nodes", [])

            part_resp = await client.request(
                "GET", f"/slurm/{version}/partitions"
            )
            partitions = part_resp.get("partitions", [])

            job_resp = await client.request(
                "GET", f"/slurm/{version}/jobs"
            )
            jobs = job_resp.get("jobs", [])
        except (SlurmError, Exception) as e:
            logger.warning("REST cluster_info partially failed: %s", e)

        return ClusterInfo(nodes=nodes, jobs=jobs, partitions=partitions)

    async def ping(self) -> bool:
        """Ping slurmrestd via GET /slurm/{version}/ping."""
        try:
            client = await self._get_client()
            version = self._config.rest_api_version
            await client.request("GET", f"/slurm/{version}/ping")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._active_client:
            await self._active_client.__aexit__(None, None, None)
            self._active_client = None


def _parse_time_limit_minutes(time_limit: str) -> int:
    """Convert HH:MM:SS to minutes."""
    parts = time_limit.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 60


def _parse_memory_mb(memory: str) -> int:
    """Convert memory string (e.g., '64G', '4096M') to megabytes."""
    memory = memory.strip().upper()
    if memory.endswith("G"):
        return int(float(memory[:-1]) * 1024)
    elif memory.endswith("M"):
        return int(float(memory[:-1]))
    elif memory.endswith("T"):
        return int(float(memory[:-1]) * 1024 * 1024)
    return int(memory)


def _match_job_state(job_state, filter_state: str) -> bool:
    """Check if a job state matches the filter (handles list or string)."""
    if isinstance(job_state, list):
        return filter_state.upper() in [s.upper() for s in job_state]
    if isinstance(job_state, str):
        return job_state.upper() == filter_state.upper()
    return False
