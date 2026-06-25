"""
Hybrid Orchestration Service for Agent Pool Management

This module implements the HybridOrchestrationService that bridges the existing
OpenAI-compatible API endpoints with efficient agent persistence through the
MultiTierSessionManager.

Key Features:
- Preserves full OpenAI API compatibility
- Enables agent persistence and reuse for performance
- Maintains complete multi-tier session support
- Provides seamless integration with existing endpoints
"""

import os
import asyncio
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from .session_manager import MultiTierSessionManager
from .persistence_v2 import AsyncPostgresSaver
from .persistence import AsyncSessionLocal
from .models import Assistant
from .external_tool_manager import tool_manager
from ..core.auth import AuthCredentials
from ..logger_config import get_logger
from sqlalchemy.future import select

# Import cleanup scheduler for session management
from .jobs.cleanup_scheduler import start_cleanup_scheduler, stop_cleanup_scheduler

# Import storage cleanup task
from .routers.v1.storage_quota import storage_cleanup_task

# Import partition maintenance for session_messages
from .persistence.partition_maintenance import (
    startup_ensure_partitions,
    _partition_maintenance_loop,
)

# Import here to avoid circular imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .scientific_workflow.langchain_agent import ScientificWorkflowAgent

logger = get_logger(__name__)


class HybridOrchestrationService:
    """
    Core orchestration service that bridges OpenAI API compatibility
    with efficient agent persistence.
    
    This service maintains the existing OpenAI-compatible API surface
    while providing intelligent agent pooling and session management
    underneath for optimal performance.
    """
    
    def __init__(self):
        self.session_manager = MultiTierSessionManager()
        self.checkpointer = AsyncPostgresSaver()
        self._started = False
        self._storage_cleanup_task = None
        self._partition_maintenance_task = None
    
    async def start(self) -> None:
        """Start the hybrid orchestration service"""
        if self._started:
            return

        logger.info("Starting HybridOrchestrationService")

        # Initialize checkpointer with module-level pool (LangGraph 1.0.5)
        await self.checkpointer.setup()
        logger.info("✅ LangGraph 1.0.5 checkpointer initialized with module-level pool")

        await self.session_manager.start()

        # Start cleanup scheduler if session persistence is enabled
        if os.getenv("SESSION_PERSISTENCE_ENABLED", "false").lower() == "true":
            await start_cleanup_scheduler()
            logger.info("✅ Session cleanup scheduler started")

        # Start storage cleanup background task for ephemeral files
        self._storage_cleanup_task = asyncio.create_task(storage_cleanup_task())
        logger.info("✅ Storage cleanup background task started (7-day TTL for ephemeral files)")

        # Ensure session_messages partitions exist (startup + background 24h check)
        await startup_ensure_partitions()
        self._partition_maintenance_task = asyncio.create_task(_partition_maintenance_loop())
        logger.info("✅ Partition maintenance started (current + 6 months, 24h refresh)")

        self._started = True
    
    async def stop(self) -> None:
        """Stop the hybrid orchestration service"""
        if not self._started:
            return

        logger.info("Stopping HybridOrchestrationService")

        # Stop cleanup scheduler if session persistence is enabled
        if os.getenv("SESSION_PERSISTENCE_ENABLED", "false").lower() == "true":
            await stop_cleanup_scheduler()
            logger.info("✅ Session cleanup scheduler stopped")

        # Stop storage cleanup background task
        if self._storage_cleanup_task:
            self._storage_cleanup_task.cancel()
            try:
                await self._storage_cleanup_task
            except asyncio.CancelledError:
                logger.info("✅ Storage cleanup background task cancelled")

        # Stop partition maintenance background task
        if self._partition_maintenance_task:
            self._partition_maintenance_task.cancel()
            try:
                await self._partition_maintenance_task
            except asyncio.CancelledError:
                logger.info("✅ Partition maintenance background task cancelled")

        await self.session_manager.stop()

        # Dispose checkpointer (no-op for shared module-level pool in LangGraph 1.0.5)
        # The module-level pool is closed at service shutdown via close_global_connection_pool()
        if self.checkpointer:
            logger.debug("Disposing AsyncPostgresSaver instance (shared pool not closed)")
            await self.checkpointer.dispose()

        self._started = False
    
    @asynccontextmanager
    async def lifespan_context(self):
        """Async context manager for service lifecycle"""
        await self.start()
        try:
            yield self
        finally:
            await self.stop()
    
    async def invoke_agent_legacy(
        self,
        user_input: str,
        thread_id: str,
        assistant_id: str,
        chat_history: list,
        user: AuthCredentials
    ) -> Dict[str, Any]:
        """
        Legacy agent invocation for backwards compatibility.
        
        This method preserves the existing /invoke endpoint behavior
        while utilizing agent persistence underneath.
        """
        logger.info(f"Legacy agent invocation for thread_id: {thread_id}")
        
        # Build request context for session resolution
        request_context = {
            "session_id": thread_id,
            "thread_id": thread_id,
            "assistant_id": assistant_id,
            "user_credentials": user,
            "interaction_type": "direct_user"
        }
        
        # Get or create agent with session-aware persistence
        agent = await self.session_manager.get_or_create_agent(request_context)
        
        # Load and bind assistant configuration
        await self._bind_assistant_config(agent, assistant_id)
        
        # Execute with full session context
        logger.info(f"Invoking agent for thread '{thread_id}' with input: '{user_input[:100]}...'")
        result = await agent.arun(user_input=user_input, chat_history=chat_history)
        logger.info(f"Agent execution completed for thread '{thread_id}'.")
        
        return result
    
    async def invoke_agent_openai_compat(
        self,
        request_context: Dict[str, Any]
    ) -> 'ScientificWorkflowAgent':
        """
        OpenAI-compatible agent invocation for Assistant/Thread API.
        
        This method handles requests from the OpenAI-compatible endpoints
        and returns a configured agent ready for execution.
        """
        thread_id = request_context.get("thread_id")
        assistant_id = request_context.get("assistant_id")
        
        logger.info(f"OpenAI-compatible agent invocation for thread_id: {thread_id}")
        
        # Get or create agent with complete session hierarchy
        agent = await self.session_manager.get_or_create_agent(request_context)
        
        # Load assistant configuration if provided
        if assistant_id:
            await self._bind_assistant_config(agent, assistant_id)
        
        return agent
    
    async def invoke_agent_multi_agent(
        self,
        request_context: Dict[str, Any]
    ) -> 'ScientificWorkflowAgent':
        """
        Multi-agent orchestration invocation.
        
        Handles multi-agent team workflows with proper session hierarchy
        and cross-gateway communication support.
        """
        team_session_id = request_context.get("multi_agent_session_id")
        logger.info(f"Multi-agent invocation for team: {team_session_id}")
        
        # Ensure multi-agent context is properly set
        request_context["interaction_type"] = "multi_agent"
        
        # Get or create agent with multi-agent session support
        agent = await self.session_manager.get_or_create_agent(request_context)
        
        return agent
    
    async def invoke_agent_a2a_delegation(
        self,
        request_context: Dict[str, Any]
    ) -> 'ScientificWorkflowAgent':
        """
        Agent-to-Agent delegation invocation.
        
        Handles cross-gateway agent delegation with proper session
        hierarchy preservation and return path management.
        """
        gateway_session_id = request_context.get("gateway_session_id")
        delegation_source = request_context.get("delegation_source")
        
        logger.info(f"A2A delegation from {delegation_source} via gateway: {gateway_session_id}")
        
        # Ensure A2A context is properly set
        request_context["interaction_type"] = "a2a_delegation"
        
        # Get or create agent with A2A session support
        agent = await self.session_manager.get_or_create_agent(request_context)
        
        return agent
    
    async def _bind_assistant_config(
        self,
        agent: 'ScientificWorkflowAgent',
        assistant_id: str
    ) -> None:
        """
        Load and bind assistant configuration to agent.
        
        This preserves the existing assistant configuration loading
        while enabling it to work with persistent agents.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Assistant).where(Assistant.id == assistant_id)
            )
            assistant_config = result.scalars().first()
        
        if not assistant_config:
            raise ValueError(f"Assistant with ID '{assistant_id}' not found.")
        
        logger.info(f"Loaded configuration for assistant '{assistant_id}', model '{assistant_config.model}'.")
        
        # Update agent configuration
        agent.bind_assistant_config(
            assistant_id=assistant_id,
            model=assistant_config.model,
            instructions=assistant_config.instructions,
            tools=assistant_config.tools,
            metadata=assistant_config.metadata
        )
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get comprehensive session and agent pool statistics"""
        base_stats = self.session_manager.get_session_stats()

        # Add service-level stats
        base_stats.update({
            "service_status": "active" if self._started else "inactive",
            "tool_count": len(tool_manager.get_all_tools()),
        })

        return base_stats

    async def get_session_data(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session data including context for MCP servers.

        Args:
            session_id: The session identifier to look up

        Returns:
            Dictionary with session data including 'context' key, or None if not found
        """
        # Look up session hierarchy in the session manager
        hierarchy = self.session_manager.session_hierarchies.get(session_id)

        if not hierarchy:
            logger.debug(f"Session {session_id} not found in session hierarchies")
            return None

        # Build session data with context containing all session tier IDs
        session_data = {
            "context": {
                "session_id": hierarchy.session_id,
                "mcp_session_id": hierarchy.mcp_session_id,
                "multi_agent_session_id": hierarchy.multi_agent_session_id,
                "gateway_session_id": hierarchy.gateway_session_id,
                "assistant_id": hierarchy.assistant_id,
                "thread_id": hierarchy.thread_id,
                "interaction_type": hierarchy.interaction_type.value,
                "created_at": hierarchy.created_at,
                "last_used": hierarchy.last_used,
                "interaction_count": hierarchy.interaction_count,
            },
            "session_id": session_id,
            "active": True,
        }

        logger.debug(f"Retrieved session data for {session_id}")
        return session_data

    async def cleanup_expired_sessions(self) -> None:
        """Manually trigger session cleanup (for admin endpoints)"""
        await self.session_manager.cleanup_expired_sessions()


# Global service instance
hybrid_service = HybridOrchestrationService()


async def get_hybrid_service() -> HybridOrchestrationService:
    """Dependency injection for FastAPI endpoints"""
    if not hybrid_service._started:
        await hybrid_service.start()
    return hybrid_service