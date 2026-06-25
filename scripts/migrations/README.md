# Database Migration Scripts

This directory contains database migration scripts for ADEPT Agentic Framework deployments.

## Available Migrations

### LangGraph 1.0.5 Checkpoints Schema Migration

**File**: `migrate_langgraph_1.0.5_checkpoints_schema.sh`

**Purpose**: Fix checkpoint schema mismatch caused by incomplete LangGraph 0.0.8 → 1.0.5 upgrade.

**Problem Resolved**:
```
Error: column "checkpoint_ns" does not exist
LINE 5:     checkpoint_ns,
            ^
```

**When to Run**:
- ✅ On existing ADEPT deployments that have the old checkpoints schema
- ✅ If you encounter `checkpoint_ns does not exist` errors
- ❌ NOT needed for fresh deployments (post-commit 026b7f1)

**What It Does**:
1. ✅ Creates full PostgreSQL database backup
2. ✅ Checks for existing checkpoint data (typically 0 rows)
3. ✅ Drops old checkpoint-related tables
4. ✅ Rebuilds orchestration service container
5. ✅ Verifies new 7-column JSONB schema created by LangGraph
6. ✅ Validates service health

**Schema Change**:
```
Old (LangGraph 0.0.8):
- 3 columns: thread_id (PK), checkpoint (BYTEA), metadata (BYTEA)
- Primary key: thread_id

New (LangGraph 1.0.5):
- 7 columns: thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
             type, checkpoint (JSONB), metadata (JSONB)
- Primary key: (thread_id, checkpoint_ns, checkpoint_id) - composite key
```

## Usage

### Prerequisites

1. **Pull latest code** from `feature-contextwindow-and-sessionmgmt-integration` branch:
   ```bash
   git pull origin feature-contextwindow-and-sessionmgmt-integration
   ```
   Ensure you have commit `026b7f1` or later (the code fix).

2. **Verify services are running**:
   ```bash
   docker ps | grep -E "(postgres|orchestration_service)"
   ```

3. **Run from project root**:
   ```bash
   cd /path/to/adept-agentic-framework-extended
   ```

### Running the Migration

```bash
# Make executable (if not already)
chmod +x scripts/migrations/migrate_langgraph_1.0.5_checkpoints_schema.sh

# Run migration
./scripts/migrations/migrate_langgraph_1.0.5_checkpoints_schema.sh
```

### Migration Output

The script provides colored output:
- 🔵 **[INFO]**: Informational messages
- 🟢 **[SUCCESS]**: Successful operations
- 🟡 **[WARNING]**: Warnings (review but may be expected)
- 🔴 **[ERROR]**: Errors (migration will stop)

### Expected Duration
- Total time: ~2-5 minutes
- Backup: 10-30 seconds
- Table drops: 5 seconds
- Container rebuild: 1-3 minutes
- Service startup: 30-60 seconds
- Verification: 10 seconds

## Safety Features

### Automatic Backups
- Full database backup created before any changes
- Location: `/tmp/adept_migration_backups/agentic_orchestrator_backup_TIMESTAMP.sql`
- Old schema exported for reference: `checkpoints_schema_old_TIMESTAMP.txt`

### Data Loss Check
- Script checks for existing checkpoint data
- Prompts for confirmation if data exists (rare)
- Typically 0 rows (checkpoints are ephemeral state)

### Rollback Procedure

If migration fails or causes issues:

```bash
# 1. Find your backup file
ls -lh /tmp/adept_migration_backups/

# 2. Restore database
docker exec -i postgres psql -U admin -d agentic_orchestrator < \
  /tmp/adept_migration_backups/agentic_orchestrator_backup_TIMESTAMP.sql

# 3. Restart orchestration service
docker restart orchestration_service

# 4. Check service health
docker logs orchestration_service --tail 50
```

## Verification

### Manual Verification After Migration

1. **Check new schema**:
   ```bash
   docker exec postgres psql -U admin -d agentic_orchestrator -c "\d checkpoints"
   ```
   Expected output:
   ```
                       Table "public.checkpoints"
           Column        | Type  | Collation | Nullable |   Default
   ----------------------+-------+-----------+----------+-------------
    thread_id            | text  |           | not null |
    checkpoint_ns        | text  |           | not null | ''::text
    checkpoint_id        | text  |           | not null |
    parent_checkpoint_id | text  |           |          |
    type                 | text  |           |          |
    checkpoint           | jsonb |           | not null |
    metadata             | jsonb |           | not null | '{}'::jsonb
   Indexes:
       "checkpoints_pkey" PRIMARY KEY, btree (thread_id, checkpoint_ns, checkpoint_id)
   ```

2. **Check service health**:
   ```bash
   docker exec orchestration_service curl -s http://localhost:8084/health
   ```
   Expected: `{"status":"ok"}`

3. **Test completion request** (via Streamlit or API):
   - Navigate to Streamlit interface
   - Create a new conversation
   - Send a simple message
   - Verify no `checkpoint_ns` errors in logs

## Troubleshooting

### Migration Script Errors

**Error**: `Code fix not present in legacy_persistence.py`
- **Cause**: Old code without the fix
- **Solution**:
  ```bash
  git pull origin feature-contextwindow-and-sessionmgmt-integration
  git log --oneline | grep "026b7f1"  # Verify commit present
  ```

**Error**: `PostgreSQL container 'postgres' is not running`
- **Cause**: Services not started
- **Solution**:
  ```bash
  make start
  # or
  ./scripts/quick-start-adept-and-subsystems.sh
  ```

**Error**: `Failed to rebuild orchestration service`
- **Cause**: Docker build issues
- **Solution**:
  ```bash
  docker logs orchestration_service
  make rebuild-orchestrator  # Try manual rebuild
  ```

### Post-Migration Issues

**Issue**: Service starts but health check fails
- **Check logs**: `docker logs orchestration_service --tail 100`
- **Check database**: `docker exec postgres psql -U admin -d agentic_orchestrator -c "\dt"`
- **Retry**: `docker restart orchestration_service`

**Issue**: checkpoint_ns errors still occur
- **Verify schema**: Run manual verification steps above
- **Check table exists**:
  ```bash
  docker exec postgres psql -U admin -d agentic_orchestrator -c "SELECT COUNT(*) FROM checkpoints;"
  ```
- **Re-run migration**: Script is idempotent (safe to run multiple times)

## Multiple Deployments

If you manage multiple ADEPT deployments:

1. **Test on non-production first**
2. **Run migration on each deployment**:
   ```bash
   # Deployment 1
   ssh user@deployment1.example.com
   cd /path/to/adept
   ./scripts/migrations/migrate_langgraph_1.0.5_checkpoints_schema.sh

   # Deployment 2
   ssh user@deployment2.example.com
   cd /path/to/adept
   ./scripts/migrations/migrate_langgraph_1.0.5_checkpoints_schema.sh
   ```
3. **Keep backup files** until all deployments verified

## FAQ

**Q: Is this migration destructive?**
A: Yes, it drops checkpoint tables, but:
- Full database backup created automatically
- Checkpoints table typically has 0 rows (ephemeral state)
- Easily rolled back if needed

**Q: Do I need to run this on fresh deployments?**
A: No. Fresh clones after commit 026b7f1 will have the correct schema automatically.

**Q: Can I run this script multiple times?**
A: Yes. The script uses `DROP TABLE IF EXISTS` and is idempotent. Safe to re-run.

**Q: Will this affect user data (conversations, assistants)?**
A: No. Only checkpoint tables are affected. User data in `assistants`, `threads`, `runs`, etc. is preserved.

**Q: How long is downtime?**
A: ~2-5 minutes while orchestration service rebuilds. Other services remain available.

**Q: What if I have custom checkpoint data?**
A: The script checks row count and prompts for confirmation. You can cancel if needed.

## Related Documentation

- **Bugfix Commit**: `026b7f1` - Remove checkpoints table creation from init_db()
- **Root Cause Analysis**: See Plan Mode document: `~/.claude/plans/majestic-plotting-yao.md`
- **Session 32 Documentation**: `docs/implementation-plans/SESSION_32_*.md`
- **LangGraph Migration Guide**: `docs/LANGGRAPH_1.0.5_MIGRATION.md` (if exists)

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review orchestration service logs: `docker logs orchestration_service`
3. Review database schema: `docker exec postgres psql -U admin -d agentic_orchestrator -c "\d checkpoints"`
4. Create GitHub issue with:
   - Migration output
   - Service logs
   - Database schema output
   - Backup timestamp (for recovery assistance)
