"""stdio subprocess bridge — lifecycle management for AWS MCP server processes.

Uses the MCP SDK's stdio_client to spawn servers as subprocesses and
communicate via JSON-RPC over stdin/stdout pipes.
"""

import os
from contextlib import AsyncExitStack
from typing import Any, Optional

from loguru import logger
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .models import CatalogEntry, ToolInfo


class StdioSubprocess:
    """Wraps a single AWS MCP server running as a stdio subprocess.

    Manages the full lifecycle: spawn → initialize → discover tools → call → stop.
    """

    def __init__(self, catalog_entry: CatalogEntry) -> None:
        self.catalog = catalog_entry
        self._exit_stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        self._tools: list[ToolInfo] = []
        # NOTE: The MCP SDK's stdio_client() returns a transport (read/write
        # streams), not a subprocess handle, so the spawned process PID is not
        # accessible through the public API.  We keep the field for future use
        # if the SDK exposes it, but callers must tolerate None.
        self.pid: Optional[int] = None

    @property
    def tools(self) -> list[ToolInfo]:
        return list(self._tools)

    @property
    def is_running(self) -> bool:
        return self._session is not None

    async def start(self, env: dict[str, str]) -> list[ToolInfo]:
        """Spawn the subprocess, initialize MCP session, discover tools.

        Args:
            env: Environment variables to inject (STS temp creds + region).

        Returns:
            List of discovered tools with qualified (prefixed) names.
        """
        if self._session is not None:
            await self.stop()

        # Merge subprocess env with STS credentials
        process_env = {**os.environ, **env}

        server_params = StdioServerParameters(
            command=self.catalog.command,
            env=process_env,
        )

        self._exit_stack = AsyncExitStack()
        try:
            stdio_transport = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read_stream, write_stream = stdio_transport
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()

            # Discover tools
            tools_result = await self._session.list_tools()
            self._tools = []
            for tool in tools_result.tools:
                tool_info = ToolInfo(
                    name=tool.name,
                    qualified_name=f"{self.catalog.tool_prefix}.{tool.name}",
                    description=tool.description or "",
                    input_schema=tool.inputSchema if tool.inputSchema else {},
                    server_name=self.catalog.name,
                )
                self._tools.append(tool_info)

            logger.info(
                "Started {} — discovered {} tools",
                self.catalog.name,
                len(self._tools),
            )
            return self._tools

        except Exception:
            logger.exception("Failed to start {}", self.catalog.name)
            await self.stop()
            raise

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Forward a tool call to the subprocess via MCP session.

        Args:
            tool_name: Original (unprefixed) tool name.
            arguments: Tool arguments dict.

        Returns:
            Tool call result from the MCP server.
        """
        if self._session is None:
            raise RuntimeError(f"Server {self.catalog.name} is not running")

        result = await self._session.call_tool(tool_name, arguments)
        return result

    async def stop(self) -> None:
        """Terminate the subprocess and clean up resources."""
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                logger.warning("Error closing subprocess for {}", self.catalog.name)
            finally:
                self._exit_stack = None
                self._session = None
                self._tools = []
                self.pid = None
                logger.info("Stopped {}", self.catalog.name)
