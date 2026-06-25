"""
This module provides a custom Redis-backed checkpointer for LangGraph.

DEPRECATED: This module is no longer used. The framework has transitioned
to using the `AsyncPostgresSaver` in `orchestration_service/persistence.py`
for durable, ACID-compliant state management. This file is retained for
historical context regarding the previous Redis-based implementation.
"""

import os
from typing import Dict, Any, Optional, Tuple
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

class CustomRedisCheckpointer(AsyncRedisSaver):
    """
    A custom Redis checkpointer that sanitizes the checkpoint before saving.
    It removes the 'full_tool_outputs' field to avoid persisting large,
    transient data like base64 plot strings to the database.
    """
    async def put(self, config: dict, checkpoint: dict, metadata: dict) -> None:
        # Before writing to Redis, remove the large, transient data.
        checkpoint_copy = checkpoint.copy()
        if "full_tool_outputs" in checkpoint_copy.get("channel_values", {}):
            del checkpoint_copy["channel_values"]["full_tool_outputs"]
        
        await super().put(config, checkpoint_copy, metadata)

    async def get_tuple(self, config: dict) -> Optional[Tuple]:
        # Get the saved checkpoint from Redis.
        saved_tuple = await super().get_tuple(config)
        if saved_tuple:
            checkpoint = saved_tuple.checkpoint
            # Add back the empty field to conform to the AgentState schema upon loading.
            if "full_tool_outputs" not in checkpoint.get("channel_values", {}):
                checkpoint["channel_values"]["full_tool_outputs"] = []
            return saved_tuple
        return None

async def get_redis_checkpointer() -> AsyncRedisSaver:
    """
    Factory function to create and configure the RedisSaver from `langgraph-checkpoint-redis`.
    This function provides a Redis-backed checkpointer for LangGraph agents.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    checkpointer = AsyncRedisSaver(redis_url)
    await checkpointer.asetup()
    return checkpointer