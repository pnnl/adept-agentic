"""
Academy MCP Server — Manager Registry

Session-scoped AcademyManagerRegistry singleton for managing Academy Manager
instances with per-session isolation, matching ADEPT's mcp_session_id pattern.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from academy.agent import Agent
from academy.exchange import LocalExchangeFactory
from academy.handle import Handle
from academy.manager import Manager

logger = logging.getLogger("academy_mcp_server")


@dataclass
class _SessionState:
    """State for a single MCP session."""

    manager: Manager
    handles: Dict[str, Handle] = field(default_factory=dict)
    agent_metadata: Dict[str, dict] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class AcademyManagerRegistry:
    """Session-scoped registry for Academy Manager instances.

    Each mcp_session_id gets its own Manager with LocalExchangeFactory,
    providing full isolation between concurrent users/sessions.

    Usage:
        registry = AcademyManagerRegistry()
        agent_id, actions = await registry.launch_agent(session_id, EchoAgent)
        result = await registry.invoke_action(session_id, agent_id, "echo", message="hi")
        agents = await registry.list_agents(session_id)
        await registry.shutdown_agent(session_id, agent_id)
        await registry.cleanup_session(session_id)
    """

    def __init__(self):
        self._sessions: Dict[str, _SessionState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a per-session lock for concurrency control."""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    async def get_or_create_session(self, session_id: str) -> _SessionState:
        """Get existing session or create a new one with a fresh Manager."""
        lock = self._get_lock(session_id)
        async with lock:
            if session_id not in self._sessions:
                logger.info(
                    "[SESSION_CREATE] Creating Academy Manager for session=%s",
                    session_id,
                )
                manager = await Manager.from_exchange_factory(
                    factory=LocalExchangeFactory()
                )
                self._sessions[session_id] = _SessionState(manager=manager)
            return self._sessions[session_id]

    async def launch_agent(
        self,
        session_id: str,
        agent_class: Type[Agent],
        agent_type: str,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """Launch an agent in the given session.

        Args:
            session_id: MCP session ID for isolation.
            agent_class: Academy Agent subclass to instantiate.
            agent_type: String name of the agent type (echo/counter/compute).
            agent_config: kwargs passed to agent constructor.

        Returns:
            (agent_id_str, actions_list) tuple.
        """
        session = await self.get_or_create_session(session_id)
        lock = self._get_lock(session_id)

        async with lock:
            handle = await session.manager.launch(
                agent_class, kwargs=agent_config or {}
            )
            # Bind the Manager's exchange client directly to the Handle so
            # callers outside the Manager's task-group context (e.g. MCP tool
            # handlers, tests) can invoke actions without relying on the
            # exchange_context ContextVar.
            if handle._exchange is None:
                handle._exchange = session.manager.exchange_client
            agent_id_str = str(handle.agent_id)

            # Discover available actions
            try:
                description = await handle.agent_describe()
                actions = list(description.keys()) if isinstance(description, dict) else []
            except Exception:
                actions = []
                logger.warning(
                    "[AGENT_DESCRIBE_FALLBACK] Could not describe agent %s, "
                    "returning empty actions",
                    agent_id_str,
                )

            session.handles[agent_id_str] = handle
            session.agent_metadata[agent_id_str] = {
                "agent_type": agent_type,
                "status": "running",
                "actions": actions,
                "created_at": datetime.utcnow().isoformat(),
            }

            logger.info(
                "[AGENT_LAUNCH] agent_id=%s type=%s actions=%s session=%s",
                agent_id_str,
                agent_type,
                actions,
                session_id,
            )

            return agent_id_str, actions

    async def invoke_action(
        self,
        session_id: str,
        agent_id: str,
        action_name: str,
        timeout: int = 30,
        **action_args: Any,
    ) -> Any:
        """Invoke an action on an agent.

        Args:
            session_id: MCP session ID.
            agent_id: Agent ID string.
            action_name: Name of the @action method to call.
            timeout: Timeout in seconds.
            **action_args: Arguments to pass to the action.

        Returns:
            Action result (usually a dict).

        Raises:
            KeyError: If session or agent not found.
            asyncio.TimeoutError: If action exceeds timeout.
        """
        session = await self.get_or_create_session(session_id)

        if agent_id not in session.handles:
            raise KeyError(
                f"Agent '{agent_id}' not found in session '{session_id}'. "
                f"Available agents: {list(session.handles.keys())}"
            )

        handle = session.handles[agent_id]

        logger.info(
            "[ACTION_INVOKE] agent_id=%s action=%s args=%s timeout=%ds session=%s",
            agent_id,
            action_name,
            action_args,
            timeout,
            session_id,
        )

        start_time = time.monotonic()
        result = await asyncio.wait_for(
            handle.action(action_name, **action_args),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start_time

        logger.info(
            "[ACTION_RESULT] agent_id=%s action=%s elapsed=%.3fs session=%s",
            agent_id,
            action_name,
            elapsed,
            session_id,
        )

        return result

    async def list_agents(self, session_id: str) -> List[dict]:
        """List all agents in the given session.

        Args:
            session_id: MCP session ID.

        Returns:
            List of agent info dicts with agent_id, agent_type, status, actions, created_at.
        """
        session = await self.get_or_create_session(session_id)
        agents = []
        for agent_id, metadata in session.agent_metadata.items():
            agents.append({"agent_id": agent_id, **metadata})
        return agents

    async def shutdown_agent(
        self, session_id: str, agent_id: str, blocking: bool = True
    ) -> None:
        """Shut down an agent in the given session.

        Args:
            session_id: MCP session ID.
            agent_id: Agent ID string.
            blocking: If True, wait for shutdown to complete.

        Raises:
            KeyError: If session or agent not found.
        """
        session = await self.get_or_create_session(session_id)
        lock = self._get_lock(session_id)

        async with lock:
            if agent_id not in session.handles:
                raise KeyError(
                    f"Agent '{agent_id}' not found in session '{session_id}'"
                )

            handle = session.handles[agent_id]

            logger.info(
                "[AGENT_SHUTDOWN] agent_id=%s blocking=%s session=%s",
                agent_id,
                blocking,
                session_id,
            )

            await session.manager.shutdown(handle, blocking=blocking)

            # Update metadata and remove handle
            if agent_id in session.agent_metadata:
                session.agent_metadata[agent_id]["status"] = "shutdown"
            del session.handles[agent_id]

    async def cleanup_session(self, session_id: str) -> None:
        """Clean up all resources for a session.

        Shuts down all agents and closes the Manager.

        Args:
            session_id: MCP session ID.
        """
        lock = self._get_lock(session_id)
        async with lock:
            if session_id not in self._sessions:
                return

            session = self._sessions[session_id]

            # Shutdown remaining agents
            for agent_id, handle in list(session.handles.items()):
                try:
                    await session.manager.shutdown(handle, blocking=False)
                    logger.info(
                        "[SESSION_CLEANUP] Shut down agent %s in session %s",
                        agent_id,
                        session_id,
                    )
                except Exception as e:
                    logger.warning(
                        "[SESSION_CLEANUP] Error shutting down agent %s: %s",
                        agent_id,
                        e,
                    )

            # Close the manager
            try:
                await session.manager.close()
            except Exception as e:
                logger.warning(
                    "[SESSION_CLEANUP] Error closing manager for session %s: %s",
                    session_id,
                    e,
                )

            del self._sessions[session_id]
            if session_id in self._locks:
                del self._locks[session_id]

            logger.info("[SESSION_CLEANUP] Session %s cleaned up", session_id)


# Module-level singleton
registry = AcademyManagerRegistry()
