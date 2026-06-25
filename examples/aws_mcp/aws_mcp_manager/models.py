"""Data models for AWS MCP Server Manager."""

import enum
import time
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ServerState(str, enum.Enum):
    """Lifecycle state of a managed AWS MCP server subprocess."""

    stopped = "stopped"
    starting = "starting"
    running = "running"
    error = "error"


class STSCredentials(BaseModel):
    """Temporary AWS credentials from STS AssumeRole."""

    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: float = Field(description="Unix timestamp when credentials expire")

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expiration

    def expires_within(self, seconds: int) -> bool:
        """Return True if credentials expire within the given number of seconds."""
        return time.time() >= (self.expiration - seconds)

    def as_env(self) -> dict[str, str]:
        """Return credentials as environment variables for subprocess injection."""
        return {
            "AWS_ACCESS_KEY_ID": self.access_key_id,
            "AWS_SECRET_ACCESS_KEY": self.secret_access_key,
            "AWS_SESSION_TOKEN": self.session_token,
        }


class CatalogEntry(BaseModel):
    """A single AWS MCP server in the static catalog."""

    name: str = Field(description="Server name, e.g. 's3-tables-mcp-server'")
    command: str = Field(description="Entry point command, e.g. 'awslabs.s3-tables-mcp-server'")
    package: str = Field(description="PyPI package name, e.g. 'awslabs.s3-tables-mcp-server'")
    description: str = Field(default="", description="Human-readable description")
    tool_prefix: str = Field(description="Namespace prefix for tools, e.g. 's3_tables'")
    install_cmd: str = Field(
        default="",
        description="pip/uv install command for on-demand installation",
    )


class ToolInfo(BaseModel):
    """A tool exposed by a loaded AWS MCP server."""

    name: str = Field(description="Original tool name from the MCP server")
    qualified_name: str = Field(description="Namespaced name: prefix.tool_name")
    description: str = Field(default="")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    server_name: str = Field(description="Name of the server that provides this tool")


class ServerEntry(BaseModel):
    """Runtime state of a managed AWS MCP server."""

    catalog: CatalogEntry
    state: ServerState = ServerState.stopped
    tools: list[ToolInfo] = Field(default_factory=list)
    loaded_at: Optional[datetime] = None
    error: Optional[str] = None
    pid: Optional[int] = None
