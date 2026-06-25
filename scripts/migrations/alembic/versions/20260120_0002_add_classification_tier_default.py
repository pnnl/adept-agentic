"""Add DEFAULT constraint to classification_tier

Revision ID: 20260120_0002
Revises: 20260120_0001
Create Date: 2026-01-20 00:02:00.000000

Purpose:
    Fix schema discrepancy where classification_tier has NOT NULL
    but missing DEFAULT 'summarize' constraint.

Background:
    - context_archives table created with NOT NULL on classification_tier
    - DEFAULT 'summarize' was added to migration file AFTER initial deployment
    - Consolidated schema uses CREATE TABLE IF NOT EXISTS, so existing tables don't update
    - Causes INSERT failures without explicit classification_tier value

Impact:
    - E2E tests fail (5 failures, 1 error)
    - Active Context Layer functionality broken
    - Any INSERT without classification_tier fails

Fix:
    Add DEFAULT constraint via ALTER TABLE (works on existing tables)

Related:
    - context_archives table in session_models.py
    - Session 32 Phase 1 Schema Fixes

See: SQL migration 005_add_classification_tier_default.sql
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260120_0002'
down_revision: Union[str, None] = '20260120_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add DEFAULT constraint to classification_tier column.

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
        AND a.attname = 'classification_tier'
    """))
    row = result.fetchone()

    if row and row[0]:
        print(f"ℹ️  classification_tier already has DEFAULT: {row[0]}, skipping")
        return

    # Add DEFAULT constraint
    op.execute("ALTER TABLE context_archives ALTER COLUMN classification_tier SET DEFAULT 'summarize'")

    # Backfill any NULL values (defensive - shouldn't exist with NOT NULL)
    result = conn.execute(sa.text("""
        SELECT COUNT(*) FROM context_archives WHERE classification_tier IS NULL
    """))
    null_count = result.scalar()

    if null_count > 0:
        print(f"⚠️  Found {null_count} rows with NULL classification_tier, backfilling...")
        op.execute("""
            UPDATE context_archives
            SET classification_tier = 'summarize'
            WHERE classification_tier IS NULL
        """)
        print(f"✅ Backfilled {null_count} rows with default value")
    else:
        print("✅ No NULL values found in classification_tier (expected)")

    print("✅ Added DEFAULT 'summarize' to classification_tier")


def downgrade() -> None:
    """
    Remove DEFAULT constraint from classification_tier.

    WARNING: This may cause INSERT failures if code doesn't explicitly provide classification_tier.
    """
    # Check if table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'context_archives' not in inspector.get_table_names():
        print("ℹ️  context_archives table doesn't exist, skipping")
        return

    # Remove DEFAULT constraint
    op.execute("ALTER TABLE context_archives ALTER COLUMN classification_tier DROP DEFAULT")

    print("✅ Removed DEFAULT constraint from classification_tier")
