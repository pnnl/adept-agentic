"""Backfill tool_call_id for existing tool_outputs

This migration ensures all tool_outputs rows have a valid tool_call_id value,
which is required by the NOT NULL constraint added in migration 002.

Problem Addressed:
- Existing ADEPT instances may have tool_outputs rows with NULL tool_call_id
- Fresh instances need the column created correctly
- The ORM refactor in Phase 1 now requires tool_call_id to be present

Solution:
1. Check if column exists (idempotent for fresh instances)
2. Backfill any NULL values with generated identifiers
3. Ensure NOT NULL constraint is applied after backfill

Safety:
- Idempotent: Can be run multiple times safely
- Non-destructive: Only updates NULL values, never overwrites existing data
- Transaction-safe: All operations in single transaction

Revision ID: 002_backfill_tool_call_id
Revises: 001_baseline
Create Date: 2026-01-10 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = '002_backfill_tool_call_id'
down_revision: Union[str, None] = '001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Backfill tool_call_id column for existing tool_outputs rows.

    This migration handles three scenarios:
    1. Fresh instance: Column doesn't exist → Add column, index, constraint
    2. Existing instance: Column exists with NULLs → Backfill NULLs only
    3. Already migrated: Column exists, no NULLs → No-op (safe)
    """
    conn = op.get_bind()

    # Step 1: Check if column exists (idempotency check)
    result = conn.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name='tool_outputs' AND column_name='tool_call_id'
    """))

    column_exists = result.fetchone() is not None

    if not column_exists:
        # Fresh instance: Add column as nullable first for backfill
        print("🔧 Creating tool_call_id column (fresh instance)")
        op.add_column('tool_outputs',
            sa.Column('tool_call_id', sa.String(), nullable=True))
    else:
        print("✅ tool_call_id column already exists")

    # Step 2: Backfill existing rows with NULL values
    # Generate predictable but unique identifiers using existing row data
    print("🔄 Backfilling NULL tool_call_id values...")

    result = conn.execute(text("""
        UPDATE tool_outputs
        SET tool_call_id = 'backfill_' || substring(md5(
            thread_id || '::' || checkpoint_id || '::' || output_sequence::text
        ), 1, 12)
        WHERE tool_call_id IS NULL
    """))

    rows_updated = result.rowcount
    if rows_updated > 0:
        print(f"✅ Backfilled {rows_updated} rows with generated tool_call_id values")
    else:
        print("✅ No NULL tool_call_id values found (already migrated)")

    # Step 3: Add NOT NULL constraint (safe now that all rows have values)
    if not column_exists:
        print("🔒 Adding NOT NULL constraint")
        op.alter_column('tool_outputs', 'tool_call_id', nullable=False)
    else:
        # Column exists - check if constraint needs to be added
        result = conn.execute(text("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name='tool_outputs' AND column_name='tool_call_id'
        """))

        is_nullable = result.fetchone()[0]
        if is_nullable == 'YES':
            print("🔒 Adding NOT NULL constraint to existing column")
            op.alter_column('tool_outputs', 'tool_call_id', nullable=False)
        else:
            print("✅ NOT NULL constraint already present")

    # Step 4: Add index if missing (idempotent)
    try:
        # Check if index exists
        result = conn.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename='tool_outputs' AND indexname='idx_tool_outputs_tool_call_id'
        """))

        if not result.fetchone():
            print("📊 Creating index on tool_call_id")
            op.create_index(
                'idx_tool_outputs_tool_call_id',
                'tool_outputs',
                ['tool_call_id'],
                unique=False
            )
        else:
            print("✅ Index idx_tool_outputs_tool_call_id already exists")

    except Exception as e:
        print(f"⚠️ Index creation skipped: {e}")
        # Non-critical - index may already exist

    print("✅ Migration 002_backfill_tool_call_id complete")


def downgrade() -> None:
    """
    Rollback: Remove tool_call_id column and index.

    WARNING: This will delete all tool_call_id data!
    """
    print("⚠️ Rolling back migration 002_backfill_tool_call_id")

    # Remove index
    try:
        op.drop_index('idx_tool_outputs_tool_call_id', table_name='tool_outputs')
        print("✅ Dropped index idx_tool_outputs_tool_call_id")
    except Exception as e:
        print(f"⚠️ Index drop skipped: {e}")

    # Remove column
    op.drop_column('tool_outputs', 'tool_call_id')
    print("✅ Dropped column tool_call_id")

    print("⚠️ Rollback complete - tool_call_id data has been removed")
