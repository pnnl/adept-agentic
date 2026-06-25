"""Add unique constraint for tool_outputs ON CONFLICT support

Revision ID: 20260120_0001
Revises: 20260120_0000
Create Date: 2026-01-20 00:01:00.000000

Purpose:
    Add unique constraint on (thread_id, checkpoint_id, output_sequence)
    to support ON CONFLICT clause in persistence_v2.py save_tool_outputs()

Background:
    - persistence_v2.py:333 uses ON CONFLICT (thread_id, checkpoint_id, output_sequence)
    - Schema only has PRIMARY KEY on id (UUID), no unique constraint on tuple
    - This causes "there is no unique or exclusion constraint matching the ON CONFLICT specification"
    - Migration adds missing unique constraint to match code expectations

Related:
    - persistence_v2.py save_tool_outputs() method
    - Session 32 Phase 1 Schema Fixes

See: SQL migration 004_add_tool_outputs_unique_constraint.sql
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260120_0001'
down_revision: Union[str, None] = '20260120_0000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add unique constraint to tool_outputs table.

    This ensures one tool output per (thread_id, checkpoint_id, output_sequence) combination.
    Enables ON CONFLICT DO UPDATE upsert operations in persistence code.
    """
    # Check if table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'tool_outputs' not in inspector.get_table_names():
        print("ℹ️  tool_outputs table doesn't exist yet, skipping constraint")
        return

    # Check if constraint already exists (idempotent)
    constraints = inspector.get_unique_constraints('tool_outputs')
    constraint_exists = any(
        c['name'] == 'uq_tool_outputs_thread_checkpoint_seq'
        for c in constraints
    )

    if constraint_exists:
        print("ℹ️  Unique constraint uq_tool_outputs_thread_checkpoint_seq already exists, skipping")
        return

    # Add unique constraint
    op.create_unique_constraint(
        'uq_tool_outputs_thread_checkpoint_seq',
        'tool_outputs',
        ['thread_id', 'checkpoint_id', 'output_sequence']
    )

    print("✅ Added unique constraint uq_tool_outputs_thread_checkpoint_seq to tool_outputs")


def downgrade() -> None:
    """
    Remove unique constraint from tool_outputs table.

    WARNING: This breaks ON CONFLICT upsert operations in persistence code.
    Only downgrade if reverting to code that doesn't use ON CONFLICT.
    """
    # Check if table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'tool_outputs' not in inspector.get_table_names():
        print("ℹ️  tool_outputs table doesn't exist, skipping")
        return

    # Drop constraint if exists (idempotent)
    op.drop_constraint(
        'uq_tool_outputs_thread_checkpoint_seq',
        'tool_outputs',
        type_='unique'
    )

    print("✅ Removed unique constraint uq_tool_outputs_thread_checkpoint_seq from tool_outputs")
