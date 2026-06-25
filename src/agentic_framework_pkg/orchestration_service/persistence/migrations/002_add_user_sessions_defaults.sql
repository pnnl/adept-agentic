-- Migration: 002_add_user_sessions_defaults.sql
-- Purpose: Add missing SQL-level defaults to user_sessions table
-- Author: Session 33 Phase 2
-- Date: 2026-01-17
--
-- Background:
-- The user_sessions table was created via SQLAlchemy's metadata.create_all()
-- which bypasses SQL DEFAULT clauses. This migration adds the missing defaults
-- to align the database schema with:
-- 1. The ORM model (session_models.py)
-- 2. The original migration 001 specification
-- 3. User requirements for ORM idempotency
--
-- Impact: Non-destructive, only adds DEFAULT clauses (no data changes)
-- Idempotent: Safe to run multiple times

-- ============================================================================
-- Add SQL-level defaults to user_sessions table
-- ============================================================================

-- Session metadata defaults
ALTER TABLE user_sessions
    ALTER COLUMN session_type SET DEFAULT 'response';

ALTER TABLE user_sessions
    ALTER COLUMN status SET DEFAULT 'active';

-- Timestamp defaults
ALTER TABLE user_sessions
    ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE user_sessions
    ALTER COLUMN last_active_at SET DEFAULT CURRENT_TIMESTAMP;

-- Cost tracking defaults
ALTER TABLE user_sessions
    ALTER COLUMN total_tokens SET DEFAULT 0;

ALTER TABLE user_sessions
    ALTER COLUMN estimated_cost_usd SET DEFAULT 0.0;

-- User-facing feature defaults
ALTER TABLE user_sessions
    ALTER COLUMN session_metadata SET DEFAULT '{}'::jsonb;

ALTER TABLE user_sessions
    ALTER COLUMN retention_policy SET DEFAULT 'indefinite';

-- ============================================================================
-- Verification
-- ============================================================================

DO $$
DECLARE
    defaults_count INTEGER;
    missing_defaults TEXT[];
BEGIN
    -- Count columns with defaults
    SELECT COUNT(*) INTO defaults_count
    FROM information_schema.columns
    WHERE table_name = 'user_sessions'
      AND column_default IS NOT NULL;

    -- Check specific required defaults
    SELECT ARRAY_AGG(column_name) INTO missing_defaults
    FROM (
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'user_sessions'
          AND column_name IN (
              'session_type', 'status', 'created_at', 'last_active_at',
              'total_tokens', 'estimated_cost_usd', 'session_metadata', 'retention_policy'
          )
          AND column_default IS NULL
    ) missing;

    -- Verify all 8 defaults exist
    IF defaults_count < 8 THEN
        RAISE EXCEPTION 'Migration 002 incomplete: Only % of 8 defaults applied. Missing: %',
            defaults_count, missing_defaults;
    END IF;

    -- Log success
    RAISE NOTICE '✅ Migration 002 complete: Added 8 SQL defaults to user_sessions';
    RAISE NOTICE 'Defaults applied to: session_type, status, created_at, last_active_at, total_tokens, estimated_cost_usd, session_metadata, retention_policy';
END $$;

-- ============================================================================
-- Display updated schema
-- ============================================================================

-- Show columns with their new defaults (for verification)
SELECT
    column_name,
    data_type,
    column_default,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'user_sessions'
  AND column_name IN (
      'session_type', 'status', 'created_at', 'last_active_at',
      'total_tokens', 'estimated_cost_usd', 'session_metadata', 'retention_policy'
  )
ORDER BY ordinal_position;
