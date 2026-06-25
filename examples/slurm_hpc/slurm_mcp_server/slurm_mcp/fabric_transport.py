"""Fabric-based SSH transport for any Slurm cluster.

Concrete implementation of SlurmTransport using Fabric (paramiko).
Works for any cluster that has SSH + Slurm CLI access.
Accepts a config object with host, ssh_port, username, ssh_key_path, ssh_timeout.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Protocol

from fabric import Connection
from invoke.exceptions import CommandTimedOut, UnexpectedExit

from .slurm_parsers import (
    build_sbatch_options,
    parse_sacct_json,
    parse_sbatch_output,
    parse_scancel_output,
    parse_sinfo_json,
    parse_squeue_json,
)
from .transport import ClusterInfo, JobResult, SlurmTransport

logger = logging.getLogger(__name__)


class SSHConfig(Protocol):
    """Protocol defining what a cluster config must provide for SSH transport."""

    host: str
    ssh_port: int
    username: str
    ssh_timeout: int
    default_partition: str
    default_account: str

    @property
    def resolved_ssh_key_path(self): ...

    @property
    def resolved_working_directory(self) -> str: ...


class FabricSSHTransport(SlurmTransport):
    """Fabric-based SSH transport for remote Slurm clusters.

    Uses Fabric's Connection with key-based auth. The private key path
    is read from the cluster config (managed by clusters.yaml lifecycle).
    Key material never leaves this module — only metadata is exposed.
    """

    def __init__(self, config: SSHConfig):
        self._config = config
        self._conn: Optional[Connection] = None

    def _get_connection(self) -> Connection:
        if self._conn is None or not self._conn.is_connected:
            import paramiko

            connect_kwargs: Dict[str, Any] = {
                "look_for_keys": False,
                "allow_agent": False,
            }
            key_path = self._config.resolved_ssh_key_path
            if key_path.exists():
                connect_kwargs["key_filename"] = str(key_path)
                logger.debug("SSH key: %s (exists=True)", key_path)
            else:
                logger.warning("SSH key not found: %s", key_path)

            password = getattr(self._config, "password", "")
            if password:
                connect_kwargs["password"] = password

            logger.debug(
                "Connecting: %s@%s:%d (timeout=%ds)",
                self._config.username, self._config.host,
                self._config.ssh_port, self._config.ssh_timeout,
            )
            self._conn = Connection(
                host=self._config.host,
                port=self._config.ssh_port,
                user=self._config.username,
                connect_kwargs=connect_kwargs,
                connect_timeout=self._config.ssh_timeout,
            )
            self._conn.client.set_missing_host_key_policy(
                paramiko.AutoAddPolicy()
            )
            logger.info("SSH connection established: %s@%s", self._config.username, self._config.host)
        return self._conn

    def _run(self, cmd: str, timeout: Optional[int] = None, warn: bool = False):
        """Run a remote command via Fabric."""
        conn = self._get_connection()
        effective_timeout = timeout or self._config.ssh_timeout
        logger.debug("SSH exec: %s (timeout=%ds warn=%s)", cmd[:120], effective_timeout, warn)
        result = conn.run(
            cmd, hide=True, warn=warn, timeout=effective_timeout, in_stream=False
        )
        logger.debug(
            "SSH result: ok=%s exit=%d stdout_len=%d stderr_len=%d",
            result.ok, result.return_code, len(result.stdout), len(result.stderr),
        )
        return result

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
        output_dir: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> JobResult:
        effective_partition = partition or self._config.default_partition or None
        effective_account = account or self._config.default_account or None

        if session_id:
            home_result = self._run("readlink -f $HOME || echo $HOME", warn=True)
            home_dir = home_result.stdout.strip() or "/tmp"
            logger.info(
                "Resolved remote HOME: %r (raw stdout=%r, session_id=%s)",
                home_dir, home_result.stdout, session_id,
            )
            workspace_dir = f"{home_dir}/adept-workspace/{session_id}"
            self._run(f"mkdir -p {workspace_dir}", warn=True)
            effective_workdir = working_directory or workspace_dir
            if output_dir:
                self._run(f"mkdir -p {output_dir}", warn=True)
                output_path = f"{output_dir}/slurm-%j.out"
                error_path = f"{output_dir}/slurm-%j.err"
            else:
                output_path = f"{workspace_dir}/slurm-%j.out"
                error_path = f"{workspace_dir}/slurm-%j.err"
            logger.info(
                "Workspace paths: workdir=%s output=%s error=%s",
                effective_workdir, output_path, error_path,
            )
        elif output_dir:
            workspace_dir = None
            self._run(f"mkdir -p {output_dir}", warn=True)
            effective_workdir = working_directory or output_dir
            output_path = f"{output_dir}/slurm-%j.out"
            error_path = f"{output_dir}/slurm-%j.err"
            logger.info(
                "Output dir override: workdir=%s output=%s", effective_workdir, output_path,
            )
        else:
            workspace_dir = None
            effective_workdir = working_directory or self._config.resolved_working_directory
            output_path = None
            error_path = None

        sbatch_opts = build_sbatch_options(
            job_name=job_name,
            partition=effective_partition,
            account=effective_account,
            nodes=nodes,
            ntasks=ntasks,
            cpus_per_task=cpus_per_task,
            memory=memory,
            time_limit=time_limit,
            working_directory=effective_workdir,
            array=array,
            output_path=output_path,
            error_path=error_path,
        )

        if workspace_dir:
            script_filename = f"{job_name}_{uuid.uuid4().hex[:8]}.sh"
            remote_script_path = f"{workspace_dir}/{script_filename}"
            persist_script = True
        else:
            remote_script_path = f"/tmp/adept_job_{uuid.uuid4().hex[:12]}.sh"
            persist_script = False

        try:
            write_cmd = f"cat > {remote_script_path} << 'ADEPT_EOF'\n{script}\nADEPT_EOF"
            self._run(write_cmd, timeout=timeout_seconds)

            sbatch_cmd = f"sbatch {sbatch_opts} {remote_script_path}"
            result = self._run(sbatch_cmd, warn=True, timeout=timeout_seconds)

            if result.failed:
                return JobResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr,
                )

            job_id = parse_sbatch_output(result.stdout)
            logger.info(
                "Job %s submitted from %s (persist=%s)",
                job_id, remote_script_path, persist_script,
            )
            return JobResult(success=True, job_id=job_id, output=result.stdout)

        except (CommandTimedOut, UnexpectedExit) as e:
            return JobResult(success=False, error=str(e))
        except ValueError as e:
            return JobResult(success=False, error=str(e))
        finally:
            if not persist_script:
                try:
                    self._run(f"rm -f {remote_script_path}", warn=True)
                except Exception:
                    pass

    async def get_job_status(self, job_id: str) -> JobResult:
        try:
            result = self._run(f"squeue --json -j {job_id}", warn=True)
            if result.ok:
                jobs = parse_squeue_json(result.stdout)
                if jobs:
                    return JobResult(
                        success=True,
                        job_id=job_id,
                        output=result.stdout,
                        raw_data=jobs[0],
                    )

            result = self._run(f"sacct --json -j {job_id}", warn=True)
            if result.ok:
                jobs = parse_sacct_json(result.stdout)
                if jobs:
                    return JobResult(
                        success=True,
                        job_id=job_id,
                        output=result.stdout,
                        raw_data=jobs[0],
                    )

        except (CommandTimedOut, UnexpectedExit) as e:
            return JobResult(success=False, job_id=job_id, error=str(e))

        return JobResult(
            success=False,
            job_id=job_id,
            error=f"Job {job_id} not found in squeue or sacct",
        )

    async def cancel_job(self, job_id: str) -> JobResult:
        try:
            result = self._run(f"scancel {job_id}", warn=True)
            success = parse_scancel_output(result.stdout, result.stderr)
            return JobResult(
                success=success,
                job_id=job_id,
                output=result.stdout,
                error=result.stderr,
            )
        except (CommandTimedOut, UnexpectedExit) as e:
            return JobResult(success=False, job_id=job_id, error=str(e))

    async def list_jobs(
        self, user: Optional[str] = None, state: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        cmd_parts = ["squeue", "--json"]
        if user:
            cmd_parts.append(f"--user={user}")
        if state:
            cmd_parts.append(f"--states={state}")
        try:
            result = self._run(" ".join(cmd_parts), warn=True)
            if result.failed:
                logger.warning("squeue failed: %s", result.stderr)
                return []
            return parse_squeue_json(result.stdout)
        except (CommandTimedOut, UnexpectedExit) as e:
            logger.warning("squeue error: %s", e)
            return []

    async def get_cluster_info(self) -> ClusterInfo:
        nodes: List[Dict[str, Any]] = []
        partitions: List[Dict[str, Any]] = []
        jobs: List[Dict[str, Any]] = []

        try:
            sinfo_result = self._run("sinfo --json", warn=True)
            if sinfo_result.ok:
                data = parse_sinfo_json(sinfo_result.stdout)
                nodes = data.get("nodes", [])
                partitions = data.get("sinfo", [])
        except (CommandTimedOut, UnexpectedExit):
            pass

        try:
            squeue_result = self._run("squeue --json", warn=True)
            if squeue_result.ok:
                jobs = parse_squeue_json(squeue_result.stdout)
        except (CommandTimedOut, UnexpectedExit):
            pass

        return ClusterInfo(nodes=nodes, jobs=jobs, partitions=partitions)

    async def ping(self) -> bool:
        try:
            result = self._run("scontrol ping", timeout=10, warn=True)
            return result.ok
        except Exception as e:
            logger.debug("Ping failed: %s", e)
            return False

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
