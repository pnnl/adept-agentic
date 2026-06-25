# Session Lifecycle Architecture

**Date**: 2025-12-27
**Status**: Active
**Version**: 1.0

---

## Overview

This document describes the lifecycle management of user sessions in the Agentic Framework, including state transitions, retention policies, and cleanup mechanisms.

---

## Session State Machine

### State Definitions

```
┌──────────┐
│  ACTIVE  │ ◄──────────────────────────┐
└────┬─────┘                            │
     │                                  │
     │ (inactive for N days)            │
     │ OR manual archive                │
     ▼                                  │
┌──────────┐                            │
│ ARCHIVED │                            │ (manual restore)
└────┬─────┘                            │
     │                                  │
     │ (retention policy expired)       │
     │ OR manual delete                 │
     ▼                                  │
┌─────────────────┐                     │
│ PENDING_DELETION│ ────────────────────┘ (grace period not expired + manual restore)
└────┬────────────┘
     │
     │ (grace period expired)
     │
     ▼
┌─────────┐
│ DELETED │ (hard delete from database)
└─────────┘
```

### State Descriptions

| State | Description | Visibility | Operations Allowed |
|-------|-------------|------------|-------------------|
| **ACTIVE** | Session is currently in use or recently used | Visible in UI | All operations (read, write, archive, delete) |
| **ARCHIVED** | Session marked as inactive but retained | Visible in "Archived" section | Read, export, restore, delete |
| **PENDING_DELETION** | Session marked for deletion with grace period | Visible in "Trash" section | Restore (within grace period), force delete |
| **DELETED** | Session permanently removed from database | Not visible | None (irreversible) |

### State Transitions

#### 1. ACTIVE → ARCHIVED

**Trigger Conditions**:
- Automatic: Session inactive for `SESSION_AUTO_ARCHIVE_THRESHOLD_DAYS` (default: 90 days)
- Manual: User clicks "Archive" button in UI
- API: `POST /v1/sessions/{session_id}/archive`

**Implementation**:
```python
# Automatic archiving by cleanup scheduler
async def _archive_inactive_sessions(session: AsyncSession) -> int:
    cutoff_date = datetime.utcnow() - timedelta(days=self.archive_inactive_days)

    stmt = (
        update(UserSession)
        .where(
            and_(
                UserSession.status == 'active',
                UserSession.last_active_at < cutoff_date
            )
        )
        .values(
            status='archived',
            archived_at=datetime.utcnow()
        )
    )

    await session.execute(stmt)
```

#### 2. ARCHIVED → PENDING_DELETION

**Trigger Conditions**:
- Automatic: Retention policy expired (see Retention Policies section)
- Manual: User clicks "Delete" button on archived session
- API: `DELETE /v1/sessions/{session_id}`

**Implementation**:
```python
# Automatic deletion by cleanup scheduler
async def _delete_expired_sessions(session: AsyncSession) -> int:
    for user_session in sessions_to_check:
        retention_days = RetentionPolicy.parse(user_session.retention_policy)
        expiry_date = user_session.created_at + timedelta(days=retention_days)

        if now > expiry_date:
            user_session.status = 'pending_deletion'
            user_session.deleted_at = now
```

#### 3. PENDING_DELETION → DELETED

**Trigger Conditions**:
- Automatic: Grace period expired (`SESSION_DELETION_GRACE_PERIOD_DAYS`, default: 30 days)
- Manual: User clicks "Delete Permanently" in UI
- API: `DELETE /v1/sessions/{session_id}?permanent=true`

**Cascade Behavior**:
```sql
-- Hard delete cascades to related tables
DELETE FROM user_sessions WHERE session_id = 'xxx' AND status = 'pending_deletion';

-- Cascades to:
-- 1. session_messages (ON DELETE CASCADE)
-- 2. tool_outputs.message_id set to NULL (ON DELETE SET NULL)
--    - Trigger marks tool_outputs as 'orphaned'
-- 3. context_archives (no FK, orphaned archives cleaned separately)
```

#### 4. PENDING_DELETION → ACTIVE (Restore)

**Trigger Conditions**:
- Manual: User clicks "Restore" button within grace period
- API: `POST /v1/sessions/{session_id}/restore`

**Implementation**:
```python
async def restore_session(session_id: str):
    async with get_async_session() as session:
        stmt = (
            update(UserSession)
            .where(
                and_(
                    UserSession.session_id == session_id,
                    UserSession.status == 'pending_deletion'
                )
            )
            .values(
                status='active',
                deleted_at=None
            )
        )

        result = await session.execute(stmt)

        if result.rowcount == 0:
            raise ValueError("Session not found or cannot be restored")
```

#### 5. ARCHIVED → ACTIVE (Restore)

**Trigger Conditions**:
- Manual: User clicks "Restore" button on archived session
- API: `POST /v1/sessions/{session_id}/restore`

**Implementation**: Same as PENDING_DELETION → ACTIVE, but checks for `status='archived'`

---

## Retention Policies

### Policy Format

Retention policies define how long a session is retained before automatic deletion:

| Format | Meaning | Days | Example Use Case |
|--------|---------|------|------------------|
| `indefinite` or `-1` | Never delete | -1 | Important research sessions |
| `30d` | 30 days | 30 | Short-term testing sessions |
| `90d` | 90 days | 90 | Standard project work |
| `3m` | 3 months | 90 | Quarterly project archives |
| `6m` | 6 months | 180 | Medium-term retention |
| `1y` | 1 year | 365 | Annual archives |
| `2y` | 2 years | 730 | Long-term compliance |

### Policy Application

**Default Policy**: Configurable via `SESSION_DEFAULT_RETENTION_POLICY` (default: `indefinite`)

**Per-Session Override**: Users can set custom retention policy per session:
```python
# Via API
PUT /v1/sessions/{session_id}
{
  "retention_policy": "6m"
}

# Via UI
Session Settings → Retention Policy → "6 months"
```

### Policy Evaluation

Retention policy is evaluated daily by the cleanup scheduler:

```python
class CleanupJobManager:
    async def _delete_expired_sessions(self, session: AsyncSession):
        now = datetime.utcnow()

        # Get all sessions with non-indefinite retention
        sessions = await session.execute(
            select(UserSession).where(
                UserSession.retention_policy != 'indefinite'
            )
        )

        for user_session in sessions:
            retention_days = RetentionPolicy.parse(user_session.retention_policy)

            if retention_days == -1:
                continue  # Skip indefinite retention

            # Calculate expiry date from creation date
            expiry_date = user_session.created_at + timedelta(days=retention_days)

            if now > expiry_date:
                # Mark for deletion (soft delete)
                user_session.status = 'pending_deletion'
                user_session.deleted_at = now
```

**Important**: Retention policy countdown starts from `created_at`, not `last_active_at`. This ensures predictable expiration dates.

---

## Cleanup Mechanisms

### Cleanup Scheduler

**Schedule**: Daily at 2 AM local time (configurable via APScheduler)

**Tasks**:
1. Delete orphaned tool outputs (retention_status='orphaned', older than grace period)
2. Archive inactive sessions (status='active', inactive for N days)
3. Soft delete expired sessions (retention policy expired)
4. Hard delete sessions past grace period (status='pending_deletion', older than grace period)

### Orphaned Tool Outputs Cleanup

**Problem**: When session_messages are deleted, tool_outputs FK is set to NULL, creating orphaned outputs that consume storage.

**Solution**: Database trigger + cleanup scheduler

#### Database Trigger

```sql
CREATE OR REPLACE FUNCTION mark_orphaned_tool_outputs()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.message_id IS NULL AND OLD.message_id IS NOT NULL THEN
        NEW.retention_status := 'orphaned';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER on_tool_output_orphaned
BEFORE UPDATE ON tool_outputs
FOR EACH ROW
WHEN (OLD.message_id IS DISTINCT FROM NEW.message_id)
EXECUTE FUNCTION mark_orphaned_tool_outputs();
```

#### Cleanup Implementation

```python
async def _cleanup_orphaned_tool_outputs(self, session: AsyncSession) -> int:
    cutoff_date = datetime.utcnow() - timedelta(days=self.orphan_grace_period_days)

    stmt = delete(ToolOutput).where(
        and_(
            ToolOutput.retention_status == 'orphaned',
            ToolOutput.created_at < cutoff_date
        )
    )

    result = await session.execute(stmt)
    return result.rowcount
```

**Grace Period**: Default 30 days (`SESSION_ORPHAN_GRACE_PERIOD_DAYS`)

**Rationale**: Provides buffer time for potential recovery or investigation before permanent deletion.

### Context Archives Cleanup

**Note**: Phase 1 does NOT implement context_archives cleanup. This will be addressed in Phase 3 (Context Window Management).

**Future Implementation**:
- When session is hard deleted, orphaned context_archives should be cleaned
- When summarization is re-run, old archives for the same message range should be replaced

---

## Database Partitioning

### session_messages Table Partitioning

**Strategy**: Monthly partitioning by `created_at` column

**Benefits**:
- **Performance**: Queries filter by date range scan only relevant partitions
- **Maintenance**: Drop old partitions instead of DELETE queries (faster)
- **Scalability**: Handles millions of messages without performance degradation

#### Partition Creation

**Initial Partitions** (created by migration script):
```sql
CREATE TABLE session_messages_2025_12
    PARTITION OF session_messages
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');

CREATE TABLE session_messages_2026_01
    PARTITION OF session_messages
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

-- ... 3 months ahead
```

**Manual Partition Creation**:
```sql
SELECT create_monthly_partition('2026-04-01'::DATE);
```

**Automated Partition Creation** (future enhancement):
- Cleanup scheduler should create next 3 months of partitions automatically
- Run at end of each month to ensure partitions exist ahead of time

#### Partition Maintenance

**Dropping Old Partitions**:
```sql
-- Drop partitions older than retention policy (e.g., 2 years)
DROP TABLE session_messages_2024_01;  -- January 2024
DROP TABLE session_messages_2024_02;  -- February 2024
```

**Best Practice**: Coordinate partition drops with retention policies to avoid orphaned data.

**Future Enhancement**: Cleanup scheduler should auto-drop partitions older than max retention policy.

---

## Full-Text Search

### Materialized tsvector Column

**Column Definition**:
```sql
ALTER TABLE session_messages ADD COLUMN content_tsvector tsvector
    GENERATED ALWAYS AS (to_tsvector('english', COALESCE(message_content, ''))) STORED;

CREATE INDEX idx_session_messages_content_fts
    ON session_messages USING gin(content_tsvector);
```

**Why Materialized**:
- Pre-computed tsvector eliminates on-the-fly tokenization overhead
- GIN index on materialized column is faster than functional index
- Storage cost is minimal compared to performance gain

### Search Query Patterns

**Basic Search**:
```sql
SELECT * FROM session_messages
WHERE content_tsvector @@ to_tsquery('english', 'python & code');
```

**Ranked Search**:
```sql
SELECT *, ts_rank(content_tsvector, query) AS rank
FROM session_messages,
     to_tsquery('english', 'machine & learning') AS query
WHERE content_tsvector @@ query
ORDER BY rank DESC
LIMIT 50;
```

**Phrase Search**:
```sql
SELECT * FROM session_messages
WHERE content_tsvector @@ phraseto_tsquery('english', 'deep learning model');
```

---

## Grace Periods

### Purpose

Grace periods provide a safety buffer before irreversible actions:

1. **Prevent Accidental Data Loss**: Users can recover from mistakes
2. **Allow Investigation**: Admins can investigate issues before permanent deletion
3. **Compliance**: Meet data retention regulations requiring recovery windows

### Grace Period Types

| Type | Default | Environment Variable | Purpose |
|------|---------|---------------------|---------|
| **Deletion Grace** | 30 days | `SESSION_DELETION_GRACE_PERIOD_DAYS` | Buffer before hard delete |
| **Orphan Grace** | 30 days | `SESSION_ORPHAN_GRACE_PERIOD_DAYS` | Buffer before orphaned tool_outputs deleted |

### Implementation Example

```python
class CleanupJobManager:
    def __init__(
        self,
        orphan_grace_period_days: int = 30,
        deletion_grace_period_days: int = 30,
        archive_inactive_days: int = 90
    ):
        self.orphan_grace_period_days = orphan_grace_period_days
        self.deletion_grace_period_days = deletion_grace_period_days
        self.archive_inactive_days = archive_inactive_days
```

---

## Lifecycle Operations API

### Session CRUD Endpoints (Phase 4)

```
GET    /v1/sessions                    # List sessions with pagination/filters
GET    /v1/sessions/{session_id}       # Get session metadata
PUT    /v1/sessions/{session_id}       # Update session (title, tags, retention_policy)
POST   /v1/sessions/{session_id}/archive   # Archive session
POST   /v1/sessions/{session_id}/restore   # Restore archived/pending_deletion session
DELETE /v1/sessions/{session_id}       # Soft delete (move to pending_deletion)
DELETE /v1/sessions/{session_id}?permanent=true  # Hard delete (force immediate)
```

### Lifecycle State Queries

```python
# Get active sessions
GET /v1/sessions?status=active

# Get archived sessions
GET /v1/sessions?status=archived

# Get trash (pending deletion)
GET /v1/sessions?status=pending_deletion

# Get sessions expiring soon (within 7 days)
GET /v1/sessions?expiring_within=7d
```

---

## Monitoring and Metrics

### Key Metrics to Track

1. **Session Counts by Status**:
   ```sql
   SELECT status, COUNT(*) FROM user_sessions GROUP BY status;
   ```

2. **Orphaned Tool Outputs**:
   ```sql
   SELECT retention_status, COUNT(*) FROM tool_outputs GROUP BY retention_status;
   ```

3. **Cleanup Job Performance**:
   - Orphans deleted per run
   - Sessions archived per run
   - Sessions deleted per run
   - Cleanup job duration

4. **Storage Growth**:
   ```sql
   SELECT
       pg_size_pretty(pg_total_relation_size('session_messages')) AS messages_size,
       pg_size_pretty(pg_total_relation_size('tool_outputs')) AS outputs_size,
       pg_size_pretty(pg_total_relation_size('user_sessions')) AS sessions_size;
   ```

### Alerting Thresholds (Recommendations)

- **Orphaned Tool Outputs** > 10,000: Investigate cleanup scheduler
- **Pending Deletion Sessions** > 1,000: Possible grace period too long
- **Cleanup Job Duration** > 5 minutes: Index or query optimization needed
- **Partition Size** > 10 GB: Consider more frequent partitions (weekly instead of monthly)

---

## Best Practices

### For Users

1. **Set Appropriate Retention Policies**: Use shorter retention (30d, 90d) for test sessions, indefinite for important research
2. **Regular Archiving**: Archive completed projects to keep active session list manageable
3. **Restore Within Grace Period**: If you accidentally delete, restore within 30 days
4. **Export Before Deletion**: Export sessions to JSON/Jupyter before manual deletion

### For Administrators

1. **Monitor Cleanup Scheduler**: Ensure daily cleanup jobs are running successfully
2. **Partition Maintenance**: Create next 3 months of partitions at month-end
3. **Index Maintenance**: Run VACUUM ANALYZE monthly on session_messages
4. **Backup Strategy**: Backup session_messages table before dropping old partitions
5. **Grace Period Tuning**: Adjust grace periods based on user feedback and storage constraints

### For Developers

1. **Cascade Awareness**: Understand FK cascade rules when deleting sessions
2. **Transaction Safety**: Wrap multi-table operations in transactions
3. **Async Context Managers**: Always use `async with get_async_session()` for proper cleanup
4. **Error Handling**: Handle `IntegrityError` for FK violations gracefully
5. **Testing**: Test state transitions thoroughly, including error paths

---

## Future Enhancements

### Phase 2-7 Additions

- **Session Sharing**: Allow users to share sessions with other users (read-only or collaborative)
- **Session Branching**: Fork sessions to create alternate conversation paths
- **Auto-Tagging**: LLM-based automatic tag extraction from conversation content
- **Smart Archiving**: ML-based prediction of which sessions to archive
- **Cost Alerts**: Notify users when session costs exceed thresholds
- **Conversation Summarization**: Auto-generate session titles and summaries

### Operational Improvements

- **Auto-Partition Management**: Cleanup scheduler creates/drops partitions automatically
- **Backup Integration**: Auto-backup sessions before hard deletion
- **Metrics Dashboard**: Real-time monitoring of session lifecycle metrics
- **Audit Logging**: Track all lifecycle state transitions for compliance
- **Bulk Operations**: Archive/delete/restore multiple sessions in batch

---

## References

- Implementation Plan: `docs/implementation-plans/SESSION_CONTEXT_INTEGRATION_PROPOSAL.md`
- Phase 1 Guide: `docs/guides/SESSION_MANAGEMENT_PHASE1.md`
- Migration Script: `src/agentic_framework_pkg/orchestration_service/persistence/migrations/001_create_session_tables.sql`
- Cleanup Scheduler: `src/agentic_framework_pkg/orchestration_service/jobs/cleanup_scheduler.py`
- Retention Policy Parser: `src/agentic_framework_pkg/orchestration_service/sessions/retention_policy.py`

---

**Document Version**: 1.0
**Last Updated**: 2025-12-27
**Status**: Active (Phase 1 Complete)
