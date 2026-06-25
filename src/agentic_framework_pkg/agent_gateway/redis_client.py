"""
Shared Redis connection pool management for agent gateway.

Provides singleton connection pool for service API tokens:
- Database /1: Service API tokens

This module is isolated to agent_gateway to avoid circular imports
with orchestration_service.

Motivation:
- Centralized token management with Redis Database 1
- Enables atomic transactions with MULTI/EXEC and Lua scripts
- Optimizes connection usage with 4 uvicorn workers

Architecture:
- Module-level singleton pool for database 1 (tokens)
- Lazy initialization on first access
- Connection pool sizing: max_connections=20 (4 workers × 5 connections per worker)
"""

import os
import redis.asyncio as redis
from typing import Optional
from ..logger_config import get_logger

logger = get_logger(__name__)

# Module-level singleton connection pool
_redis_pool_db1: Optional[redis.Redis] = None  # Service API tokens


async def get_tokens_redis_client() -> redis.Redis:
    """
    Get or create a shared Redis connection pool for service API tokens (Database 1).

    Returns:
        redis.Redis: Async Redis client with connection pooling
    """
    global _redis_pool_db1

    if _redis_pool_db1 is None:
        # Parse base Redis URL and force database /1
        base_url = os.getenv("REDIS_URL", "redis://redis:6379/0").rsplit("/", 1)[0]
        redis_url = f"{base_url}/1"
        _redis_pool_db1 = redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,  # 4 workers × 5 connections
        )
        logger.info(f"Initialized shared Redis pool for database /1 (service tokens) at {redis_url}")

    return _redis_pool_db1


async def close_redis_clients():
    """
    Close Redis connection pool.

    Call this during service shutdown to gracefully close connections.
    """
    global _redis_pool_db1

    if _redis_pool_db1:
        await _redis_pool_db1.close()
        logger.info("Closed Redis connection pool for database /1 (service tokens)")
        _redis_pool_db1 = None
