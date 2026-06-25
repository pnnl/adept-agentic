"""Configuration for AWS MCP Server Manager via Pydantic Settings."""

from pydantic import Field
from pydantic_settings import BaseSettings


class AWSMCPManagerConfig(BaseSettings):
    """Configuration loaded from AWS_MCP_* environment variables."""

    model_config = {"env_prefix": "AWS_MCP_"}

    # IAM user credentials (STS calls only — never exposed to subprocesses)
    aws_access_key_id: str = Field(default="", description="IAM user access key for STS AssumeRole")
    aws_secret_access_key: str = Field(default="", description="IAM user secret key for STS AssumeRole")
    aws_region: str = Field(default="us-east-1", description="Default AWS region")

    # STS AssumeRole configuration
    sts_role_arn: str = Field(default="", description="Role ARN to assume for subprocess credentials")
    sts_session_duration: int = Field(default=3600, description="Temp credential TTL in seconds")
    sts_external_id: str = Field(default="", description="Optional ExternalId for cross-account assume role")
    sts_refresh_buffer: int = Field(default=300, description="Refresh credentials N seconds before expiry")

    # Meta-server configuration
    port: int = Field(default=8003, description="Meta-server listen port")
    proxy_port: int = Field(default=9830, description="Nginx proxy port")
    subprocess_timeout: int = Field(default=120, description="Max seconds per tool call")
    max_loaded_servers: int = Field(default=20, description="Circuit breaker: max concurrent servers")

    @property
    def has_iam_credentials(self) -> bool:
        return bool(self.aws_access_key_id and self.aws_secret_access_key)

    @property
    def has_sts_config(self) -> bool:
        return bool(self.sts_role_arn)
