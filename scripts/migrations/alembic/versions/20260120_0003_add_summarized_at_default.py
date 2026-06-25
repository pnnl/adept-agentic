"""Add DEFAULT constraint to summarized_at

Revision ID: 20260120_0003
Revises: 20260120_0002
Create Date: 2026-01-20 00:03:00.000000

Purpose:
    Fix schema discrepancy where summarized_at has NOT NULL
    but missing DEFAULT CURRENT_TIMESTAMP constraint.

Background:
    - Similar to classification_tier issue (migration 005)
    - summarized_at has NOT NULL (from SQLAlchemy model)
    - Missing DEFAULT constraint (migration file only specified DEFAULT, not NOT NULL)
    - Causes mismatch between ORM and database schema

Impact:
    - E2E tests fail (5 failures, 1 error)
    - Context archiving functionality broken
    - Any INSERT without summarized_at value fails

Fix:
    Add DEFAULT CURRENT_TIMESTAMP via ALTER TABLE

Related:
    - context_archives table in session_models.py
    - Migration 005 (classification_tier default)
    - Session 32 Phase 1 Schema Fixes

See: SQL migration 006_add_summarized_at_default.sql
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260120_0003'
down_revision: Union[str, None] = '20260120_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add DEFAULT CURRENT_TIMESTAMP constraint to summarized_at column.

    Also backfills any NULL values (defensive, shouldn't exist with NOT NULL constraint).
    """
    # Check if table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'context_archives' not in inspector.get_table_names():
        print("ℹ️  context_archives table doesn't exist yet, skipping DEFAULT constraint")
        return

    # Check if column already has default (idempotent)
    result = conn.execute(sa.text("""
        SELECT pg_get_expr(adbin, adrelid) as default_value
        FROM pg_catalog.pg_attrdef d
        JOIN pg_catalog.pg_attribute a ON (a.attrelid, a.attnum) = (d.adrelid, d.adnum)
        JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
        WHERE c.relname = 'context_archives'
        AND a.attname = 'summarized_at'
    """))
    row = result.fetchone()

    if row and row[0]:
        print(f"ℹ️  summarized_at already has DEFAULT: {row[0]}, skipping")
        return

    # Add DEFAULT constraint
    op.execute("ALTER TABLE context_archives ALTER COLUMN summarized_at SET DEFAULT CURRENT_TIMESTAMP")

    # Backfill any NULL values (defensive - shouldn't exist with NOT NULL)
    result = conn.execute(sa.text("""
        SELECT COUNT(*) FROM context_archives WHERE summarized_at IS NULL
    """))
    null_count = result.scalar()

    if null_count > 0:
        print(f"⚠️  Found {null_count} rows with NULL summarized_at, backfilling...")
        op.execute("""
            UPDATE context_archives
            SET summarized_at = CURRENT_TIMESTAMP
            WHERE summarized_at IS NULL
        """)
        print(f"✅ Backfilled {null_count} rows with CURRENT_TIMESTAMP")
    else:
        print("✅ No NULL values found in summarized_at (expected)")

    print("✅ Added DEFAULT CURRENT_TIMESTAMP to summarized_at")


def downgrade() -> None:
    """
    Remove DEFAULT constraint from summarized_at.

    WARNING: This may cause INSERT failures if code doesn't explicitly provide summarized_at.
    """
    # Check if table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'context_archives' not in inspector.get_table_names():
        print("ℹ️  context_archives table doesn't exist, skipping")
        return

    # Remove DEFAULT constraint
    op.execute("ALTER TABLE context_archives ALTER COLUMN summarized_at DROP DEFAULT")

    print("✅ Removed DEFAULT constraint from summarized_at")
