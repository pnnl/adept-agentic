-- ============================================================================
-- Migration 005: Add DEFAULT constraint to classification_tier
-- ============================================================================
-- Date: 2025-12-30
-- Purpose: Fix schema discrepancy where classification_tier has NOT NULL
--          but missing DEFAULT 'summarize' constraint
--
-- Background:
--   The context_archives table was created with NOT NULL constraint on
--   classification_tier, but the DEFAULT 'summarize' constraint was added
--   to migration 001 file AFTER initial deployment. Since the consolidated
--   schema uses CREATE TABLE IF NOT EXISTS, existing tables don't get updated.
--
-- Impact:
--   - Any INSERT without explicit classification_tier value fails
--   - E2E tests fail (5 failures, 1 error)
--   - Active Context Layer functionality broken
--
-- Fix:
--   Add DEFAULT constraint via ALTER TABLE (works on existing tables)
--
-- Related Migrations:
--   - 001_create_session_tables.sql: Original table creation
--   - consolidated_initial_schema.sql: Includes this DEFAULT in fresh deploys
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 1: Add DEFAULT constraint to existing column
-- ============================================================================

ALTER TABLE context_archives
ALTER COLUMN classification_tier SET DEFAULT 'summarize';

-- ============================================================================
-- STEP 2: Backfill existing NULL values (defensive - shouldn't exist)
-- ============================================================================

-- Check if any NULL values exist (should be impossible with NOT NULL constraint)
-- But we'll handle it defensively in case of data corruption
DO $$
DECLARE
    null_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO null_count
    FROM context_archives
    WHERE classification_tier IS NULL;

    IF null_count > 0 THEN
        RAISE NOTICE 'Found % rows with NULL classification_tier, backfilling...', null_count;

        UPDATE context_archives
        SET classification_tier = 'summarize'
        WHERE classification_tier IS NULL;

        RAISE NOTICE 'Backfilled % rows with default value', null_count;
    ELSE
        RAISE NOTICE 'No NULL values found in classification_tier (expected)';
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
    AND a.attname = 'classification_tier';

    IF default_value IS NULL THEN
        RAISE EXCEPTION 'Failed to set DEFAULT constraint on classification_tier';
    ELSE
        RAISE NOTICE 'DEFAULT constraint verified: classification_tier = %', default_value;
    END IF;
END $$;

-- ============================================================================
-- STEP 4: Record migration in schema_migrations table
-- ============================================================================

INSERT INTO schema_migrations (migration_id, applied_at)
VALUES ('005_add_classification_tier_default', CURRENT_TIMESTAMP)
ON CONFLICT (migration_id) DO NOTHING;

COMMIT;

-- ============================================================================
-- Post-Migration Validation
-- ============================================================================

-- Display migration status
SELECT
    '✓ Migration 005 Applied Successfully' AS status,
    migration_id,
    applied_at
FROM schema_migrations
WHERE migration_id = '005_add_classification_tier_default';

-- Display updated column definition
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'context_archives'
AND column_name = 'classification_tier';
