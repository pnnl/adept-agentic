"""
Cleanup job scheduler for orphaned tool outputs and expired sessions.

Runs daily at 2 AM to:
1. Detect orphaned tool_outputs (retention_status='orphaned')
2. Delete tool_outputs older than grace period (30 days default)
3. Delete sessions past retention policy
4. Archive inactive sessions

Usage:
    from orchestration_service.jobs.cleanup_scheduler import start_cleanup_scheduler

    # At service startup
    await start_cleanup_scheduler()

    # At service shutdown
    await stop_cleanup_scheduler()
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.session_models import UserSession, SessionMessage, ToolOutput
from ..sessions.retention_policy import RetentionPolicy
from ...logger_config import get_logger

logger = get_logger(__name__)


class CleanupJobManager:
    """
    Manages scheduled cleanup jobs for session management.

    Runs daily cleanup tasks:
    - Delete orphaned tool outputs after grace period
    - Delete expired sessions based on retention policy
    - Archive inactive sessions
    """

    def __init__(
        self,
        orphan_grace_period_days: Optional[int] = None,
        deletion_grace_period_days: Optional[int] = None,
        archive_inactive_days: Optional[int] = None,
    ):
        """
        Initialize cleanup job manager.

        Args:
            orphan_grace_period_days: Days before deleting orphaned tool_outputs
                                     (default: 30, from env SESSION_ORPHAN_GRACE_PERIOD_DAYS)
            deletion_grace_period_days: Days before hard delete of pending_deletion sessions
                                       (default: 30, from env SESSION_DELETION_GRACE_PERIOD_DAYS)
            archive_inactive_days: Days of inactivity before auto-archiving sessions
                                  (default: 90, from env SESSION_AUTO_ARCHIVE_THRESHOLD_DAYS)
        """
        self.scheduler = AsyncIOScheduler()

        # Load configuration from environment or use defaults
        self.orphan_grace_period_days = (
            orphan_grace_period_days
            or int(os.getenv("SESSION_ORPHAN_GRACE_PERIOD_DAYS", "30"))
        )
        self.deletion_grace_period_days = (
            deletion_grace_period_days
            or int(os.getenv("SESSION_DELETION_GRACE_PERIOD_DAYS", "30"))
        )
        self.archive_inactive_days = (
            archive_inactive_days
            or int(os.getenv("SESSION_AUTO_ARCHIVE_THRESHOLD_DAYS", "90"))
        )

        # Metrics
        self.last_run: Optional[datetime] = None
        self.orphans_deleted: int = 0
        self.sessions_archived: int = 0
        self.sessions_deleted: int = 0

    def start(self):
        """
        Start the cleanup job scheduler.

        Schedules daily job at 2 AM local time.
        """
        # Schedule daily cleanup at 2 AM
        self.scheduler.add_job(
            self.run_cleanup,
            trigger=CronTrigger(hour=2, minute=0),
            id="daily_cleanup",
            name="Session and Tool Output Cleanup",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info(
            "Cleanup job scheduler started (daily at 2 AM). "
            f"Orphan grace period: {self.orphan_grace_period_days}d, "
            f"Deletion grace period: {self.deletion_grace_period_days}d, "
            f"Archive threshold: {self.archive_inactive_days}d"
        )

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown(wait=True)
        logger.info("Cleanup job scheduler stopped")

    async def run_cleanup(self):
        """
        Run all cleanup tasks.

        Called by scheduler or can be invoked manually for testing.
        """
        start_time = datetime.utcnow()
        logger.info("Starting cleanup job")

        try:
            # Import here to avoid circular dependency and heavy imports
            from ..persistence.checkpointing import get_async_session

            async with get_async_session() as session:
                # Task 1: Delete orphaned tool outputs
                orphans_deleted = await self._cleanup_orphaned_tool_outputs(session)
                self.orphans_deleted += orphans_deleted

                # Task 2: Archive inactive sessions
                archived = await self._archive_inactive_sessions(session)
                self.sessions_archived += archived

                # Task 3: Delete expired sessions
                deleted = await self._delete_expired_sessions(session)
                self.sessions_deleted += deleted

                await session.commit()

            duration = (datetime.utcnow() - start_time).total_seconds()
            self.last_run = datetime.utcnow()

            logger.info(
                f"Cleanup job completed in {duration:.2f}s: "
                f"{orphans_deleted} orphans deleted, "
                f"{archived} sessions archived, "
                f"{deleted} sessions deleted"
            )

        except Exception as e:
            logger.error(f"Cleanup job failed: {e}", exc_info=True)
            raise

    async def _cleanup_orphaned_tool_outputs(self, session: AsyncSession) -> int:
        """
        Delete orphaned tool outputs older than grace period.

        Args:
            session: Database session

        Returns:
            Number of tool outputs deleted
        """
        cutoff_date = datetime.utcnow() - timedelta(days=self.orphan_grace_period_days)

        # Find orphaned tool outputs older than grace period
        stmt = (
            delete(ToolOutput)
            .where(
                and_(
                    ToolOutput.retention_status == "orphaned",
                    ToolOutput.created_at < cutoff_date,
                )
            )
            .returning(ToolOutput.id)
        )

        result = await session.execute(stmt)
        deleted_ids = result.scalars().all()

        count = len(deleted_ids)
        if count > 0:
            logger.info(
                f"Deleted {count} orphaned tool outputs "
                f"(older than {cutoff_date})"
            )

        return count

    async def _archive_inactive_sessions(self, session: AsyncSession) -> int:
        """
        Archive sessions inactive for specified period.

        Args:
            session: Database session

        Returns:
            Number of sessions archived
        """
        cutoff_date = datetime.utcnow() - timedelta(days=self.archive_inactive_days)

        # Archive active sessions inactive for too long
        # NOTE: Archiving is independent of retention policy - even indefinite
        # retention sessions can be archived when inactive (archiving != deletion)
        stmt = (
            update(UserSession)
            .where(
                and_(
                    UserSession.status == "active",
                    UserSession.last_active_at < cutoff_date,
                )
            )
            .values(status="archived", archived_at=datetime.utcnow())
            .returning(UserSession.session_id)
        )

        result = await session.execute(stmt)
        archived_ids = result.scalars().all()

        count = len(archived_ids)
        if count > 0:
            logger.info(
                f"Archived {count} inactive sessions "
                f"(last active before {cutoff_date})"
            )

        return count

    async def _delete_expired_sessions(self, session: AsyncSession) -> int:
        """
        Delete sessions past their retention policy.

        Args:
            session: Database session

        Returns:
            Number of sessions deleted
        """
        now = datetime.utcnow()

        # Get all sessions with non-indefinite retention policies
        stmt = select(UserSession).where(
            and_(
                UserSession.status.in_(["active", "archived"]),
                UserSession.retention_policy != "indefinite",
            )
        )

        result = await session.execute(stmt)
        sessions_to_check = result.scalars().all()

        expired_count = 0

        for user_session in sessions_to_check:
            try:
                # Parse retention policy
                retention_days = RetentionPolicy.parse(user_session.retention_policy)

                if retention_days == -1:
                    continue  # Indefinite retention

                # Check if session has expired
                expiry_date = user_session.created_at + timedelta(days=retention_days)

                if now > expiry_date:
                    # Mark for deletion (soft delete)
                    user_session.status = "pending_deletion"
                    user_session.deleted_at = now
                    expired_count += 1

            except Exception as e:
                logger.warning(
                    f"Failed to process retention for session {user_session.session_id}: {e}"
                )

        if expired_count > 0:
            logger.info(
                f"Marked {expired_count} sessions for deletion (retention policy expired)"
            )

        # Hard delete sessions in pending_deletion state past grace period
        grace_cutoff = now - timedelta(days=self.deletion_grace_period_days)

        hard_delete_stmt = (
            delete(UserSession)
            .where(
                and_(
                    UserSession.status == "pending_deletion",
                    UserSession.deleted_at < grace_cutoff,
                )
            )
            .returning(UserSession.session_id)
        )

        result = await session.execute(hard_delete_stmt)
        deleted_ids = result.scalars().all()

        hard_deleted_count = len(deleted_ids)
        if hard_deleted_count > 0:
            logger.info(
                f"Hard deleted {hard_deleted_count} sessions "
                f"(past grace period of {self.deletion_grace_period_days} days)"
            )

        return expired_count + hard_deleted_count


# Global instance
_cleanup_manager: Optional[CleanupJobManager] = None


def get_cleanup_manager() -> CleanupJobManager:
    """Get or create global cleanup manager instance."""
    global _cleanup_manager
    if _cleanup_manager is None:
        _cleanup_manager = CleanupJobManager()
    return _cleanup_manager


async def start_cleanup_scheduler():
    """
    Start the cleanup scheduler (call at service startup).

    This function should be called during the orchestration service
    startup lifecycle to enable automated cleanup jobs.
    """
    manager = get_cleanup_manager()
    manager.start()
    logger.info("Cleanup scheduler started")


async def stop_cleanup_scheduler():
    """
    Stop the cleanup scheduler (call at service shutdown).

    This function should be called during the orchestration service
    shutdown lifecycle to gracefully stop the scheduler.
    """
    manager = get_cleanup_manager()
    manager.stop()
    logger.info("Cleanup scheduler stopped")
