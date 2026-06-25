-- ============================================================================
-- Consolidated Initial Schema: Session Management + Context Window Management
-- ============================================================================
-- Purpose: Complete database schema for fresh deployments
-- Equivalent to: Migrations 001 + 002 + 003 + 004
-- Author: Session 32 Phase 1 Migration Consolidation
-- Date: 2025-12-30
--
-- This consolidated schema merges all Phase 1 migrations into a single file
-- for fresh database deployments. It is idempotent and can be safely re-run.
--
-- Schema includes:
-- - user_sessions: User-facing session metadata with retention policies
-- - session_messages: Full conversation history (partitioned by month)
-- - tool_outputs: LangGraph checkpointer tool output persistence
-- - context_archives: LLM-generated summaries for context compression
-- - schema_migrations: Migration tracking table
-- - Helper functions, triggers, and indexes
--
-- For existing deployments: Use individual migrations 001, 002, 003, 004
-- For fresh deployments: Use this consolidated schema
-- ============================================================================

BEGIN;

-- ============================================================================
-- PART 0: Schema Migrations Tracking Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

-- Record that this consolidated schema is equivalent to migrations 001-004
-- NOTE: Migration 005 (LangGraph checkpoints) is now handled by Alembic migrations
INSERT INTO schema_migrations (migration_id, description)
VALUES
    ('001_create_session_tables', 'Base schema: user_sessions, session_messages, context_archives'),
    ('002_fix_tool_outputs_schema', 'Recreated tool_outputs with UUID primary key'),
    ('003_add_message_deletion_trigger', 'Added trigger for session_messages deletion handling'),
    ('004_add_tool_outputs_unique_constraint', 'Added unique constraint for ON CONFLICT support')
ON CONFLICT (migration_id) DO NOTHING;

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
-- PART 2: session_messages table WITH PARTITIONING
-- ============================================================================

-- Create parent table with partitioning
CREATE TABLE IF NOT EXISTS session_messages (
    -- Primary key (must include partition column for partitioned tables)
    id UUID DEFAULT gen_random_uuid(),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key to session
    session_id TEXT NOT NULL,

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

    -- Materialized tsvector for full-text search
    content_tsvector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', COALESCE(message_content, ''))
    ) STORED,

    -- Primary key and unique constraints MUST include partition column
    PRIMARY KEY (id, created_at),
    CONSTRAINT uq_session_message_idx UNIQUE (session_id, message_index, created_at)
) PARTITION BY RANGE (created_at);

-- Add foreign key constraint (must be done after table creation for partitioned tables)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_session_messages_session'
    ) THEN
        ALTER TABLE session_messages
            ADD CONSTRAINT fk_session_messages_session
            FOREIGN KEY (session_id)
            REFERENCES user_sessions(session_id)
            ON DELETE CASCADE;
    END IF;
END $$;

-- Function to create monthly partitions dynamically
-- (defined here before first use; also referenced in PART 6 for documentation)
CREATE OR REPLACE FUNCTION create_monthly_partition(target_date DATE)
RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
    table_exists BOOLEAN;
BEGIN
    start_date := date_trunc('month', target_date);
    end_date := date_trunc('month', target_date + INTERVAL '1 month');
    partition_name := 'session_messages_' || to_char(start_date, 'YYYY_MM');
    SELECT EXISTS (
        SELECT 1 FROM pg_tables WHERE tablename = partition_name
    ) INTO table_exists;
    IF table_exists THEN
        RETURN partition_name || ' already exists';
    END IF;
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

-- Create initial partitions (current month + next 12 months)
DO $$
BEGIN
    FOR i IN 0..12 LOOP
        PERFORM create_monthly_partition(
            (CURRENT_DATE + (i || ' months')::interval)::date
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
-- PART 3: tool_outputs table (LangGraph Checkpointer Persistence)
-- ============================================================================
-- NOTE: This is the complete schema from migration 002, which replaced the
-- partial ALTER statements from migration 001. The UUID primary key schema
-- matches what E2E tests and SQLAlchemy models expect.

CREATE TABLE IF NOT EXISTS tool_outputs (
    -- Primary key (UUID for E2E tests and models)
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Tool call identification
    tool_call_id VARCHAR NOT NULL,
    tool_name VARCHAR,

    -- Link to session_messages (for orphaning detection)
    -- NOTE: No FK constraint due to partitioning limitation (see migration 001 notes)
    -- Referential integrity maintained through triggers and application logic
    message_id UUID,

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
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique constraint for ON CONFLICT support (from migration 004)
    CONSTRAINT uq_tool_outputs_thread_checkpoint_seq
        UNIQUE (thread_id, checkpoint_id, output_sequence)
);

-- Performance indexes for tool_outputs
CREATE INDEX IF NOT EXISTS idx_tool_outputs_message_id ON tool_outputs(message_id);
CREATE INDEX IF NOT EXISTS idx_tool_outputs_retention_status ON tool_outputs(retention_status);
CREATE INDEX IF NOT EXISTS idx_tool_outputs_created_at ON tool_outputs(created_at);
CREATE INDEX IF NOT EXISTS idx_tool_outputs_session_id ON tool_outputs(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_outputs_thread_id ON tool_outputs(thread_id);
CREATE INDEX IF NOT EXISTS idx_tool_outputs_tool_call_id ON tool_outputs(tool_call_id);

-- ============================================================================
-- PART 4: context_archives table (Active Context Layer)
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
-- NOTE: PART 5 (checkpoints table) has been removed - now managed by Alembic
-- ============================================================================
-- The checkpoints table (LangGraph 1.0.5) is now created and managed by
-- Alembic migrations via the orchestration service lifespan.
-- See: scripts/migrations/alembic/versions/20260113_0030_migrate_langgraph_checkpoints_to_1_0_5.py
-- ============================================================================

-- ============================================================================
-- PART 7: Trigger Functions and Triggers
-- ============================================================================

-- Function to mark tool_outputs as orphaned when message_id becomes NULL
-- (from migration 001)
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

-- Trigger on tool_outputs for orphaning detection
DROP TRIGGER IF EXISTS on_tool_output_orphaned ON tool_outputs;
CREATE TRIGGER on_tool_output_orphaned
BEFORE UPDATE ON tool_outputs
FOR EACH ROW
WHEN (OLD.message_id IS DISTINCT FROM NEW.message_id)
EXECUTE FUNCTION mark_orphaned_tool_outputs();

-- Function to set tool_outputs.message_id=NULL when session_messages are deleted
-- (from migration 003 - workaround for partitioned table FK constraint limitation)
CREATE OR REPLACE FUNCTION set_tool_outputs_message_id_null()
RETURNS TRIGGER AS $$
BEGIN
    -- When a message is deleted, set message_id=NULL for all linked tool outputs
    UPDATE tool_outputs
    SET message_id = NULL
    WHERE message_id = OLD.id;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- Trigger on session_messages DELETE
DROP TRIGGER IF EXISTS on_session_message_deleted ON session_messages;
CREATE TRIGGER on_session_message_deleted
BEFORE DELETE ON session_messages
FOR EACH ROW
EXECUTE FUNCTION set_tool_outputs_message_id_null();

-- ============================================================================
-- PART 6: Helper Functions
-- ============================================================================

-- create_monthly_partition() is defined earlier (before first use in partition creation block)

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
-- PART 7: Schema Validation
-- ============================================================================

DO $$
DECLARE
    table_count INTEGER;
    col_count INTEGER;
    trigger_count INTEGER;
    index_count INTEGER;
    migration_count INTEGER;
BEGIN
    -- Verify schema_migrations table and records
    SELECT COUNT(*) INTO migration_count
    FROM schema_migrations
    WHERE migration_id IN (
        '001_create_session_tables',
        '002_fix_tool_outputs_schema',
        '003_add_message_deletion_trigger',
        '004_add_tool_outputs_unique_constraint'
    );
    ASSERT migration_count = 4, 'schema_migrations should have 4 records for migrations 001-004';

    -- Check user_sessions
    SELECT COUNT(*) INTO table_count FROM pg_tables WHERE tablename = 'user_sessions';
    ASSERT table_count = 1, 'user_sessions table not created';

    -- Check session_messages (partitioned table)
    SELECT COUNT(*) INTO table_count FROM pg_tables WHERE tablename = 'session_messages';
    ASSERT table_count = 1, 'session_messages table not created';

    -- Check tool_outputs
    SELECT COUNT(*) INTO table_count FROM pg_tables WHERE tablename = 'tool_outputs';
    ASSERT table_count = 1, 'tool_outputs table not created';

    -- Verify tool_outputs has 14 columns (from migration 002)
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'tool_outputs' AND table_schema = 'public';
    ASSERT col_count = 14, format('tool_outputs should have 14 columns, found %', col_count);

    -- Verify tool_outputs unique constraint (from migration 004)
    SELECT COUNT(*) INTO index_count
    FROM pg_constraint
    WHERE conname = 'uq_tool_outputs_thread_checkpoint_seq';
    ASSERT index_count = 1, 'tool_outputs unique constraint uq_tool_outputs_thread_checkpoint_seq not created';

    -- Check context_archives
    SELECT COUNT(*) INTO table_count FROM pg_tables WHERE tablename = 'context_archives';
    ASSERT table_count = 1, 'context_archives table not created';

    -- Check triggers
    SELECT COUNT(*) INTO trigger_count
    FROM information_schema.triggers
    WHERE trigger_name = 'on_tool_output_orphaned' AND event_object_table = 'tool_outputs';
    ASSERT trigger_count = 1, 'on_tool_output_orphaned trigger not created';

    SELECT COUNT(*) INTO trigger_count
    FROM information_schema.triggers
    WHERE trigger_name = 'on_session_message_deleted' AND event_object_table = 'session_messages';
    ASSERT trigger_count = 1, 'on_session_message_deleted trigger not created';

    RAISE NOTICE '========================================';
    RAISE NOTICE 'Consolidated Schema Applied Successfully';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Tables created:';
    RAISE NOTICE '  - schema_migrations (tracking table)';
    RAISE NOTICE '  - user_sessions (session metadata)';
    RAISE NOTICE '  - session_messages (partitioned conversation history)';
    RAISE NOTICE '  - tool_outputs (LangGraph checkpointer persistence)';
    RAISE NOTICE '  - context_archives (LLM summaries)';
    RAISE NOTICE '';
    RAISE NOTICE 'Triggers created:';
    RAISE NOTICE '  - on_tool_output_orphaned (orphaning detection)';
    RAISE NOTICE '  - on_session_message_deleted (message deletion handling)';
    RAISE NOTICE '';
    RAISE NOTICE 'Functions created:';
    RAISE NOTICE '  - mark_orphaned_tool_outputs()';
    RAISE NOTICE '  - set_tool_outputs_message_id_null()';
    RAISE NOTICE '  - create_monthly_partition()';
    RAISE NOTICE '  - parse_retention_policy()';
    RAISE NOTICE '';
    RAISE NOTICE 'Equivalent to migrations: 001, 002, 003, 004';
    RAISE NOTICE '========================================';
END $$;

COMMIT;
