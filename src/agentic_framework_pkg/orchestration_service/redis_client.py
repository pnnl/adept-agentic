"""
Shared Redis connection pool management for orchestration service.

Provides singleton connection pools for different Redis databases:
- Database /0: Tool configurations and ACLs (external_tool_manager)
- Database /2: File metadata (files router, MCP tools, utility tools)

Motivation:
- Prevents connection pool fragmentation (4 independent redis.from_url() instances)
- Enables atomic transactions with MULTI/EXEC and Lua scripts
- Optimizes connection usage with 4 uvicorn workers

Architecture:
- Module-level singleton pools per database
- Lazy initialization on first access
- Connection pool sizing: max_connections=20 (4 workers × 5 connections per worker)
"""

import os
import redis.asyncio as redis
from typing import Optional
from ..logger_config import get_logger

logger = get_logger(__name__)

# Module-level singleton connection pools
_redis_pool_db0: Optional[redis.Redis] = None  # Tool configurations
_redis_pool_db1: Optional[redis.Redis] = None  # Service API tokens
_redis_pool_db2: Optional[redis.Redis] = None  # File metadata


async def get_redis_client(database: int = 2) -> redis.Redis:
    """
    Get or create a shared Redis connection pool for the specified database.

    Args:
        database: Redis database number (0 for tools, 1 for tokens, 2 for files)

    Returns:
        redis.Redis: Async Redis client with connection pooling

    Raises:
        ValueError: If unsupported database number provided
    """
    global _redis_pool_db0, _redis_pool_db1, _redis_pool_db2

    if database == 0:
        # Database /0: Tool configurations and ACLs
        if _redis_pool_db0 is None:
            # Parse base Redis URL and force database /0
            base_url = os.getenv("REDIS_URL", "redis://redis:6379/0").rsplit("/", 1)[0]
            redis_url = f"{base_url}/0"
            _redis_pool_db0 = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20,  # 4 workers × 5 connections
            )
            logger.info(f"Initialized shared Redis pool for database /0 (tools) at {redis_url}")
        return _redis_pool_db0

    elif database == 1:
        # Database /1: Service API tokens
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

    elif database == 2:
        # Database /2: File metadata
        if _redis_pool_db2 is None:
            # Parse base Redis URL and force database /2
            base_url = os.getenv("REDIS_URL", "redis://redis:6379/0").rsplit("/", 1)[0]
            redis_url = f"{base_url}/2"
            _redis_pool_db2 = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20,  # 4 workers × 5 connections
            )
            logger.info(f"Initialized shared Redis pool for database /2 (files) at {redis_url}")
        return _redis_pool_db2

    else:
        raise ValueError(f"Unsupported Redis database: {database}. Use 0 (tools), 1 (tokens), or 2 (files).")


async def close_redis_clients():
    """
    Close all Redis connection pools.

    Call this during service shutdown to gracefully close connections.
    """
    global _redis_pool_db0, _redis_pool_db1, _redis_pool_db2

    if _redis_pool_db0:
        await _redis_pool_db0.close()
        logger.info("Closed Redis connection pool for database /0 (tools)")
        _redis_pool_db0 = None

    if _redis_pool_db1:
        await _redis_pool_db1.close()
        logger.info("Closed Redis connection pool for database /1 (service tokens)")
        _redis_pool_db1 = None

    if _redis_pool_db2:
        await _redis_pool_db2.close()
        logger.info("Closed Redis connection pool for database /2 (files)")
        _redis_pool_db2 = None


# Convenience functions for common use cases
async def get_tools_redis_client() -> redis.Redis:
    """Get Redis client for tool configurations (database /0)."""
    return await get_redis_client(database=0)


async def get_tokens_redis_client() -> redis.Redis:
    """Get Redis client for service API tokens (database /1)."""
    return await get_redis_client(database=1)


async def get_files_redis_client() -> redis.Redis:
    """Get Redis client for file metadata (database /2)."""
    return await get_redis_client(database=2)
