"""Server registry — in-memory registry for loaded AWS MCP server subprocesses."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from .config import AWSMCPManagerConfig
from .models import CatalogEntry, ServerEntry, ServerState, ToolInfo
from .sts_broker import STSBroker
from .subprocess_bridge import StdioSubprocess


class ServerRegistry:
    """Manages the lifecycle of AWS MCP server subprocesses.

    Maintains an in-memory registry of loaded servers, handles STS credential
    refresh, and routes tool calls to the correct subprocess.
    """

    def __init__(
        self,
        config: AWSMCPManagerConfig,
        sts_broker: STSBroker,
    ) -> None:
        self._config = config
        self._sts_broker = sts_broker
        self._entries: dict[str, ServerEntry] = {}
        self._subprocesses: dict[str, StdioSubprocess] = {}
        self._lock = asyncio.Lock()

    @property
    def max_loaded_servers(self) -> int:
        return self._config.max_loaded_servers

    @property
    def loaded_count(self) -> int:
        return sum(
            1
            for e in self._entries.values()
            if e.state in (ServerState.running, ServerState.starting)
        )

    def get_entry(self, name: str) -> Optional[ServerEntry]:
        return self._entries.get(name)

    async def load_server(self, catalog_entry: CatalogEntry) -> ServerEntry:
        """Load an AWS MCP server: get STS creds, spawn subprocess, discover tools.

        Raises:
            RuntimeError: If the circuit breaker limit is reached.
            RuntimeError: If the server fails to start.
        """
        async with self._lock:
            # Check if already loaded
            existing = self._entries.get(catalog_entry.name)
            if existing and existing.state == ServerState.running:
                logger.info("{} is already running", catalog_entry.name)
                return existing

            # Circuit breaker
            if self.loaded_count >= self._config.max_loaded_servers:
                raise RuntimeError(
                    f"Circuit breaker: {self.loaded_count} servers loaded "
                    f"(max {self._config.max_loaded_servers}). "
                    f"Unload a server first."
                )

            # Create entry in starting state
            entry = ServerEntry(catalog=catalog_entry, state=ServerState.starting)
            self._entries[catalog_entry.name] = entry

        # Get STS credentials (outside lock to avoid blocking)
        try:
            env = await self._get_subprocess_env(catalog_entry.name)
        except Exception as exc:
            async with self._lock:
                entry.state = ServerState.error
                entry.error = f"STS credential error: {exc}"
            raise RuntimeError(entry.error) from exc

        # Spawn subprocess
        subprocess = StdioSubprocess(catalog_entry)
        try:
            tools = await subprocess.start(env)
        except Exception as exc:
            async with self._lock:
                entry.state = ServerState.error
                entry.error = f"Subprocess start error: {exc}"
            raise RuntimeError(entry.error) from exc

        # Update registry
        async with self._lock:
            entry.state = ServerState.running
            entry.tools = tools
            entry.loaded_at = datetime.now(timezone.utc)
            entry.pid = subprocess.pid
            entry.error = None
            self._subprocesses[catalog_entry.name] = subprocess

        logger.info(
            "Loaded {} with {} tools",
            catalog_entry.name,
            len(tools),
        )
        return entry

    async def unload_server(self, name: str) -> None:
        """Stop a server subprocess and remove it from the registry."""
        async with self._lock:
            subprocess = self._subprocesses.pop(name, None)
            entry = self._entries.get(name)

        if subprocess:
            await subprocess.stop()

        if entry:
            async with self._lock:
                entry.state = ServerState.stopped
                entry.tools = []
                entry.pid = None
                entry.error = None

        self._sts_broker.invalidate(name)
        logger.info("Unloaded {}", name)

    async def call_tool(
        self, qualified_name: str, arguments: dict[str, Any]
    ) -> Any:
        """Route a tool call by qualified name (prefix.tool_name) to the right subprocess.

        Before calling, checks if STS credentials need refresh and transparently
        restarts the subprocess if so.
        """
        server_name, original_tool = self._resolve_tool(qualified_name)

        async with self._lock:
            subprocess = self._subprocesses.get(server_name)
            entry = self._entries.get(server_name)

        if not subprocess or not entry or entry.state != ServerState.running:
            raise RuntimeError(
                f"Server '{server_name}' is not running. "
                f"Load it first with load_aws_server('{server_name}')."
            )

        # Check STS credential freshness — restart subprocess if needed
        if self._config.has_sts_config:
            session_name = entry.catalog.name
            if self._sts_broker.needs_refresh(session_name, self._config.sts_refresh_buffer):
                logger.info("Refreshing credentials for {}", server_name)
                await self._restart_with_fresh_creds(server_name, subprocess, entry)

        return await subprocess.call_tool(original_tool, arguments)

    def list_all_tools(self) -> list[ToolInfo]:
        """Aggregate tools from all running servers."""
        tools = []
        for entry in self._entries.values():
            if entry.state == ServerState.running:
                tools.extend(entry.tools)
        return tools

    def _resolve_tool(self, qualified_name: str) -> tuple[str, str]:
        """Resolve prefix.tool_name → (server_name, original_tool_name)."""
        if "." not in qualified_name:
            raise ValueError(
                f"Tool name '{qualified_name}' must be qualified as 'prefix.tool_name'"
            )

        prefix, tool_name = qualified_name.split(".", 1)

        for entry in self._entries.values():
            if entry.catalog.tool_prefix == prefix and entry.state == ServerState.running:
                return entry.catalog.name, tool_name

        raise RuntimeError(
            f"No running server with tool prefix '{prefix}'. "
            f"Load the appropriate server first."
        )

    async def _get_subprocess_env(self, server_name: str) -> dict[str, str]:
        """Build environment dict with STS temp credentials and region."""
        env: dict[str, str] = {"AWS_DEFAULT_REGION": self._config.aws_region}

        if self._config.has_sts_config:
            creds = await self._sts_broker.get_credentials(server_name)
            env.update(creds.as_env())
        elif self._config.has_iam_credentials:
            # Fallback: pass IAM user creds directly (not recommended)
            env["AWS_ACCESS_KEY_ID"] = self._config.aws_access_key_id
            env["AWS_SECRET_ACCESS_KEY"] = self._config.aws_secret_access_key

        return env

    async def _restart_with_fresh_creds(
        self,
        server_name: str,
        subprocess: StdioSubprocess,
        entry: ServerEntry,
    ) -> None:
        """Restart a subprocess with refreshed STS credentials."""
        self._sts_broker.invalidate(server_name)
        env = await self._get_subprocess_env(server_name)
        await subprocess.stop()
        tools = await subprocess.start(env)

        async with self._lock:
            entry.tools = tools
            entry.loaded_at = datetime.now(timezone.utc)

    async def shutdown(self) -> None:
        """Stop all running subprocesses (for graceful shutdown)."""
        names = list(self._subprocesses.keys())
        for name in names:
            try:
                await self.unload_server(name)
            except Exception:
                logger.warning("Error unloading {} during shutdown", name)
