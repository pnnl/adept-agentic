"""Transport abstraction for Slurm cluster operations.

Shared ABC used by both Deception (SSH-only) and Tahoma (SSH + REST).
Concrete implementations:
  - FabricSSHTransport (fabric-based SSH, works for any cluster)
  - RESTTransport (httpx-based, for clusters with slurmrestd)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class JobResult:
    """Unified result from Slurm operations regardless of transport."""

    success: bool
    job_id: Optional[str] = None
    output: str = ""
    error: str = ""
    raw_data: Optional[Dict[str, Any]] = None


@dataclass
class ClusterInfo:
    """Unified cluster status."""

    nodes: List[Dict[str, Any]] = field(default_factory=list)
    jobs: List[Dict[str, Any]] = field(default_factory=list)
    partitions: List[Dict[str, Any]] = field(default_factory=list)


class SlurmTransport(ABC):
    """Abstract transport for Slurm cluster operations.

    Concrete implementations:
      - FabricSSHTransport: Uses Fabric (paramiko) for SSH-based Slurm CLI access
      - RESTTransport: Uses httpx for slurmrestd HTTP API access
    """

    @abstractmethod
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
    ) -> JobResult: ...

    @abstractmethod
    async def get_job_status(self, job_id: str) -> JobResult: ...

    @abstractmethod
    async def cancel_job(self, job_id: str) -> JobResult: ...

    @abstractmethod
    async def list_jobs(
        self, user: Optional[str] = None, state: Optional[str] = None
    ) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def get_cluster_info(self) -> ClusterInfo: ...

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...
