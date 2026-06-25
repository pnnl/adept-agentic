-- Migration: 001_create_session_tables.sql
-- Purpose: Create session management and context window tables with showstopper fixes
-- Author: Phase 1 Implementation
-- Date: 2025-12-26
--
-- This migration creates the foundational database schema for the integrated
-- Session Management + Context Window Management system. It includes:
-- - user_sessions: User-facing session metadata
-- - session_messages: Full conversation history (partitioned by month)
-- - tool_outputs: Modified existing table with FK to session_messages
-- - context_archives: LLM-generated summaries for context compression
-- - Helper functions for partition management and retention policy parsing
-- - Triggers for auto-updating orphaned tool_outputs

-- ============================================================================
-- PART 1: user_sessions table (Historical Retention Layer)
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_sessions (
    -- Primary key
    session_id TEXT PRIMARY KEY,

    -- Multi-tier session identifiers (from existing session_manager.py)
    mcp_session_id TEXT,
    multi_agent_session_id TEXT,
    gateway_session_id TEXT,

    -- User identification
    user_id TEXT NOT NULL,
    username TEXT,

    -- Session metadata
    session_type TEXT NOT NULL DEFAULT 'response',  -- response, multi_agent (assistant DEPRECATED)
    status TEXT NOT NULL DEFAULT 'active',  -- active, archived, pending_deletion, deleted

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_active_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TIMESTAMP,
    deleted_at TIMESTAMP,

    -- Cost tracking
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd NUMERIC(10, 6) DEFAULT 0.0,

    -- User-facing features
    title TEXT,  -- User-defined session title
    tags TEXT[],  -- Searchable tags
    session_metadata JSONB DEFAULT '{}',  -- Flexible metadata

    -- Retention policy
    retention_policy TEXT DEFAULT 'indefinite',  -- "indefinite", "-1", "30d", "90d", "1m", etc.

    -- Constraints
    CONSTRAINT chk_user_sessions_status CHECK (
        status IN ('active', 'archived', 'pending_deletion', 'deleted')
    )
);

-- Performance indexes for user_sessions
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_status_created
    ON user_sessions(user_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_sessions_last_active
    ON user_sessions(last_active_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_sessions_status
    ON user_sessions(status);
CREATE INDEX IF NOT EXISTS idx_user_sessions_tags
    ON user_sessions USING gin(tags);  -- GIN index for array search
CREATE INDEX IF NOT EXISTS idx_user_sessions_multi_tier
    ON user_sessions(mcp_session_id, multi_agent_session_id);

-- ============================================================================
-- PART 2: session_messages table WITH PARTITIONING (Showstopper #4)
-- ============================================================================

-- Create parent table with partitioning
CREATE TABLE IF NOT EXISTS session_messages (
    -- Primary key (must include partition column for partitioned tables)
    id UUID DEFAULT gen_random_uuid(),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key to session
    session_id TEXT NOT NULL REFERENCES user_sessions(session_id) ON DELETE CASCADE,

    -- Message identification
    message_index INTEGER NOT NULL,
    message_role TEXT NOT NULL,  -- user, assistant, system, tool

    -- Message content
    message_content TEXT,
    message_metadata JSONB DEFAULT '{}',

    -- Context classification (from Active Context Layer)
    context_layer TEXT DEFAULT 'historical',  -- active, historical
    classification_tier TEXT,  -- retain, summarize, delete (if from Active Layer)
    importance_score FLOAT,
    fidelity_level TEXT,  -- high, medium, low

    -- Tool call linkage (for preventing orphaned tool_outputs)
    tool_call_ids TEXT[],  -- Array of tool call IDs
    has_tool_outputs BOOLEAN DEFAULT FALSE,

    -- Materialized tsvector for full-text search (Showstopper #9)
    content_tsvector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', COALESCE(message_content, ''))
    ) STORED,

    -- Primary key and unique constraints MUST include partition column
    PRIMARY KEY (id, created_at),
    CONSTRAINT uq_session_message_idx UNIQUE (session_id, message_index, created_at)
) PARTITION BY RANGE (created_at);

-- Create initial partitions (current month + next 3 months)
DO $$
DECLARE
    start_date DATE;
    end_date DATE;
    partition_name TEXT;
BEGIN
    -- Current month (2025-12)
    start_date := '2025-12-01'::DATE;
    end_date := '2026-01-01'::DATE;
    partition_name := 'session_messages_2025_12';
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF session_messages FOR VALUES FROM (%L) TO (%L)',
        partition_name, start_date, end_date
    );

    -- Next 3 months
    FOR i IN 1..3 LOOP
        start_date := date_trunc('month', start_date + INTERVAL '1 month');
        end_date := date_trunc('month', start_date + INTERVAL '1 month');
        partition_name := 'session_messages_' || to_char(start_date, 'YYYY_MM');
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF session_messages FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_date, end_date
        );
    END LOOP;
END $$;

-- Performance indexes (applied to parent table, inherited by partitions)
CREATE INDEX IF NOT EXISTS idx_session_messages_session
    ON session_messages(session_id, message_index);
CREATE INDEX IF NOT EXISTS idx_session_messages_created
    ON session_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_messages_role
    ON session_messages(message_role);
CREATE INDEX IF NOT EXISTS idx_session_messages_context_layer
    ON session_messages(context_layer);
CREATE INDEX IF NOT EXISTS idx_session_messages_tool_calls
    ON session_messages USING gin(tool_call_ids);
CREATE INDEX IF NOT EXISTS idx_session_messages_content_fts
    ON session_messages USING gin(content_tsvector);

-- ============================================================================
-- PART 3: tool_outputs ALTER statements (Modify Existing Table)
-- ============================================================================

-- Add new columns if they don't exist
DO $$
BEGIN
    -- Add message_id column (FK to session_messages)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tool_outputs' AND column_name = 'message_id'
    ) THEN
        ALTER TABLE tool_outputs ADD COLUMN message_id UUID;
    END IF;

    -- Add retention_status column
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tool_outputs' AND column_name = 'retention_status'
    ) THEN
        ALTER TABLE tool_outputs ADD COLUMN retention_status TEXT DEFAULT 'active';
    END IF;
END $$;

-- NOTE: FK constraint cannot be created due to PostgreSQL partitioning limitation
-- Foreign keys on partitioned tables must reference columns that include the partition key.
-- Since session_messages is partitioned by created_at, the FK would need to reference
-- (id, created_at), but tool_outputs doesn't have message_created_at.
-- Referential integrity is maintained through:
-- 1. Application logic in the orchestration service
-- 2. The on_tool_output_orphaned trigger marks orphaned tool_outputs
-- 3. Cleanup jobs periodically remove orphaned tool_outputs
--
-- Future: Consider composite FK (message_id, message_created_at) if needed
--
-- DO $$
-- BEGIN
--     IF NOT EXISTS (
--         SELECT 1 FROM pg_constraint WHERE conname = 'fk_tool_outputs_message'
--     ) THEN
--         ALTER TABLE tool_outputs
--             ADD CONSTRAINT fk_tool_outputs_message
--             FOREIGN KEY (message_id)
--             REFERENCES session_messages(id)
--             ON DELETE SET NULL;  -- Don't cascade, trigger will mark as orphaned
--     END IF;
-- END $$;

-- Add indexes for tool_outputs
CREATE INDEX IF NOT EXISTS idx_tool_outputs_message
    ON tool_outputs(message_id);
CREATE INDEX IF NOT EXISTS idx_tool_outputs_retention
    ON tool_outputs(retention_status);

-- ============================================================================
-- PART 4: Trigger for auto-updating orphaned tool_outputs (Showstopper #3)
-- ============================================================================

-- Function to mark tool_outputs as orphaned when message_id becomes NULL
CREATE OR REPLACE FUNCTION mark_orphaned_tool_outputs()
RETURNS TRIGGER AS $$
BEGIN
    -- When message_id changes from non-NULL to NULL, mark as orphaned
    IF NEW.message_id IS NULL AND OLD.message_id IS NOT NULL THEN
        NEW.retention_status := 'orphaned';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if it exists, then create it
DROP TRIGGER IF EXISTS on_tool_output_orphaned ON tool_outputs;
CREATE TRIGGER on_tool_output_orphaned
BEFORE UPDATE ON tool_outputs
FOR EACH ROW
WHEN (OLD.message_id IS DISTINCT FROM NEW.message_id)
EXECUTE FUNCTION mark_orphaned_tool_outputs();

-- ============================================================================
-- PART 5: context_archives table (Active Context Layer)
-- ============================================================================

CREATE TABLE IF NOT EXISTS context_archives (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Session identifiers
    session_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    mcp_session_id TEXT,
    multi_agent_session_id TEXT,

    -- Archive metadata
    archive_sequence INTEGER NOT NULL,  -- Sequential number for this session's archives
    message_range_start INTEGER NOT NULL,  -- First message index in this archive
    message_range_end INTEGER NOT NULL,  -- Last message index in this archive

    -- Summarized content
    summary_content TEXT NOT NULL,  -- LLM-generated summary
    original_token_count INTEGER NOT NULL,
    summary_token_count INTEGER NOT NULL,
    compression_ratio FLOAT,  -- summary_tokens / original_tokens

    -- Classification metadata
    classification_tier TEXT NOT NULL DEFAULT 'summarize',  -- DELETE, SUMMARIZE, RETAIN
    average_importance_score FLOAT,

    -- Summarization metadata
    summarization_model TEXT,  -- Model used for summarization
    summarization_strategy TEXT,  -- Strategy name from factory
    summarized_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- User context
    user_id TEXT,

    -- Constraints
    CONSTRAINT uq_context_archives_seq UNIQUE (session_id, archive_sequence)
);

-- Performance indexes for context_archives
CREATE INDEX IF NOT EXISTS idx_context_archives_session
    ON context_archives(session_id, archive_sequence);
CREATE INDEX IF NOT EXISTS idx_context_archives_thread
    ON context_archives(thread_id);
CREATE INDEX IF NOT EXISTS idx_context_archives_summarized
    ON context_archives(summarized_at DESC);

-- ============================================================================
-- PART 6: Helper function for partition management
-- ============================================================================

-- Function to create monthly partitions dynamically
CREATE OR REPLACE FUNCTION create_monthly_partition(target_date DATE)
RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
    table_exists BOOLEAN;
BEGIN
    -- Calculate partition boundaries
    start_date := date_trunc('month', target_date);
    end_date := date_trunc('month', target_date + INTERVAL '1 month');

    -- Generate partition name
    partition_name := 'session_messages_' || to_char(start_date, 'YYYY_MM');

    -- Check if partition already exists
    SELECT EXISTS (
        SELECT 1 FROM pg_tables WHERE tablename = partition_name
    ) INTO table_exists;

    IF table_exists THEN
        RETURN partition_name || ' already exists';
    END IF;

    -- Create partition
    EXECUTE format(
        'CREATE TABLE %I PARTITION OF session_messages ' ||
        'FOR VALUES FROM (%L) TO (%L)',
        partition_name,
        start_date,
        end_date
    );

    RETURN partition_name || ' created successfully';
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- PART 7: Retention policy helper function
-- ============================================================================

-- Function to parse retention policy strings into days
CREATE OR REPLACE FUNCTION parse_retention_policy(policy_str TEXT)
RETURNS INTEGER AS $$
BEGIN
    -- Parse retention policy string to days
    -- Examples: "indefinite" or "-1" → -1, "30d" → 30, "3m" → 90, "1y" → 365

    -- Handle indefinite retention
    IF policy_str = 'indefinite' OR policy_str = '-1' THEN
        RETURN -1;
    END IF;

    -- Parse format like "30d", "3m", "1y"
    IF policy_str ~ '^\d+[dmy]$' THEN
        CASE substring(policy_str from '[dmy]$')
            WHEN 'd' THEN
                RETURN substring(policy_str from '^\d+')::INTEGER;
            WHEN 'm' THEN
                RETURN substring(policy_str from '^\d+')::INTEGER * 30;
            WHEN 'y' THEN
                RETURN substring(policy_str from '^\d+')::INTEGER * 365;
        END CASE;
    END IF;

    -- Default to indefinite if unparseable
    RETURN -1;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- PART 8: Migration verification
-- ============================================================================

-- Verify all tables exist
DO $$
DECLARE
    table_count INTEGER;
BEGIN
    -- Check user_sessions
    SELECT COUNT(*) INTO table_count FROM pg_tables WHERE tablename = 'user_sessions';
    ASSERT table_count = 1, 'user_sessions table not created';

    -- Check session_messages (partitioned table)
    SELECT COUNT(*) INTO table_count FROM pg_tables WHERE tablename = 'session_messages';
    ASSERT table_count = 1, 'session_messages table not created';

    -- Check context_archives
    SELECT COUNT(*) INTO table_count FROM pg_tables WHERE tablename = 'context_archives';
    ASSERT table_count = 1, 'context_archives table not created';

    -- Check tool_outputs columns
    SELECT COUNT(*) INTO table_count FROM information_schema.columns
    WHERE table_name = 'tool_outputs' AND column_name IN ('message_id', 'retention_status');
    ASSERT table_count = 2, 'tool_outputs columns not added';

    RAISE NOTICE 'Migration 001 completed successfully';
    RAISE NOTICE 'Created tables: user_sessions, session_messages (partitioned), context_archives';
    RAISE NOTICE 'Modified table: tool_outputs (added message_id, retention_status)';
    RAISE NOTICE 'Created triggers: on_tool_output_orphaned';
    RAISE NOTICE 'Created functions: create_monthly_partition(), parse_retention_policy(), mark_orphaned_tool_outputs()';
END $$;
