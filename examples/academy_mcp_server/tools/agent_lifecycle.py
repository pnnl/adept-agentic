"""
Academy Agent Lifecycle Tools

MCP tool implementations for launching, invoking, listing, and shutting down
Academy agents within ADEPT sessions.

Follows the canonical register(mcp) pattern — server.py calls register()
to bind tool functions to the FastMCP instance.
"""

import asyncio
import logging
import time
from typing import Any, Dict, Union

from fastmcp import Context, FastMCP

# Support both standalone (Docker) and subpackage (examples.academy_mcp_server) imports
try:
    from ..manager_registry import registry
    from ..agent_templates import AGENT_TEMPLATES
    from ..schemas import LaunchAgentInput
except ImportError:
    from manager_registry import registry
    from agent_templates import AGENT_TEMPLATES
    from schemas import LaunchAgentInput

logger = logging.getLogger("academy_mcp_server")


async def launch_academy_agent(
    agent_type: str,
    agent_config: Dict[str, Any],
    mcp_session_id: str = None,
) -> dict:
    """Launch an Academy agent in the given session.

    Args:
        agent_type: One of 'echo', 'counter', 'compute'.
        agent_config: kwargs passed to agent constructor.
        mcp_session_id: Session ID for isolation.

    Returns:
        Dict with status, agent_id, agent_type, actions, session_id.
    """
    session_id = mcp_session_id or "default"

    if agent_type not in AGENT_TEMPLATES:
        return {
            "status": "error",
            "error": (
                f"Unknown agent_type '{agent_type}'. "
                f"Available types: {list(AGENT_TEMPLATES.keys())}"
            ),
            "session_id": session_id,
        }

    agent_class = AGENT_TEMPLATES[agent_type]

    try:
        agent_id, actions = await registry.launch_agent(
            session_id=session_id,
            agent_class=agent_class,
            agent_type=agent_type,
            agent_config=agent_config,
        )

        return {
            "status": "running",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "actions": actions,
            "session_id": session_id,
        }
    except Exception as e:
        logger.error(
            "[LAUNCH_ERROR] agent_type=%s session=%s error=%s",
            agent_type,
            session_id,
            str(e),
        )
        return {
            "status": "error",
            "error": str(e),
            "agent_type": agent_type,
            "session_id": session_id,
        }


async def invoke_agent_action(
    agent_id: str,
    action_name: str,
    action_args: Dict[str, Any],
    timeout: int = 30,
    mcp_session_id: str = None,
) -> dict:
    """Invoke an action on a running Academy agent.

    Args:
        agent_id: Agent ID from launch_academy_agent.
        action_name: Name of the @action method to call.
        action_args: Arguments dict for the action.
        timeout: Timeout in seconds.
        mcp_session_id: Session ID for isolation.

    Returns:
        Dict with status, result, agent_id, action, execution_time, session_id.
    """
    session_id = mcp_session_id or "default"

    try:
        start_time = time.monotonic()
        result = await registry.invoke_action(
            session_id=session_id,
            agent_id=agent_id,
            action_name=action_name,
            timeout=timeout,
            **action_args,
        )
        elapsed = time.monotonic() - start_time

        return {
            "status": "success",
            "result": result,
            "agent_id": agent_id,
            "action": action_name,
            "execution_time": round(elapsed, 3),
            "session_id": session_id,
        }
    except KeyError as e:
        return {
            "status": "error",
            "error": str(e),
            "agent_id": agent_id,
            "action": action_name,
            "session_id": session_id,
        }
    except asyncio.TimeoutError:
        return {
            "status": "error",
            "error": f"Action '{action_name}' timed out after {timeout}s",
            "agent_id": agent_id,
            "action": action_name,
            "session_id": session_id,
        }
    except Exception as e:
        logger.error(
            "[ACTION_ERROR] agent_id=%s action=%s session=%s error=%s",
            agent_id,
            action_name,
            session_id,
            str(e),
        )
        return {
            "status": "error",
            "error": str(e),
            "agent_id": agent_id,
            "action": action_name,
            "session_id": session_id,
        }


async def list_academy_agents(
    mcp_session_id: str = None,
) -> dict:
    """List all Academy agents in the given session.

    Args:
        mcp_session_id: Session ID to list agents for.

    Returns:
        Dict with agents list, session_id, count.
    """
    session_id = mcp_session_id or "default"

    try:
        agents = await registry.list_agents(session_id)
        return {
            "agents": agents,
            "session_id": session_id,
            "count": len(agents),
        }
    except Exception as e:
        logger.error(
            "[LIST_ERROR] session=%s error=%s", session_id, str(e)
        )
        return {
            "agents": [],
            "session_id": session_id,
            "count": 0,
            "error": str(e),
        }


async def shutdown_academy_agent(
    agent_id: str,
    blocking: bool = True,
    mcp_session_id: str = None,
) -> dict:
    """Shut down an Academy agent.

    Args:
        agent_id: Agent ID to shut down.
        blocking: If True, wait for shutdown to complete.
        mcp_session_id: Session ID for isolation.

    Returns:
        Dict with status, agent_id, execution_time, session_id.
    """
    session_id = mcp_session_id or "default"

    try:
        start_time = time.monotonic()
        await registry.shutdown_agent(
            session_id=session_id,
            agent_id=agent_id,
            blocking=blocking,
        )
        elapsed = time.monotonic() - start_time

        return {
            "status": "shutdown",
            "agent_id": agent_id,
            "execution_time": round(elapsed, 3),
            "session_id": session_id,
        }
    except KeyError as e:
        return {
            "status": "error",
            "error": str(e),
            "agent_id": agent_id,
            "session_id": session_id,
        }
    except Exception as e:
        logger.error(
            "[SHUTDOWN_ERROR] agent_id=%s session=%s error=%s",
            agent_id,
            session_id,
            str(e),
        )
        return {
            "status": "error",
            "error": str(e),
            "agent_id": agent_id,
            "session_id": session_id,
        }


# ---------------------------------------------------------------------------
# MCP tool registration (canonical register(mcp) pattern)
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register all Academy lifecycle tools with the given FastMCP instance."""

    @mcp.tool()
    async def launch_academy_agent_tool(
        agent_type: str,
        agent_config: Union[dict, None] = None,
        mcp_session_id: str = None,
        ctx: Context = None,
    ) -> dict:
        """Launch a federated Academy agent (echo, counter, or compute).

        Creates a session-scoped Academy Manager (if none exists) and launches the
        specified agent type. Returns the agent ID and available actions.

        Agent types:
          - echo: Echoes messages back, tracks call count. Actions: echo, get_call_count
          - counter: Stateful counter with increment/decrement. Actions: increment, decrement, get_count, reset
          - compute: Scientific computations. Actions: factorial, fibonacci, is_prime, get_computation_count

        Args:
            agent_type: Type of agent to launch ('echo', 'counter', or 'compute').
            agent_config: Agent-specific configuration dict (e.g., {'initial_value': 10} for counter).
            mcp_session_id: Session ID for resource isolation across concurrent users.

        Returns:
            dict with status, agent_id, agent_type, actions list, and session_id.
        """
        config = agent_config or {}
        if isinstance(config, LaunchAgentInput):
            config = config.agent_config

        logger.info(
            "[TOOL_CALL] launch_academy_agent_tool | type=%s | config=%s | session=%s",
            agent_type, config, mcp_session_id or "none",
        )
        try:
            result = await launch_academy_agent(
                agent_type=agent_type, agent_config=config,
                mcp_session_id=mcp_session_id,
            )
            logger.info(
                "[TOOL_RESULT] launch_academy_agent_tool | status=%s | agent_id=%s",
                result.get("status", "unknown"), result.get("agent_id", "none"),
            )
            return result
        except Exception as e:
            logger.error("[TOOL_ERROR] launch_academy_agent_tool | error=%s", str(e))
            raise

    @mcp.tool()
    async def invoke_agent_action_tool(
        agent_id: str,
        action_name: str,
        action_args: Union[dict, None] = None,
        timeout: int = 30,
        mcp_session_id: str = None,
        ctx: Context = None,
    ) -> dict:
        """Invoke an action on a running Academy agent.

        Calls a named action method on a previously launched agent with the given
        arguments. Each agent type supports different actions:

          Echo agent: echo(message='hello'), get_call_count()
          Counter agent: increment(value=1), decrement(value=1), get_count(), reset()
          Compute agent: factorial(n=7), fibonacci(n=10), is_prime(n=17), get_computation_count()

        IMPORTANT: Pass action parameters inside the action_args dict, not as
        top-level arguments.

        Args:
            agent_id: Agent ID returned by launch_academy_agent.
            action_name: Name of the action to invoke.
            action_args: Dict of keyword arguments for the action.
            timeout: Timeout in seconds for the action (1-300, default 30).
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with status, result, agent_id, action, execution_time, session_id.
        """
        args = action_args or {}
        logger.info(
            "[TOOL_CALL] invoke_agent_action_tool | agent=%s | action=%s | args=%s | session=%s",
            agent_id, action_name, args, mcp_session_id or "none",
        )
        try:
            result = await invoke_agent_action(
                agent_id=agent_id, action_name=action_name,
                action_args=args, timeout=timeout,
                mcp_session_id=mcp_session_id,
            )
            logger.info(
                "[TOOL_RESULT] invoke_agent_action_tool | agent=%s | action=%s | status=%s",
                agent_id, action_name, result.get("status", "unknown"),
            )
            return result
        except Exception as e:
            logger.error("[TOOL_ERROR] invoke_agent_action_tool | error=%s", str(e))
            raise

    @mcp.tool()
    async def list_academy_agents_tool(
        mcp_session_id: str = None,
        ctx: Context = None,
    ) -> dict:
        """List all Academy agents in the current session.

        Returns information about all agents launched in the given session,
        including their IDs, types, statuses, available actions, and creation times.

        Args:
            mcp_session_id: Session ID to list agents for.

        Returns:
            dict with agents list, session_id, and count.
        """
        logger.info("[TOOL_CALL] list_academy_agents_tool | session=%s", mcp_session_id or "none")
        try:
            result = await list_academy_agents(mcp_session_id=mcp_session_id)
            logger.info(
                "[TOOL_RESULT] list_academy_agents_tool | count=%d | session=%s",
                result.get("count", 0), mcp_session_id or "none",
            )
            return result
        except Exception as e:
            logger.error("[TOOL_ERROR] list_academy_agents_tool | error=%s", str(e))
            raise

    @mcp.tool()
    async def shutdown_academy_agent_tool(
        agent_id: str,
        blocking: bool = True,
        mcp_session_id: str = None,
        ctx: Context = None,
    ) -> dict:
        """Shut down a running Academy agent.

        Gracefully shuts down the specified agent. If blocking=True, waits for
        the shutdown to complete before returning.

        Args:
            agent_id: Agent ID to shut down.
            blocking: If true, wait for shutdown to complete (default: true).
            mcp_session_id: Session ID for resource isolation.

        Returns:
            dict with status, agent_id, execution_time, session_id.
        """
        logger.info(
            "[TOOL_CALL] shutdown_academy_agent_tool | agent=%s | blocking=%s | session=%s",
            agent_id, blocking, mcp_session_id or "none",
        )
        try:
            result = await shutdown_academy_agent(
                agent_id=agent_id, blocking=blocking,
                mcp_session_id=mcp_session_id,
            )
            logger.info(
                "[TOOL_RESULT] shutdown_academy_agent_tool | agent=%s | status=%s",
                agent_id, result.get("status", "unknown"),
            )
            return result
        except Exception as e:
            logger.error("[TOOL_ERROR] shutdown_academy_agent_tool | error=%s", str(e))
            raise

    logger.info("Registered 4 Academy MCP tools")
