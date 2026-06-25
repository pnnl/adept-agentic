-- ============================================================================
-- Migration 004: Add unique constraint for tool_outputs ON CONFLICT support
-- ============================================================================
-- Date: 2025-12-30
-- Author: Session 32 Phase 1 Schema Fixes
-- Purpose: Add unique constraint on (thread_id, checkpoint_id, output_sequence)
--          to support ON CONFLICT clause in persistence_v2.py save_tool_outputs()
--
-- Related Issue: Issue 4 - ON CONFLICT specification error
-- Error: "there is no unique or exclusion constraint matching the ON CONFLICT specification"
--
-- Background:
-- persistence_v2.py:333 uses:
--   ON CONFLICT (thread_id, checkpoint_id, output_sequence) DO UPDATE
-- But the schema only has PRIMARY KEY on id (UUID), no unique constraint
-- on the (thread_id, checkpoint_id, output_sequence) tuple.
--
-- This migration adds the missing unique constraint to match the code's expectations.
-- ============================================================================

-- Add unique constraint to tool_outputs
-- This ensures one tool output per (thread_id, checkpoint_id, output_sequence) combination
ALTER TABLE tool_outputs
ADD CONSTRAINT uq_tool_outputs_thread_checkpoint_seq
UNIQUE (thread_id, checkpoint_id, output_sequence);

-- ============================================================================
-- Validation Query (run after migration)
-- ============================================================================
-- SELECT constraint_name, constraint_type
-- FROM information_schema.table_constraints
-- WHERE table_name = 'tool_outputs'
-- AND constraint_name = 'uq_tool_outputs_thread_checkpoint_seq';
