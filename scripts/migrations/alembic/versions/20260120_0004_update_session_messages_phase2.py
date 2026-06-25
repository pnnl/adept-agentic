"""Update session_messages schema for Phase 2 ORM compatibility

Revision ID: 20260120_0004
Revises: 20260120_0003
Create Date: 2026-01-20 00:04:00.000000

Purpose:
    Add Phase 2 schema features to existing deployments for ORM compatibility.

    1. Add content_tsvector generated column (full-text search)
    2. Add GIN index for full-text search
    3. Update primary key to composite (id, created_at)
    4. Update unique constraint to include created_at

    This migration is idempotent and safe to re-run.

Background:
    - Partitioned tables REQUIRE partition key (created_at) in PRIMARY KEY
    - Unique constraints MUST include partition key for ON CONFLICT upsert
    - Full-text search via tsvector improves message search performance
    - Fresh deployments using consolidated_initial_schema.sql already have these

Impact:
    - Enables ON CONFLICT upsert operations
    - Proper partition routing for inserts/updates
    - Full-text search capability on message content
    - ORM model matches database schema exactly

WARNING:
    Primary key update temporarily locks session_messages table.
    For large tables (>100K rows), run during low-traffic window.

Related:
    - session_models.py SessionMessage ORM model
    - Session 34 Phase 2 - ORM Schema Drift Fixes
    - Context management adapter persistence

See: SQL migration 007_update_session_messages_schema_phase2.sql
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260120_0004'
down_revision: Union[str, None] = '20260120_0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Apply Phase 2 schema updates to session_messages table.

    Steps:
    1. Add content_tsvector generated column
    2. Add GIN indexes (full-text search, tool_call_ids array)
    3. Update primary key to composite (id, created_at)
    4. Update unique constraint to include created_at
    """
    # Check if table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'session_messages' not in inspector.get_table_names():
        print("ℹ️  session_messages table doesn't exist yet, skipping Phase 2 schema updates")
        return

    # ========================================================================
    # STEP 1: Add content_tsvector generated column (if not exists)
    # ========================================================================
    columns = [col['name'] for col in inspector.get_columns('session_messages')]

    if 'content_tsvector' not in columns:
        print("Adding content_tsvector generated column to session_messages")
        op.execute("""
            ALTER TABLE session_messages
            ADD COLUMN content_tsvector tsvector
            GENERATED ALWAYS AS (to_tsvector('english', COALESCE(message_content, ''))) STORED
        """)
        print("✅ Added content_tsvector column")
    else:
        print("ℹ️  content_tsvector column already exists, skipping")

    # ========================================================================
    # STEP 2: Add GIN indexes (if not exist)
    # ========================================================================
    indexes = [idx['name'] for idx in inspector.get_indexes('session_messages')]

    # GIN index for full-text search
    if 'idx_session_messages_content_fts' not in indexes:
        print("Creating GIN index idx_session_messages_content_fts")
        op.create_index(
            'idx_session_messages_content_fts',
            'session_messages',
            ['content_tsvector'],
            postgresql_using='gin'
        )
        print("✅ Created GIN index for full-text search")
    else:
        print("ℹ️  Index idx_session_messages_content_fts already exists, skipping")

    # GIN index for tool_call_ids array
    if 'idx_session_messages_tool_calls' not in indexes:
        print("Creating GIN index idx_session_messages_tool_calls")
        op.create_index(
            'idx_session_messages_tool_calls',
            'session_messages',
            ['tool_call_ids'],
            postgresql_using='gin'
        )
        print("✅ Created GIN index for tool_call_ids")
    else:
        print("ℹ️  Index idx_session_messages_tool_calls already exists, skipping")

    # ========================================================================
    # STEP 3: Update Primary Key to Composite (id, created_at)
    # ========================================================================
    # Check current primary key structure
    result = conn.execute(sa.text("""
        SELECT array_length(conkey, 1) as key_count
        FROM pg_constraint
        WHERE conname = 'session_messages_pkey'
        AND contype = 'p'
        AND conrelid = 'session_messages'::regclass
    """))
    row = result.fetchone()

    if row and row[0] == 1:
        print("⚠️  Primary key is single-column (id), upgrading to composite (id, created_at)")
        print("⚠️  This operation will temporarily lock the session_messages table")

        # Drop existing primary key on parent table
        op.execute("ALTER TABLE session_messages DROP CONSTRAINT IF EXISTS session_messages_pkey")

        # Drop primary key on all partition tables
        result = conn.execute(sa.text("""
            SELECT inhrelid::regclass::text AS partition_name
            FROM pg_inherits
            WHERE inhparent = 'session_messages'::regclass
        """))
        partitions = result.fetchall()

        for partition in partitions:
            partition_name = partition[0]
            pkey_name = f"{partition_name}_pkey"
            try:
                op.execute(f"ALTER TABLE {partition_name} DROP CONSTRAINT IF EXISTS {pkey_name}")
            except Exception as e:
                print(f"⚠️  Could not drop constraint {pkey_name}: {e}")

        # Add composite primary key to parent table
        op.create_primary_key(
            'session_messages_pkey',
            'session_messages',
            ['id', 'created_at']
        )

        print("✅ Primary key updated to composite (id, created_at)")
    elif row and row[0] == 2:
        print("ℹ️  Primary key is already composite, skipping")
    else:
        print("⚠️  No primary key found on session_messages, adding composite key")
        op.create_primary_key(
            'session_messages_pkey',
            'session_messages',
            ['id', 'created_at']
        )
        print("✅ Added composite primary key (id, created_at)")

    # ========================================================================
    # STEP 4: Update Unique Constraint to Include created_at
    # ========================================================================
    # Check if old unique constraint exists (without created_at)
    result = conn.execute(sa.text("""
        SELECT array_length(conkey, 1) as key_count
        FROM pg_constraint
        WHERE conname = 'uq_session_message_idx'
        AND contype = 'u'
        AND conrelid = 'session_messages'::regclass
    """))
    row = result.fetchone()

    if row and row[0] == 2:
        print("⚠️  Unique constraint uq_session_message_idx is 2-column, upgrading to 3-column")

        # Drop old constraint
        op.drop_constraint(
            'uq_session_message_idx',
            'session_messages',
            type_='unique'
        )

        # Add new constraint with created_at
        op.create_unique_constraint(
            'uq_session_message_idx',
            'session_messages',
            ['session_id', 'message_index', 'created_at']
        )

        print("✅ Unique constraint updated to include created_at")
    elif row and row[0] == 3:
        print("ℹ️  Unique constraint already includes created_at, skipping")
    else:
        print("⚠️  Unique constraint uq_session_message_idx not found, creating with created_at")
        op.create_unique_constraint(
            'uq_session_message_idx',
            'session_messages',
            ['session_id', 'message_index', 'created_at']
        )
        print("✅ Created unique constraint with created_at")

    # ========================================================================
    # Validation
    # ========================================================================
    print("\n=== Migration 20260120_0004 Validation ===")

    # Check content_tsvector
    columns_after = [col['name'] for col in inspector.get_columns('session_messages')]
    tsvector_exists = 'content_tsvector' in columns_after
    print(f"✅ content_tsvector column exists: {tsvector_exists}")

    # Check indexes
    indexes_after = [idx['name'] for idx in inspector.get_indexes('session_messages')]
    content_fts_idx = 'idx_session_messages_content_fts' in indexes_after
    tool_calls_idx = 'idx_session_messages_tool_calls' in indexes_after
    print(f"✅ idx_session_messages_content_fts exists: {content_fts_idx}")
    print(f"✅ idx_session_messages_tool_calls exists: {tool_calls_idx}")

    # Check primary key
    result = conn.execute(sa.text("""
        SELECT array_length(conkey, 1) as key_count
        FROM pg_constraint
        WHERE conname = 'session_messages_pkey'
        AND contype = 'p'
        AND conrelid = 'session_messages'::regclass
    """))
    row = result.fetchone()
    pk_is_composite = row and row[0] == 2
    print(f"✅ Primary key is composite (id, created_at): {pk_is_composite}")

    # Check unique constraint
    result = conn.execute(sa.text("""
        SELECT array_length(conkey, 1) as key_count
        FROM pg_constraint
        WHERE conname = 'uq_session_message_idx'
        AND contype = 'u'
        AND conrelid = 'session_messages'::regclass
    """))
    row = result.fetchone()
    uq_has_created_at = row and row[0] == 3
    print(f"✅ Unique constraint includes created_at: {uq_has_created_at}")

    if not (tsvector_exists and content_fts_idx and tool_calls_idx and pk_is_composite and uq_has_created_at):
        raise Exception("Migration 20260120_0004 validation failed. Check logs for details.")

    print("=== Migration 20260120_0004 Complete ===\n")


def downgrade() -> None:
    """
    Rollback Phase 2 schema updates.

    WARNING: This is destructive and NOT fully supported.
    - Removes composite primary key (reverts to single-column id)
    - Removes unique constraint (breaks ON CONFLICT operations)
    - Removes GIN indexes (breaks full-text search)
    - Removes content_tsvector column

    Only downgrade if you have a backup and are reverting to pre-Phase-2 code.
    """
    # Check if table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'session_messages' not in inspector.get_table_names():
        print("ℹ️  session_messages table doesn't exist, skipping")
        return

    print("⚠️  WARNING: Downgrade is destructive and may break ORM compatibility")

    # Drop unique constraint
    try:
        op.drop_constraint('uq_session_message_idx', 'session_messages', type_='unique')
        print("✅ Dropped unique constraint uq_session_message_idx")
    except Exception as e:
        print(f"⚠️  Could not drop unique constraint: {e}")

    # Drop primary key (composite)
    try:
        op.execute("ALTER TABLE session_messages DROP CONSTRAINT IF EXISTS session_messages_pkey")
        print("✅ Dropped composite primary key")
    except Exception as e:
        print(f"⚠️  Could not drop primary key: {e}")

    # Add back single-column primary key on id
    try:
        op.create_primary_key('session_messages_pkey', 'session_messages', ['id'])
        print("✅ Restored single-column primary key (id)")
    except Exception as e:
        print(f"⚠️  Could not restore primary key: {e}")

    # Drop GIN indexes
    try:
        op.drop_index('idx_session_messages_content_fts', 'session_messages')
        print("✅ Dropped GIN index idx_session_messages_content_fts")
    except Exception as e:
        print(f"⚠️  Could not drop index: {e}")

    try:
        op.drop_index('idx_session_messages_tool_calls', 'session_messages')
        print("✅ Dropped GIN index idx_session_messages_tool_calls")
    except Exception as e:
        print(f"⚠️  Could not drop index: {e}")

    # Drop content_tsvector column
    try:
        op.drop_column('session_messages', 'content_tsvector')
        print("✅ Dropped content_tsvector column")
    except Exception as e:
        print(f"⚠️  Could not drop column: {e}")

    print("⚠️  Downgrade complete. ORM model may not match database schema.")
