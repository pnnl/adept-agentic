"""Migrate LangGraph checkpoints to 1.0.5 schema

Revision ID: 20260113_0030
Revises: 20260110_1430_backfill_tool_call_id
Create Date: 2026-01-13 00:30:00

This migration provides idempotent upgrade from LangGraph 0.0.8 to 1.0.5 checkpoint schema.

Migration Strategy:
- Detects current schema state using CheckpointSchemaMigrator
- Applies appropriate migration based on state:
  - MISSING: Create tables from ORM
  - OLD: Drop and recreate (checkpoints are ephemeral)
  - CURRENT: Skip (already up to date)
  - DRIFT: Auto-correct (drop and recreate, checkpoints are ephemeral)

Breaking Changes:
- Composite primary key (thread_id, checkpoint_ns, checkpoint_id) instead of single thread_id
- JSONB types instead of BYTEA for checkpoint and metadata
- Added: checkpoint_ns, checkpoint_id, parent_checkpoint_id, type columns
- Removed: created_at, updated_at columns

Data Loss Warning:
- This migration DROPS the old checkpoints table (if it exists)
- Checkpoint data is ephemeral and safe to lose
- If data preservation is critical, use MigrationStrategy.ALTER_TABLE

Usage:
    alembic upgrade head  # Run migration
    alembic downgrade -1  # Rollback (drops checkpoints table)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# No imports from orchestration_service needed - using pure Alembic operations

# revision identifiers, used by Alembic.
revision = '20260113_0030'
down_revision = '002_backfill_tool_call_id'
branch_labels = None
depends_on = None


def upgrade():
    """
    Upgrade to LangGraph 1.0.5 checkpoint schema.

    This function detects the current schema state and applies the appropriate migration:
    - MISSING → Create tables from ORM
    - OLD → Drop and recreate
    - CURRENT → Skip (no-op)
    - DRIFT → Raise error

    The migration is idempotent and can be safely re-run.
    """
    print("=" * 70)
    print("Migrating LangGraph checkpoints: 0.0.8 → 1.0.5")
    print("=" * 70)

    # Get database connection
    connection = op.get_bind()

    # Detect current schema state (synchronous version)
    from sqlalchemy import text, inspect
    inspector = inspect(connection)

    # Check if checkpoints table exists
    table_exists = inspector.has_table('checkpoints')

    if not table_exists:
        print(f"\n✅ Detected schema state: MISSING")
        print("📦 Creating checkpoints table from ORM (fresh install)...")
        _create_checkpoints_table()
        print("✅ Checkpoints table created successfully")
        return

    # Get current columns
    columns = {col['name']: col for col in inspector.get_columns('checkpoints')}
    pk_constraint = inspector.get_pk_constraint('checkpoints')
    current_pk = tuple(sorted(pk_constraint['constrained_columns'])) if pk_constraint else ()

    # LangGraph 1.0.5 schema signature
    expected_pk = ('checkpoint_id', 'checkpoint_ns', 'thread_id')
    expected_columns = {
        'thread_id', 'checkpoint_ns', 'checkpoint_id',
        'parent_checkpoint_id', 'type', 'checkpoint', 'metadata'
    }
    current_column_names = set(columns.keys())

    # Detect schema state
    if current_pk == expected_pk and current_column_names == expected_columns:
        # Check if checkpoint column is JSONB (not BYTEA)
        checkpoint_type = str(columns['checkpoint']['type']).upper()
        if 'JSONB' in checkpoint_type or 'JSON' in checkpoint_type:
            print(f"\n✅ Detected schema state: CURRENT")
            print("✅ Checkpoints schema already up to date (LangGraph 1.0.5)")
            print("   No migration needed - skipping")
            return

    # Determine if OLD (0.0.8) or DRIFT
    is_old_schema = (
        current_pk == ('thread_id',) and
        'checkpoint' in current_column_names and
        str(columns['checkpoint']['type']).upper().startswith('BYTEA')
    )

    if is_old_schema:
        print(f"\n✅ Detected schema state: OLD")
        print("⚠️  Old LangGraph 0.0.8 schema detected")
        print(f"   Current columns: {list(current_column_names)}")
        print(f"   Current PK: {current_pk}")
        print("\n📦 Dropping old table and recreating with new schema...")
        print("   (Checkpoint data is ephemeral and will be lost)")
    else:
        print(f"\n✅ Detected schema state: DRIFT")
        print("⚠️  Schema drift detected (likely from LangGraph runtime creation)")
        print(f"   Current columns: {list(current_column_names)}")
        print(f"   Current PK: {current_pk}")
        print(f"   Expected columns: {list(expected_columns)}")
        print(f"   Expected PK: {expected_pk}")
        print("\n📦 Dropping drifted table and recreating with correct schema...")
        print("   (Checkpoint data is ephemeral and safe to lose)")

    # Drop old/drifted checkpoints table
    op.drop_table('checkpoints')
    print("✅ Table dropped")

    # Create new table from ORM
    _create_checkpoints_table()
    print("✅ New table created with LangGraph 1.0.5 schema")


def downgrade():
    """
    Downgrade from LangGraph 1.0.5 to 0.0.8 schema.

    WARNING: This is a destructive operation that drops the checkpoints table.
    Only use if you need to rollback to LangGraph 0.0.8.

    Note: This does NOT recreate the old schema - it just drops the new table.
    If you need the old schema, you must restore from backup or recreate manually.
    """
    print("=" * 70)
    print("Rolling back LangGraph checkpoints: 1.0.5 → 0.0.8")
    print("=" * 70)
    print("⚠️  WARNING: This will DROP the checkpoints table")
    print("   All checkpoint data will be lost")

    # Check if table exists before dropping
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    if inspector.has_table('checkpoints'):
        op.drop_table('checkpoints')
        print("✅ Checkpoints table dropped")
    else:
        print("ℹ️  Checkpoints table doesn't exist - nothing to drop")

    print("\n⚠️  Note: This downgrade does NOT recreate the old 0.0.8 schema")
    print("   If needed, restore from backup or run old migration scripts")


def _create_checkpoints_table():
    """
    Create checkpoints table with LangGraph 1.0.5 schema.

    This creates the table using raw SQL to ensure exact schema match.
    The schema is defined in models/checkpoint_schema.py (ORM source of truth).
    """
    op.create_table(
        'checkpoints',
        sa.Column('thread_id', sa.String(), nullable=False, comment='Thread/conversation ID'),
        sa.Column('checkpoint_ns', sa.String(), nullable=False, server_default='',
                  comment='Checkpoint namespace (default: \'\' for main)'),
        sa.Column('checkpoint_id', sa.String(), nullable=False,
                  comment='Unique checkpoint ID (UUID/timestamp)'),
        sa.Column('parent_checkpoint_id', sa.String(), nullable=True,
                  comment='Parent checkpoint for branching/rollback (optional)'),
        sa.Column('type', sa.String(), nullable=True,
                  comment='Checkpoint type (standard, subgraph, etc.)'),
        sa.Column('checkpoint', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment='Serialized checkpoint data (LangGraph state)'),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}',
                  comment='Checkpoint metadata (timestamp, version, etc.)'),
        sa.PrimaryKeyConstraint('thread_id', 'checkpoint_ns', 'checkpoint_id'),
        comment='LangGraph 1.0.5 checkpoints (managed by CheckpointSchemaMigrator)'
    )

    # Create index for thread_id lookups
    op.create_index(
        'checkpoints_thread_id_idx',
        'checkpoints',
        ['thread_id'],
    )

    print("   ✅ Created checkpoints table")
    print("   ✅ Created checkpoints_thread_id_idx index")
    print("   Schema: 7 columns, JSONB types, composite PK (thread_id, checkpoint_ns, checkpoint_id)")
