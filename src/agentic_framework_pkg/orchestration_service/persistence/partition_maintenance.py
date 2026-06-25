"""
Partition maintenance for session_messages table.

The session_messages table uses PostgreSQL RANGE partitioning by created_at
(monthly). This module ensures partitions exist ahead of the current date
so INSERT operations never fail with "no partition found for row".

Strategy:
  1. Startup hook: create current + 6 months ahead
  2. Background task: verify every 24h (handles long-running instances)
"""

import asyncio
from datetime import date, timedelta
from typing import List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger_config import get_logger
from .checkpointing import get_async_session

logger = get_logger(__name__)

_MONTHS_AHEAD = 6
_BACKGROUND_INTERVAL_SECONDS = 86400  # 24 hours
_STARTUP_RETRY_ATTEMPTS = 3
_STARTUP_RETRY_DELAY = 5.0


async def ensure_partitions_exist(months_ahead: int = _MONTHS_AHEAD) -> List[str]:
    """Create session_messages partitions for current month + N months ahead.

    Idempotent: safe to call multiple times (create_monthly_partition
    checks IF NOT EXISTS internally).

    Returns:
        List of partition names that were newly created (empty if all existed).
    """
    created = []
    today = date.today()

    async with get_async_session() as session:
        for i in range(months_ahead + 1):
            target_date = today.replace(day=1) + timedelta(days=32 * i)
            target_date = target_date.replace(day=1)
            try:
                result = await session.execute(
                    text("SELECT create_monthly_partition(:target_date)"),
                    {"target_date": target_date},
                )
                row = result.scalar()
                if row and "created successfully" in str(row):
                    created.append(str(row).split(" ")[0])
                await session.commit()
            except Exception as e:
                await session.rollback()
                if "already exists" in str(e).lower():
                    continue
                logger.warning(
                    f"[PARTITION_MAINT] Error creating partition for {target_date}: {e}"
                )

    return created


async def _partition_maintenance_loop() -> None:
    """Background task that ensures partitions exist every 24 hours."""
    while True:
        try:
            await asyncio.sleep(_BACKGROUND_INTERVAL_SECONDS)
            created = await ensure_partitions_exist(_MONTHS_AHEAD)
            if created:
                logger.info(
                    f"[PARTITION_MAINT] Background check created {len(created)} "
                    f"new partitions: {created}"
                )
            else:
                logger.debug("[PARTITION_MAINT] Background check: all partitions exist")
        except asyncio.CancelledError:
            logger.info("[PARTITION_MAINT] Background maintenance task cancelled")
            return
        except Exception as e:
            logger.error(f"[PARTITION_MAINT] Background maintenance error: {e}")
            await asyncio.sleep(60)


async def startup_ensure_partitions() -> None:
    """Startup hook with retry logic. Called during service initialization."""
    for attempt in range(1, _STARTUP_RETRY_ATTEMPTS + 1):
        try:
            created = await ensure_partitions_exist(_MONTHS_AHEAD)
            if created:
                logger.info(
                    f"[PARTITION_MAINT] Startup created {len(created)} partitions: {created}"
                )
            else:
                logger.info("[PARTITION_MAINT] Startup: all partitions already exist")
            return
        except Exception as e:
            if attempt < _STARTUP_RETRY_ATTEMPTS:
                logger.warning(
                    f"[PARTITION_MAINT] Startup attempt {attempt}/{_STARTUP_RETRY_ATTEMPTS} "
                    f"failed: {e}. Retrying in {_STARTUP_RETRY_DELAY}s..."
                )
                await asyncio.sleep(_STARTUP_RETRY_DELAY)
            else:
                logger.error(
                    f"[PARTITION_MAINT] All {_STARTUP_RETRY_ATTEMPTS} startup attempts "
                    f"failed. Service continues but partition gap may cause INSERT failures: {e}"
                )
