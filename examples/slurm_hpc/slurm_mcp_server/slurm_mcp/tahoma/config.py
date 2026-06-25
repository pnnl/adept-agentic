"""Configuration for Tahoma HPC cluster connection."""

from pathlib import Path

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class TahomaConfig(BaseSettings):
    """Tahoma HPC cluster configuration from environment variables.

    All variables use the TAHOMA_ prefix.
    Tahoma supports both SSH and REST API transports.
    """

    host: str = Field(default="tahoma.emsl.pnl.gov", description="Cluster hostname")
    ssh_port: int = Field(default=22, description="SSH port")
    username: str = Field(default="rigo160", description="Slurm account username")
    password: str = Field(
        default="",
        description="SSH password for 2FA (pubkey + password) clusters",
    )
    ssh_key_path: str = Field(
        default="",
        description="Path to SSH private key. Empty = auto-resolve from username.",
    )
    known_hosts_path: str = Field(
        default="/app/.ssh/known_hosts",
        description="Path to SSH known_hosts file",
    )

    rest_api_url: str = Field(
        default="",
        description="Tahoma slurmrestd URL (empty = SSH-only mode)",
    )
    rest_api_version: str = Field(
        default="v0.0.41", description="Slurm REST API version"
    )
    jwt_key: str = Field(
        default="", description="Base64-encoded HMAC key for REST API auth"
    )
    service_jwt: str = Field(default="", description="Static JWT for REST API auth")

    transport_mode: str = Field(
        default="auto",
        description="Primary transport: 'ssh', 'rest', or 'auto' (probe REST, fallback SSH)",
    )

    ssh_timeout: int = Field(default=30, description="SSH command timeout in seconds")
    rest_timeout: int = Field(default=30, description="REST API timeout in seconds")

    default_partition: str = Field(
        default="", description="Default partition on Tahoma"
    )
    default_account: str = Field(
        default="", description="Default account for job charging"
    )
    working_directory: str = Field(
        default="",
        description="Default working directory on Tahoma. Empty = /scratch/{username}.",
    )

    model_config = ConfigDict(
        env_prefix="TAHOMA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def resolved_ssh_key_path(self) -> Path:
        if self.ssh_key_path:
            return Path(self.ssh_key_path).expanduser()
        return Path(f"/app/.ssh/{self.username}/adept_tahoma_ed25519")

    @property
    def resolved_known_hosts_path(self) -> Path:
        return Path(self.known_hosts_path).expanduser()

    @property
    def resolved_working_directory(self) -> str:
        if self.working_directory:
            return self.working_directory
        return f"/scratch/{self.username}"


tahoma_config = TahomaConfig()
