-- Migration: 003_add_message_deletion_trigger.sql
-- Purpose: Add trigger to set tool_outputs.message_id=NULL when session_messages are deleted
-- Author: Session 32 Phase 1 Completion
-- Date: 2025-12-30
--
-- This migration adds a workaround for the partitioned table FK constraint limitation:
-- - session_messages is a partitioned table
-- - PostgreSQL doesn't support FK from tool_outputs → session_messages
-- - Solution: Trigger on session_messages DELETE to manually set tool_outputs.message_id=NULL

-- ============================================================================
-- PART 1: Create trigger function
-- ============================================================================

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

-- ============================================================================
-- PART 2: Create trigger on session_messages DELETE
-- ============================================================================

DROP TRIGGER IF EXISTS on_session_message_deleted ON session_messages;

CREATE TRIGGER on_session_message_deleted
BEFORE DELETE ON session_messages
FOR EACH ROW
EXECUTE FUNCTION set_tool_outputs_message_id_null();

-- ============================================================================
-- PART 3: Verification
-- ============================================================================

DO $$
DECLARE
    trigger_count INTEGER;
BEGIN
    -- Check trigger exists
    SELECT COUNT(*) INTO trigger_count
    FROM information_schema.triggers
    WHERE trigger_name = 'on_session_message_deleted'
      AND event_object_table = 'session_messages';

    IF trigger_count != 1 THEN
        RAISE EXCEPTION 'on_session_message_deleted trigger should exist, found % triggers', trigger_count;
    END IF;

    RAISE NOTICE 'Migration 003 completed successfully:';
    RAISE NOTICE '  - set_tool_outputs_message_id_null() function created';
    RAISE NOTICE '  - on_session_message_deleted trigger created';
    RAISE NOTICE '  - Workaround for partitioned table FK constraint complete';
END $$;
