-- Migration: 002_fix_tool_outputs_schema.sql
-- Purpose: Recreate tool_outputs table with Phase 1 schema (UUID primary key)
-- Author: Session 32 Phase 1 Completion
-- Date: 2025-12-30
--
-- This migration fixes the tool_outputs table schema mismatch between:
-- - SQLAlchemy models (expect UUID primary key)
-- - E2E tests (expect UUID primary key)
-- - Existing database table (has composite primary key)
--
-- Strategy: Rename old table, create new table with correct schema

-- ============================================================================
-- PART 1: Backup existing tool_outputs table
-- ============================================================================

-- Rename existing table for backup (preserves existing data)
ALTER TABLE IF EXISTS tool_outputs RENAME TO tool_outputs_legacy_backup;

-- Rename indexes (they'll be recreated on new table)
ALTER INDEX IF EXISTS tool_outputs_pkey RENAME TO tool_outputs_legacy_backup_pkey;
ALTER INDEX IF EXISTS idx_tool_outputs_created RENAME TO idx_tool_outputs_legacy_backup_created;
ALTER INDEX IF EXISTS idx_tool_outputs_message RENAME TO idx_tool_outputs_legacy_backup_message;
ALTER INDEX IF EXISTS idx_tool_outputs_retention RENAME TO idx_tool_outputs_legacy_backup_retention;
ALTER INDEX IF EXISTS idx_tool_outputs_session RENAME TO idx_tool_outputs_legacy_backup_session;
ALTER INDEX IF EXISTS idx_tool_outputs_thread RENAME TO idx_tool_outputs_legacy_backup_thread;

-- Drop trigger from old table (will be recreated on new table)
DROP TRIGGER IF EXISTS on_tool_output_orphaned ON tool_outputs_legacy_backup;

-- ============================================================================
-- PART 2: Create new tool_outputs table with correct schema
-- ============================================================================

CREATE TABLE tool_outputs (
    -- Primary key (UUID for E2E tests and models)
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Tool call identification
    tool_call_id VARCHAR NOT NULL,
    tool_name VARCHAR,

    -- Link to session_messages (for orphaning detection)
    message_id UUID,  -- No FK constraint due to partitioning (see migration 001)

    -- Tool output data
    full_output JSONB,
    output_size INTEGER,

    -- Retention management
    retention_status VARCHAR NOT NULL DEFAULT 'active',  -- active, orphaned, deleted

    -- Session identifiers (for multi-tier sessions)
    session_id VARCHAR,
    mcp_session_id VARCHAR,
    thread_id VARCHAR,
    checkpoint_id VARCHAR,

    -- Metadata
    output_sequence INTEGER,

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- PART 3: Create indexes for performance
-- ============================================================================

CREATE INDEX idx_tool_outputs_message_id ON tool_outputs(message_id);
CREATE INDEX idx_tool_outputs_retention_status ON tool_outputs(retention_status);
CREATE INDEX idx_tool_outputs_created_at ON tool_outputs(created_at);
CREATE INDEX idx_tool_outputs_session_id ON tool_outputs(session_id);
CREATE INDEX idx_tool_outputs_thread_id ON tool_outputs(thread_id);
CREATE INDEX idx_tool_outputs_tool_call_id ON tool_outputs(tool_call_id);

-- ============================================================================
-- PART 4: Recreate trigger for orphaning detection
-- ============================================================================

-- Trigger function already exists from migration 001, just create trigger
CREATE TRIGGER on_tool_output_orphaned
BEFORE UPDATE ON tool_outputs
FOR EACH ROW
WHEN (OLD.message_id IS DISTINCT FROM NEW.message_id)
EXECUTE FUNCTION mark_orphaned_tool_outputs();

-- ============================================================================
-- PART 5: Optional data migration (if needed)
-- ============================================================================

-- NOTE: Data migration is commented out by default since the old schema
-- is significantly different and may not have message_id populated.
-- Uncomment if you need to migrate existing data:

/*
INSERT INTO tool_outputs (
    tool_call_id,
    tool_name,
    message_id,
    full_output,
    output_size,
    retention_status,
    session_id,
    mcp_session_id,
    thread_id,
    checkpoint_id,
    output_sequence,
    created_at
)
SELECT
    COALESCE(tool_call_ids[1], 'unknown') as tool_call_id,  -- Extract first tool_call_id
    tool_name,
    message_id,
    full_output,
    output_size,
    COALESCE(retention_status, 'active') as retention_status,
    session_id,
    mcp_session_id,
    thread_id,
    checkpoint_id,
    output_sequence,
    created_at
FROM tool_outputs_legacy_backup
WHERE message_id IS NOT NULL;  -- Only migrate rows with valid message_id
*/

-- ============================================================================
-- PART 6: Verification
-- ============================================================================

-- Verify new table structure
DO $$
DECLARE
    col_count INTEGER;
    trigger_count INTEGER;
    index_count INTEGER;
BEGIN
    -- Check column count (should be 14)
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'tool_outputs' AND table_schema = 'public';

    IF col_count != 14 THEN
        RAISE EXCEPTION 'tool_outputs table should have 14 columns, found %', col_count;
    END IF;

    -- Check trigger exists
    SELECT COUNT(*) INTO trigger_count
    FROM information_schema.triggers
    WHERE trigger_name = 'on_tool_output_orphaned' AND event_object_table = 'tool_outputs';

    IF trigger_count != 1 THEN
        RAISE EXCEPTION 'on_tool_output_orphaned trigger should exist, found % triggers', trigger_count;
    END IF;

    -- Check indexes (should be at least 6)
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE tablename = 'tool_outputs' AND schemaname = 'public';

    IF index_count < 6 THEN
        RAISE EXCEPTION 'tool_outputs should have at least 6 indexes, found %', index_count;
    END IF;

    RAISE NOTICE 'Migration 002 completed successfully:';
    RAISE NOTICE '  - tool_outputs table recreated with % columns', col_count;
    RAISE NOTICE '  - on_tool_output_orphaned trigger created';
    RAISE NOTICE '  - % indexes created', index_count;
    RAISE NOTICE '  - Legacy table backed up as tool_outputs_legacy_backup';
END $$;
