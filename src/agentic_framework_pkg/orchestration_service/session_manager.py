"""
Multi-Tier Session Manager for Hybrid Architecture

This module implements the session management layer for the hybrid orchestration
approach, providing efficient agent persistence while maintaining full multi-tier
session capabilities.
"""

import os
import asyncio
import time
import uuid
from typing import Dict, Optional, List, Any, TYPE_CHECKING
from contextlib import asynccontextmanager

from .session_hierarchy import SessionHierarchy, InteractionType, SessionHierarchyBuilder
from .persistence import SessionPersistenceManager, SessionPersistenceError
from ..logger_config import get_logger

if TYPE_CHECKING:
    from .scientific_workflow.langchain_agent import ScientificWorkflowAgent
    from .request_context import RequestContext

logger = get_logger(__name__)


class A2ASessionRegistry:
    """
    Registry for tracking Agent-to-Agent (A2A) cross-gateway sessions.
    
    This registry maintains the state of active cross-gateway delegations
    and enables proper routing of responses back to originating gateways.
    """
    
    def __init__(self):
        self.active_a2a_sessions: Dict[str, Dict[str, Any]] = {}
        self.gateway_routes: Dict[str, List[str]] = {}
        self._lock = asyncio.Lock()
    
    async def register_agent(self, agent: 'ScientificWorkflowAgent') -> None:
        """Register an agent for A2A communication"""
        if not agent.session_hierarchy.gateway_session_id:
            return
        
        async with self._lock:
            gateway_session_id = agent.session_hierarchy.gateway_session_id
            self.active_a2a_sessions[gateway_session_id] = {
                "agent_pool_key": agent.session_hierarchy.get_pool_key(),
                "delegation_source": agent.session_hierarchy.delegation_source,
                "return_path": agent.session_hierarchy.return_path,
                "registered_at": time.time()
            }
            
            # Track gateway routes for mesh communication
            if agent.session_hierarchy.delegation_source:
                source = agent.session_hierarchy.delegation_source
                if source not in self.gateway_routes:
                    self.gateway_routes[source] = []
                self.gateway_routes[source].append(gateway_session_id)
    
    async def unregister_agent(self, gateway_session_id: str) -> None:
        """Unregister an agent from A2A communication"""
        async with self._lock:
            if gateway_session_id in self.active_a2a_sessions:
                session_info = self.active_a2a_sessions.pop(gateway_session_id)
                
                # Clean up gateway routes
                if session_info.get("delegation_source"):
                    source = session_info["delegation_source"]
                    if source in self.gateway_routes:
                        self.gateway_routes[source] = [
                            gw_id for gw_id in self.gateway_routes[source] 
                            if gw_id != gateway_session_id
                        ]
                        if not self.gateway_routes[source]:
                            del self.gateway_routes[source]
    
    async def is_gateway_mesh_active(self, gateway_session_id: str) -> bool:
        """Check if a gateway session is still active in the mesh"""
        return gateway_session_id in self.active_a2a_sessions


class MultiTierSessionManager:
    """
    Manages the complete session hierarchy for hybrid agents.
    
    This manager handles:
    - Session hierarchy creation and lifecycle
    - Agent pool management with multi-tier keys
    - Session expiration and cleanup
    - Inter-service session coordination
    """
    
    def __init__(self, default_ttl_seconds: int = 3600):
        self.session_hierarchies: Dict[str, SessionHierarchy] = {}
        self.agent_pool: Dict[str, 'ScientificWorkflowAgent'] = {}
        self.default_ttl_seconds = default_ttl_seconds

        # Cross-service coordination
        self.a2a_registry = A2ASessionRegistry()
        self.multi_agent_teams: Dict[str, Dict[str, Any]] = {}

        # Concurrency control
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown = False

        # Session persistence (Phase 2)
        self.persistence = SessionPersistenceManager()
        self.persistence_enabled = os.getenv("SESSION_PERSISTENCE_ENABLED", "false").lower() == "true"
        if self.persistence_enabled:
            logger.info("✅ Session persistence enabled")
    
    async def start(self) -> None:
        """Start the session manager and background cleanup task"""
        logger.info("Starting MultiTierSessionManager")
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop(self) -> None:
        """Stop the session manager and cleanup resources"""
        logger.info("Stopping MultiTierSessionManager")
        self._shutdown = True
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Clean up all active sessions
        await self._cleanup_all_sessions()
    
    @asynccontextmanager
    async def get_session_lock(self, session_key: str):
        """Get or create a lock for a specific session"""
        async with self._global_lock:
            if session_key not in self._session_locks:
                self._session_locks[session_key] = asyncio.Lock()
            lock = self._session_locks[session_key]
        
        async with lock:
            yield
    
    async def create_session_hierarchy(self, base_session_id: str, 
                                     context: Dict[str, Any]) -> SessionHierarchy:
        """
        Create complete multi-tier session context.
        
        Args:
            base_session_id: The base session identifier
            context: Additional context for session creation
        
        Returns:
            SessionHierarchy: Complete session hierarchy
        """
        async with self.get_session_lock(base_session_id):
            # Check if hierarchy already exists
            if base_session_id in self.session_hierarchies:
                existing = self.session_hierarchies[base_session_id]
                existing.refresh_usage()
                return existing
            
            # Create new hierarchy based on context
            hierarchy = SessionHierarchyBuilder.from_service_request({
                "session_id": base_session_id,
                **context
            })
            
            self.session_hierarchies[base_session_id] = hierarchy
            
            logger.info(f"Created session hierarchy: {hierarchy}")
            return hierarchy
    
    async def get_or_create_agent(self, request_context: Dict[str, Any]) -> 'ScientificWorkflowAgent':
        """
        Get existing agent or create new one with session-aware caching.
        
        This is the core method that provides agent persistence while
        maintaining proper session isolation.
        """
        # Resolve complete session hierarchy
        hierarchy = await self._resolve_session_hierarchy(request_context)
        pool_key = hierarchy.get_pool_key()

        # CRITICAL FIX: Extract user_credentials from request_context
        # Required for multi-agent orchestration (mcp_langchain_tools.py:1363)
        user_credentials = request_context.get("user_credentials")

        # Extract request_context (RequestContext dataclass) from request_context dict
        # Used for presigned URL generation with correct hostname (Option B - Phase 3)
        http_request_context = request_context.get("http_request_context")

        async with self.get_session_lock(pool_key):
            # Check if agent exists in pool
            if pool_key in self.agent_pool:
                agent = self.agent_pool[pool_key]

                # Update session hierarchy usage
                hierarchy.refresh_usage()
                agent.session_hierarchy = hierarchy

                # CRITICAL FIX: Update user_credentials if provided
                # Ensures pooled agents have current credentials for multi-agent sessions
                if user_credentials:
                    agent.user_credentials = user_credentials

                # Update request_context if provided (for URL generation)
                if http_request_context:
                    agent.request_context = http_request_context

                logger.info(f"Reusing existing agent for session: {hierarchy}")
                return agent

            # Create new agent with complete session binding
            logger.info(f"Creating new agent for session: {hierarchy}")

            # Import here to avoid circular imports
            from .scientific_workflow.langchain_agent import ScientificWorkflowAgent

            # Phase 2: Use async create() for proper agent initialization
            # The create() method calls async_init() which builds the runnable
            agent = await ScientificWorkflowAgent.create(
                session_hierarchy=hierarchy,
                user_credentials=user_credentials,  # CRITICAL FIX: Pass user credentials
                request_context=http_request_context  # Thread request context for URL generation
            )
            self.agent_pool[pool_key] = agent

            # Register for A2A communication if applicable
            if hierarchy.supports_a2a:
                await self.a2a_registry.register_agent(agent)

            # Register multi-agent team if applicable
            if hierarchy.supports_multi_agent:
                await self._register_multi_agent_member(agent)

            # Phase 2: Persist new session to database (non-blocking)
            if self.persistence_enabled:
                try:
                    await self._persist_new_session(hierarchy, user_credentials)
                except Exception as e:
                    # Non-blocking: Log error but don't fail agent creation
                    logger.error(
                        f"Failed to persist session {hierarchy.session_id} to database: {e}",
                        exc_info=True
                    )

            return agent

    async def _persist_new_session(
        self,
        hierarchy: SessionHierarchy,
        user_credentials: Optional[Dict[str, Any]]
    ) -> None:
        """
        Persist a new session to the database.

        Args:
            hierarchy: Session hierarchy to persist
            user_credentials: Optional user credentials from request context

        Raises:
            SessionPersistenceError: If persistence fails (caught by caller)
        """
        # Determine session type from interaction type
        session_type_map = {
            InteractionType.DIRECT_USER: "response",
            InteractionType.MULTI_AGENT: "multi_agent",
            InteractionType.A2A_DELEGATION: "response",
            InteractionType.ORCHESTRATION: "response",
        }
        session_type = session_type_map.get(
            hierarchy.interaction_type,
            "response"
        )

        # Extract user information
        user_id = "unknown"
        username = None
        if user_credentials:
            user_id = user_credentials.get("user_id", "unknown")
            username = user_credentials.get("username")

        # Build metadata
        metadata = {
            "interaction_type": hierarchy.interaction_type.value,
            "created_by_session_manager": True,
        }

        # Persist to database
        await self.persistence.create_session(
            session_id=hierarchy.session_id,
            user_id=user_id,
            username=username,
            session_type=session_type,
            mcp_session_id=hierarchy.mcp_session_id,
            multi_agent_session_id=hierarchy.multi_agent_session_id,
            gateway_session_id=hierarchy.gateway_session_id,
            title=None,  # Will be auto-generated later (Phase 4)
            tags=[],
            retention_policy="indefinite",
            metadata=metadata
        )

        logger.debug(
            f"Persisted session to database: {hierarchy.session_id} "
            f"(user={user_id}, type={session_type})"
        )

    async def _resolve_session_hierarchy(self, context: Dict[str, Any]) -> SessionHierarchy:
        """
        Intelligently resolve the complete session hierarchy from context.
        
        This method handles different types of requests and builds the appropriate
        session hierarchy for each case.
        """
        # Case 1: Already have complete hierarchy
        if "session_hierarchy" in context:
            return SessionHierarchy.from_dict(context["session_hierarchy"])
        
        # Case 2: Direct user request (Streamlit, CLI)
        if "session_id" in context and not context.get("gateway_session_id"):
            base_session = context["session_id"]
            return await self.create_session_hierarchy(base_session, context)
        
        # Case 3: Multi-agent orchestration request
        if context.get("multi_agent_session_id"):
            return await self._get_or_create_multi_agent_hierarchy(context)
        
        # Case 4: A2A delegation from another gateway
        if context.get("gateway_session_id"):
            return await self._resolve_a2a_session_hierarchy(context)
        
        # Case 5: OpenAI API compatibility request
        if context.get("thread_id"):
            return SessionHierarchyBuilder.from_openai_context(
                context["thread_id"], 
                context.get("assistant_id")
            )
        
        # Case 6: Fallback - create minimal hierarchy
        session_id = context.get("session_id", f"auto-{uuid.uuid4().hex[:12]}")
        return await self.create_session_hierarchy(session_id, context)
    
    async def _get_or_create_multi_agent_hierarchy(self, context: Dict[str, Any]) -> SessionHierarchy:
        """Handle multi-agent session hierarchy creation"""
        team_session_id = context["multi_agent_session_id"]
        
        # Check if we have team configuration
        if team_session_id in self.multi_agent_teams:
            team_config = self.multi_agent_teams[team_session_id]
            base_session = context.get("session_id", team_config.get("base_session_id"))
        else:
            # Create new team configuration
            base_session = context.get("session_id", f"team-{team_session_id}")
            self.multi_agent_teams[team_session_id] = {
                "base_session_id": base_session,
                "created_at": time.time(),
                "team_members": [],
                "gateway_session_id": context.get("gateway_session_id")
            }
        
        return SessionHierarchy.create_for_multi_agent(
            session_id=base_session,
            multi_agent_session_id=team_session_id,
            gateway_session_id=context.get("gateway_session_id")
        )
    
    async def _resolve_a2a_session_hierarchy(self, context: Dict[str, Any]) -> SessionHierarchy:
        """Handle A2A delegation session hierarchy"""
        original_session = context.get("original_session_id")
        if not original_session:
            # Create new session for delegation
            original_session = f"a2a-{uuid.uuid4().hex[:12]}"
        
        # Look up original hierarchy if it exists
        original_hierarchy = self.session_hierarchies.get(original_session)
        if original_hierarchy:
            return SessionHierarchy.create_for_a2a_delegation(
                original_hierarchy=original_hierarchy,
                gateway_session_id=context["gateway_session_id"],
                delegation_source=context.get("delegation_source", "unknown"),
                delegation_chain=context.get("delegation_chain", [])
            )
        
        # Create minimal A2A hierarchy
        return SessionHierarchy(
            session_id=original_session,
            gateway_session_id=context["gateway_session_id"],
            interaction_type=InteractionType.A2A_DELEGATION,
            delegation_source=context.get("delegation_source")
        )
    
    async def _register_multi_agent_member(self, agent: 'ScientificWorkflowAgent') -> None:
        """Register agent as part of a multi-agent team"""
        team_id = agent.session_hierarchy.multi_agent_session_id
        if not team_id or team_id not in self.multi_agent_teams:
            return
        
        team_config = self.multi_agent_teams[team_id]
        member_info = {
            "agent_pool_key": agent.session_hierarchy.get_pool_key(),
            "session_id": agent.session_hierarchy.session_id,
            "role": agent.session_hierarchy.session_id.split("::")[-1],  # Extract role from session ID
            "registered_at": time.time()
        }
        
        team_config["team_members"].append(member_info)
    
    async def cleanup_expired_sessions(self) -> None:
        """Clean up agents while preserving active multi-tier sessions"""
        expired_pool_keys = []
        
        async with self._global_lock:
            for pool_key, agent in self.agent_pool.items():
                hierarchy = agent.session_hierarchy
                
                # Check if any tier is still active
                if not hierarchy.is_expired(self.default_ttl_seconds):
                    continue
                
                # Special handling for multi-agent sessions
                if hierarchy.multi_agent_session_id:
                    if await self._is_team_session_active(hierarchy.multi_agent_session_id):
                        continue
                
                # Special handling for A2A sessions
                if hierarchy.gateway_session_id:
                    if await self.a2a_registry.is_gateway_mesh_active(hierarchy.gateway_session_id):
                        continue
                
                # Mark for cleanup
                expired_pool_keys.append(pool_key)
        
        # Clean up expired agents
        for pool_key in expired_pool_keys:
            await self._cleanup_agent(pool_key)
        
        if expired_pool_keys:
            logger.info(f"Cleaned up {len(expired_pool_keys)} expired agent sessions")
    
    async def _is_team_session_active(self, team_session_id: str) -> bool:
        """Check if a multi-agent team session is still active"""
        if team_session_id not in self.multi_agent_teams:
            return False
        
        team_config = self.multi_agent_teams[team_session_id]
        team_last_used = max(
            member.get("last_used", 0) 
            for member in team_config.get("team_members", [])
        ) if team_config.get("team_members") else team_config.get("created_at", 0)
        
        return (time.time() - team_last_used) < self.default_ttl_seconds
    
    async def _cleanup_agent(self, pool_key: str) -> None:
        """Clean up a specific agent and its session context"""
        if pool_key not in self.agent_pool:
            return

        agent = self.agent_pool.pop(pool_key)
        hierarchy = agent.session_hierarchy

        # Clean up agent resources (including checkpointer disposal)
        await agent.cleanup()

        # Unregister from A2A registry
        if hierarchy.gateway_session_id:
            await self.a2a_registry.unregister_agent(hierarchy.gateway_session_id)
        
        # Clean up session hierarchy if no longer referenced
        if hierarchy.session_id in self.session_hierarchies:
            # Check if any other agents reference this hierarchy
            hierarchy_in_use = any(
                other_agent.session_hierarchy.session_id == hierarchy.session_id
                for other_agent in self.agent_pool.values()
            )
            
            if not hierarchy_in_use:
                del self.session_hierarchies[hierarchy.session_id]
        
        # Clean up session lock
        if pool_key in self._session_locks:
            del self._session_locks[pool_key]
        
        logger.debug(f"Cleaned up agent session: {hierarchy}")
    
    async def _cleanup_all_sessions(self) -> None:
        """Clean up all sessions during shutdown"""
        pool_keys = list(self.agent_pool.keys())
        for pool_key in pool_keys:
            await self._cleanup_agent(pool_key)
        
        self.session_hierarchies.clear()
        self.multi_agent_teams.clear()
        self._session_locks.clear()
    
    async def _cleanup_loop(self) -> None:
        """Background cleanup loop"""
        while not self._shutdown:
            try:
                await asyncio.sleep(300)  # Run cleanup every 5 minutes
                await self.cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in session cleanup loop: {e}", exc_info=True)
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about active sessions"""
        current_time = time.time()
        
        stats = {
            "total_sessions": len(self.session_hierarchies),
            "total_agents": len(self.agent_pool),
            "multi_agent_teams": len(self.multi_agent_teams),
            "a2a_sessions": len(self.a2a_registry.active_a2a_sessions),
            "session_types": {},
            "agent_pool_utilization": {}
        }
        
        # Count by interaction type
        for hierarchy in self.session_hierarchies.values():
            interaction_type = hierarchy.interaction_type.value
            stats["session_types"][interaction_type] = stats["session_types"].get(interaction_type, 0) + 1
        
        # Agent pool utilization
        for pool_key, agent in self.agent_pool.items():
            age_minutes = (current_time - agent.session_hierarchy.created_at) / 60
            usage_count = agent.session_hierarchy.interaction_count
            
            if age_minutes < 60:
                age_bucket = "< 1 hour"
            elif age_minutes < 1440:
                age_bucket = "< 1 day"
            else:
                age_bucket = "> 1 day"
            
            if age_bucket not in stats["agent_pool_utilization"]:
                stats["agent_pool_utilization"][age_bucket] = {"count": 0, "total_usage": 0}
            
            stats["agent_pool_utilization"][age_bucket]["count"] += 1
            stats["agent_pool_utilization"][age_bucket]["total_usage"] += usage_count
        
        return stats


# Global instance for backward compatibility with standalone function imports
_global_session_manager: Optional[MultiTierSessionManager] = None


def get_global_session_manager() -> MultiTierSessionManager:
    """Get or create the global session manager instance"""
    global _global_session_manager
    if _global_session_manager is None:
        _global_session_manager = MultiTierSessionManager()
    return _global_session_manager


async def get_session_context(session_id: str) -> Dict[str, Any]:
    """
    Backward compatibility function for session context retrieval.
    
    Args:
        session_id: Session identifier
        
    Returns:
        Dict containing session context data
    """
    manager = get_global_session_manager()
    
    # Try to find existing hierarchy
    if session_id in manager.session_hierarchies:
        hierarchy = manager.session_hierarchies[session_id]
        hierarchy.refresh_usage()
        return {
            "session_id": hierarchy.session_id,
            "gateway_session_id": hierarchy.gateway_session_id,
            "multi_agent_session_id": hierarchy.multi_agent_session_id,
            "interaction_type": hierarchy.interaction_type.value,
            "user_id": getattr(hierarchy, 'user_id', None),
            "created_at": hierarchy.created_at,
            "last_used_at": hierarchy.last_used,
            "interaction_count": hierarchy.interaction_count
        }
    
    # Return minimal context for unknown session
    return {
        "session_id": session_id,
        "user_id": None,
        "created_at": time.time(),
        "last_used_at": time.time(),
        "interaction_count": 0
    }


async def update_session_context(session_id: str, context_updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Backward compatibility function for session context updates.
    
    Args:
        session_id: Session identifier
        context_updates: Dictionary of updates to apply
        
    Returns:
        Updated session context
    """
    manager = get_global_session_manager()
    
    async with manager.get_session_lock(session_id):
        # Get or create hierarchy
        if session_id not in manager.session_hierarchies:
            hierarchy = await manager.create_session_hierarchy(session_id, context_updates)
        else:
            hierarchy = manager.session_hierarchies[session_id]
            hierarchy.refresh_usage()
        
        # Apply updates (limited to safe fields)
        safe_updates = {
            k: v for k, v in context_updates.items()
            if k in ['user_id', 'metadata', 'last_used_at']
        }
        
        if 'user_id' in safe_updates:
            hierarchy.user_id = safe_updates['user_id']
        
        if 'metadata' in safe_updates:
            if not hasattr(hierarchy, 'metadata'):
                hierarchy.metadata = {}
            hierarchy.metadata.update(safe_updates['metadata'])
    
    return await get_session_context(session_id)


async def create_session_if_not_exists(session_id: str, initial_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Backward compatibility function for session creation.
    
    Args:
        session_id: Session identifier
        initial_context: Initial context for session creation
        
    Returns:
        Session context dictionary
    """
    manager = get_global_session_manager()
    
    if session_id not in manager.session_hierarchies:
        hierarchy = await manager.create_session_hierarchy(
            session_id, 
            initial_context or {}
        )
    
    return await get_session_context(session_id)