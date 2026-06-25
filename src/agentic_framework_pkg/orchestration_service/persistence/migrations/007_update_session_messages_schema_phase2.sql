-- ============================================================================
-- Migration 007: Update session_messages Schema for Phase 2 ORM Compatibility
-- ============================================================================
-- Purpose: Add Phase 2 schema features to existing deployments
-- Applies to: Databases deployed before consolidated_initial_schema.sql
-- Author: Session 34 Phase 2 - ORM Schema Drift Fixes
-- Date: 2026-01-20
--
-- IMPORTANT: This migration is idempotent and safe to re-run
--
-- Changes:
-- 1. Add content_tsvector generated column (if not exists)
-- 2. Add GIN index for full-text search (if not exists)
-- 3. Update primary key to composite (id, created_at)
-- 4. Update unique constraint to include created_at
--
-- NOTE: Fresh deployments using consolidated_initial_schema.sql already have
-- these features and DO NOT need this migration.
-- ============================================================================

BEGIN;

-- Record migration start
INSERT INTO schema_migrations (migration_id, description)
VALUES ('007_update_session_messages_schema_phase2', 'Add Phase 2 schema features for ORM compatibility')
ON CONFLICT (migration_id) DO NOTHING;

-- ============================================================================
-- STEP 1: Add content_tsvector generated column (if not exists)
-- ============================================================================

DO $$
BEGIN
    -- Check if content_tsvector column exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'session_messages' AND column_name = 'content_tsvector'
    ) THEN
        -- Add content_tsvector as generated column
        RAISE NOTICE 'Adding content_tsvector generated column to session_messages';
        ALTER TABLE session_messages
            ADD COLUMN content_tsvector tsvector
            GENERATED ALWAYS AS (to_tsvector('english', COALESCE(message_content, ''))) STORED;
    ELSE
        RAISE NOTICE 'content_tsvector column already exists, skipping';
    END IF;
END $$;

-- ============================================================================
-- STEP 2: Add GIN indexes (if not exists)
-- ============================================================================

-- GIN index for full-text search
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_session_messages_content_fts'
    ) THEN
        RAISE NOTICE 'Creating GIN index idx_session_messages_content_fts';
        CREATE INDEX idx_session_messages_content_fts
            ON session_messages USING gin(content_tsvector);
    ELSE
        RAISE NOTICE 'Index idx_session_messages_content_fts already exists, skipping';
    END IF;
END $$;

-- GIN index for tool_call_ids array (should already exist from migration 001)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_session_messages_tool_calls'
    ) THEN
        RAISE NOTICE 'Creating GIN index idx_session_messages_tool_calls';
        CREATE INDEX idx_session_messages_tool_calls
            ON session_messages USING gin(tool_call_ids);
    ELSE
        RAISE NOTICE 'Index idx_session_messages_tool_calls already exists, skipping';
    END IF;
END $$;

-- ============================================================================
-- STEP 3: Update Primary Key to Composite (id, created_at)
-- ============================================================================
-- CRITICAL: Partitioned tables REQUIRE the partition key (created_at) in the
-- primary key. This is necessary for proper partition routing and integrity.
--
-- WARNING: This operation will temporarily lock the session_messages table.
-- For large tables (>100K rows), run during low-traffic window.
-- ============================================================================

DO $$
DECLARE
    partition_record RECORD;
BEGIN
    -- Check current primary key constraint
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'session_messages_pkey'
        AND contype = 'p'
        AND conrelid = 'session_messages'::regclass
        AND conkey = ARRAY[
            (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'session_messages'::regclass AND attname = 'id')
        ]
    ) THEN
        RAISE NOTICE 'Primary key is single-column (id), upgrading to composite (id, created_at)';

        -- Drop existing primary key on parent table
        ALTER TABLE session_messages DROP CONSTRAINT IF EXISTS session_messages_pkey;

        -- Drop primary key on all partition tables
        FOR partition_record IN
            SELECT inhrelid::regclass::text AS partition_name
            FROM pg_inherits
            WHERE inhparent = 'session_messages'::regclass
        LOOP
            EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I',
                partition_record.partition_name,
                partition_record.partition_name || '_pkey'
            );
        END LOOP;

        -- Add composite primary key to parent table
        ALTER TABLE session_messages ADD PRIMARY KEY (id, created_at);

        RAISE NOTICE 'Primary key updated to composite (id, created_at)';
    ELSIF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'session_messages_pkey'
        AND contype = 'p'
        AND conrelid = 'session_messages'::regclass
        AND array_length(conkey, 1) = 2
    ) THEN
        RAISE NOTICE 'Primary key is already composite, skipping';
    ELSE
        RAISE NOTICE 'No primary key found on session_messages, adding composite key';
        ALTER TABLE session_messages ADD PRIMARY KEY (id, created_at);
    END IF;
END $$;

-- ============================================================================
-- STEP 4: Update Unique Constraint to Include created_at
-- ============================================================================
-- CRITICAL: Unique constraints on partitioned tables MUST include the
-- partition key (created_at) to enable ON CONFLICT upsert operations.
--
-- This allows:
--   INSERT INTO session_messages (session_id, message_index, created_at, ...)
--   VALUES (?, ?, CURRENT_TIMESTAMP, ...)
--   ON CONFLICT (session_id, message_index, created_at) DO UPDATE ...
-- ============================================================================

DO $$
BEGIN
    -- Check if old unique constraint exists (without created_at)
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_session_message_idx'
        AND contype = 'u'
        AND conrelid = 'session_messages'::regclass
        AND array_length(conkey, 1) = 2
    ) THEN
        RAISE NOTICE 'Unique constraint uq_session_message_idx is 2-column, upgrading to 3-column';

        -- Drop old constraint
        ALTER TABLE session_messages DROP CONSTRAINT IF EXISTS uq_session_message_idx;

        -- Add new constraint with created_at
        ALTER TABLE session_messages
            ADD CONSTRAINT uq_session_message_idx
            UNIQUE (session_id, message_index, created_at);

        RAISE NOTICE 'Unique constraint updated to include created_at';
    ELSIF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_session_message_idx'
        AND contype = 'u'
        AND conrelid = 'session_messages'::regclass
        AND array_length(conkey, 1) = 3
    ) THEN
        RAISE NOTICE 'Unique constraint already includes created_at, skipping';
    ELSE
        RAISE NOTICE 'Unique constraint uq_session_message_idx not found, creating with created_at';
        ALTER TABLE session_messages
            ADD CONSTRAINT uq_session_message_idx
            UNIQUE (session_id, message_index, created_at);
    END IF;
END $$;

-- ============================================================================
-- STEP 5: Validation
-- ============================================================================

DO $$
DECLARE
    tsvector_exists BOOLEAN;
    content_fts_idx_exists BOOLEAN;
    tool_calls_idx_exists BOOLEAN;
    pk_is_composite BOOLEAN;
    uq_has_created_at BOOLEAN;
BEGIN
    -- Check content_tsvector column
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'session_messages' AND column_name = 'content_tsvector'
    ) INTO tsvector_exists;

    -- Check GIN indexes
    SELECT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_session_messages_content_fts'
    ) INTO content_fts_idx_exists;

    SELECT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_session_messages_tool_calls'
    ) INTO tool_calls_idx_exists;

    -- Check composite primary key
    SELECT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'session_messages_pkey'
        AND contype = 'p'
        AND conrelid = 'session_messages'::regclass
        AND array_length(conkey, 1) = 2
    ) INTO pk_is_composite;

    -- Check unique constraint includes created_at
    SELECT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_session_message_idx'
        AND contype = 'u'
        AND conrelid = 'session_messages'::regclass
        AND array_length(conkey, 1) = 3
    ) INTO uq_has_created_at;

    -- Report validation results
    RAISE NOTICE '=== Migration 007 Validation Results ===';
    RAISE NOTICE 'content_tsvector column exists: %', tsvector_exists;
    RAISE NOTICE 'idx_session_messages_content_fts index exists: %', content_fts_idx_exists;
    RAISE NOTICE 'idx_session_messages_tool_calls index exists: %', tool_calls_idx_exists;
    RAISE NOTICE 'Primary key is composite (id, created_at): %', pk_is_composite;
    RAISE NOTICE 'Unique constraint includes created_at: %', uq_has_created_at;

    -- Fail if validation doesn't pass
    IF NOT (tsvector_exists AND content_fts_idx_exists AND tool_calls_idx_exists AND pk_is_composite AND uq_has_created_at) THEN
        RAISE EXCEPTION 'Migration 007 validation failed. Check logs for details.';
    END IF;

    RAISE NOTICE '=== Migration 007 Complete ===';
END $$;

COMMIT;

-- ============================================================================
-- Post-Migration Notes
-- ============================================================================
-- 1. After running this migration, the SQLAlchemy ORM model
--    (session_models.py) will match the database schema exactly.
--
-- 2. Fresh deployments using consolidated_initial_schema.sql already have
--    these features and DO NOT need this migration.
--
-- 3. The ORM model now supports:
--    - Full-text search via content_tsvector (GIN indexed)
--    - Array containment queries via tool_call_ids (GIN indexed)
--    - ON CONFLICT upsert operations (unique constraint with created_at)
--    - Proper partition routing (composite PK with created_at)
--
-- 4. To verify migration success:
--    SELECT * FROM schema_migrations WHERE migration_id = '007_update_session_messages_schema_phase2';
--
-- 5. Performance impact:
--    - content_tsvector: Adds ~10% storage overhead for message_content
--    - GIN indexes: Add ~5MB per 10,000 messages
--    - Primary key update: One-time lock, <1 second for typical tables
--
-- 6. Rollback: NOT SUPPORTED. This migration makes structural changes
--    required for Phase 2 functionality. To rollback, restore from backup.
-- ============================================================================
