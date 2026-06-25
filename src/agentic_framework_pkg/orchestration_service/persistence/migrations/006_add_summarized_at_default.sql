-- ============================================================================
-- Migration 006: Add DEFAULT constraint to summarized_at
-- ============================================================================
-- Date: 2025-12-30
-- Purpose: Fix schema discrepancy where summarized_at has NOT NULL
--          but missing DEFAULT CURRENT_TIMESTAMP constraint
--
-- Background:
--   Similar to migration 005, the summarized_at column has NOT NULL
--   (from SQLAlchemy model) but missing DEFAULT constraint (migration file
--   only specified DEFAULT, not NOT NULL, leading to mismatch).
--
-- Impact:
--   - Any INSERT without explicit summarized_at value fails
--   - E2E tests fail (5 failures, 1 error)
--   - Context archiving functionality broken
--
-- Fix:
--   Add DEFAULT CURRENT_TIMESTAMP via ALTER TABLE
--
-- Related Migrations:
--   - 001_create_session_tables.sql: Original table (DEFAULT but no NOT NULL)
--   - 005_add_classification_tier_default.sql: Fixed classification_tier
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 1: Add DEFAULT constraint to existing column
-- ============================================================================

ALTER TABLE context_archives
ALTER COLUMN summarized_at SET DEFAULT CURRENT_TIMESTAMP;

-- ============================================================================
-- STEP 2: Backfill existing NULL values (defensive - shouldn't exist)
-- ============================================================================

DO $$
DECLARE
    null_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO null_count
    FROM context_archives
    WHERE summarized_at IS NULL;

    IF null_count > 0 THEN
        RAISE NOTICE 'Found % rows with NULL summarized_at, backfilling...', null_count;

        UPDATE context_archives
        SET summarized_at = CURRENT_TIMESTAMP
        WHERE summarized_at IS NULL;

        RAISE NOTICE 'Backfilled % rows with CURRENT_TIMESTAMP', null_count;
    ELSE
        RAISE NOTICE 'No NULL values found in summarized_at (expected)';
    END IF;
END $$;

-- ============================================================================
-- STEP 3: Verify constraint applied successfully
-- ============================================================================

DO $$
DECLARE
    default_value TEXT;
BEGIN
    -- Query pg_catalog to verify DEFAULT constraint
    SELECT pg_get_expr(adbin, adrelid) INTO default_value
    FROM pg_catalog.pg_attrdef d
    JOIN pg_catalog.pg_attribute a ON (a.attrelid, a.attnum) = (d.adrelid, d.adnum)
    JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
    WHERE c.relname = 'context_archives'
    AND a.attname = 'summarized_at';

    IF default_value IS NULL THEN
        RAISE EXCEPTION 'Failed to set DEFAULT constraint on summarized_at';
    ELSE
        RAISE NOTICE 'DEFAULT constraint verified: summarized_at = %', default_value;
    END IF;
END $$;

-- ============================================================================
-- STEP 4: Record migration in schema_migrations table
-- ============================================================================

INSERT INTO schema_migrations (migration_id, applied_at)
VALUES ('006_add_summarized_at_default', CURRENT_TIMESTAMP)
ON CONFLICT (migration_id) DO NOTHING;

COMMIT;

-- ============================================================================
-- Post-Migration Validation
-- ============================================================================

-- Display migration status
SELECT
    '✓ Migration 006 Applied Successfully' AS status,
    migration_id,
    applied_at
FROM schema_migrations
WHERE migration_id = '006_add_summarized_at_default';

-- Display updated column definition
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'context_archives'
AND column_name IN ('classification_tier', 'summarized_at')
ORDER BY column_name;
