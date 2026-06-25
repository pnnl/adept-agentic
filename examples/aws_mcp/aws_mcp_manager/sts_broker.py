"""STS credential broker — AssumeRole with caching and automatic refresh."""

import asyncio
from functools import partial
from typing import Optional

import boto3
from loguru import logger

from .config import AWSMCPManagerConfig
from .models import STSCredentials


class STSBroker:
    """Brokers STS temporary credentials for AWS MCP server subprocesses.

    Holds IAM user credentials privately (never exposed to subprocesses).
    Caches assumed-role credentials and refreshes them before expiry.
    """

    def __init__(self, config: AWSMCPManagerConfig) -> None:
        self._config = config
        self._cache: dict[str, STSCredentials] = {}
        self._lock = asyncio.Lock()

    def _create_sts_client(self):
        """Create a boto3 STS client using the IAM user's long-lived credentials."""
        kwargs = {"service_name": "sts", "region_name": self._config.aws_region}
        if self._config.has_iam_credentials:
            kwargs["aws_access_key_id"] = self._config.aws_access_key_id
            kwargs["aws_secret_access_key"] = self._config.aws_secret_access_key
        return boto3.client(**kwargs)

    async def get_credentials(self, session_name: str) -> STSCredentials:
        """Get cached STS credentials, refreshing if within the refresh buffer.

        Args:
            session_name: Included in the STS session name for CloudTrail
                traceability. Typically the server name, e.g. 'adept-s3-tables'.
        """
        async with self._lock:
            cached = self._cache.get(session_name)
            if cached and not cached.expires_within(self._config.sts_refresh_buffer):
                return cached

            logger.info("Assuming role for session '{}'", session_name)
            creds = await self._assume_role(session_name)
            self._cache[session_name] = creds
            return creds

    async def _assume_role(self, session_name: str) -> STSCredentials:
        """Call STS AssumeRole in an executor thread (non-blocking)."""
        loop = asyncio.get_running_loop()
        sts = self._create_sts_client()

        kwargs = {
            "RoleArn": self._config.sts_role_arn,
            "RoleSessionName": f"adept-{session_name}"[:64],
            "DurationSeconds": self._config.sts_session_duration,
        }
        if self._config.sts_external_id:
            kwargs["ExternalId"] = self._config.sts_external_id

        response = await loop.run_in_executor(None, partial(sts.assume_role, **kwargs))
        creds = response["Credentials"]

        return STSCredentials(
            access_key_id=creds["AccessKeyId"],
            secret_access_key=creds["SecretAccessKey"],
            session_token=creds["SessionToken"],
            expiration=creds["Expiration"].timestamp(),
        )

    def needs_refresh(self, session_name: str, buffer_seconds: int) -> bool:
        """Check whether cached credentials for *session_name* are about to expire.

        Returns ``True`` if credentials exist **and** will expire within
        *buffer_seconds*, meaning the caller should refresh before the next
        tool call.  Returns ``False`` if no cached credentials exist (nothing
        to refresh) or if the credentials are still fresh.
        """
        cached = self._cache.get(session_name)
        if cached is None:
            return False
        return cached.expires_within(buffer_seconds)

    def invalidate(self, session_name: str) -> None:
        """Remove cached credentials for a session."""
        self._cache.pop(session_name, None)

    def invalidate_all(self) -> None:
        """Clear all cached credentials."""
        self._cache.clear()
