"""Add SQL-level defaults to user_sessions table

Revision ID: 20260117_0000
Revises: 20260113_0030
Create Date: 2026-01-17 00:00:00.000000

Purpose:
    Add missing SQL-level defaults to user_sessions table to align database
    schema with ORM model definitions. This fixes the discrepancy caused by
    SQLAlchemy's metadata.create_all() bypassing Column defaults.

    This migration is idempotent and safe to run multiple times.

Background:
    - Tables created via Base.metadata.create_all() lack SQL DEFAULT clauses
    - ORM Column defaults only work at Python level (not SQL level)
    - This causes inconsistency for non-Python clients and direct SQL inserts

See: docs/database-schema/ORM_SCHEMA_DISCREPANCY_ANALYSIS.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260117_0000'
down_revision: Union[str, None] = '20260113_0030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add SQL-level defaults to user_sessions table.

    These defaults match the ORM model (session_models.py) and ensure
    consistency across all database clients.
    """
    # Check if table exists first (idempotent)
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'user_sessions' not in inspector.get_table_names():
        # Table doesn't exist yet, will be created by metadata.create_all()
        # Defaults will be added when table is created
        print("ℹ️  user_sessions table doesn't exist yet, skipping defaults")
        return

    # Add SQL defaults (idempotent - only adds if not already set)
    # Note: ALTER COLUMN SET DEFAULT is idempotent in PostgreSQL

    # Session metadata defaults
    op.execute("ALTER TABLE user_sessions ALTER COLUMN session_type SET DEFAULT 'response'")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN status SET DEFAULT 'active'")

    # Timestamp defaults
    op.execute("ALTER TABLE user_sessions ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN last_active_at SET DEFAULT CURRENT_TIMESTAMP")

    # Cost tracking defaults
    op.execute("ALTER TABLE user_sessions ALTER COLUMN total_tokens SET DEFAULT 0")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN estimated_cost_usd SET DEFAULT 0.0")

    # User-facing feature defaults
    op.execute("ALTER TABLE user_sessions ALTER COLUMN session_metadata SET DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN retention_policy SET DEFAULT 'indefinite'")

    print("✅ Added 8 SQL defaults to user_sessions table")


def downgrade() -> None:
    """
    Remove SQL-level defaults from user_sessions table.

    Note: This doesn't remove the columns or data, just the DEFAULT clauses.
    ORM-level defaults will still work (Python-level only).
    """
    # Check if table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'user_sessions' not in inspector.get_table_names():
        print("ℹ️  user_sessions table doesn't exist, skipping")
        return

    # Remove SQL defaults (idempotent)
    op.execute("ALTER TABLE user_sessions ALTER COLUMN session_type DROP DEFAULT")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN created_at DROP DEFAULT")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN last_active_at DROP DEFAULT")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN total_tokens DROP DEFAULT")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN estimated_cost_usd DROP DEFAULT")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN session_metadata DROP DEFAULT")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN retention_policy DROP DEFAULT")

    print("✅ Removed 8 SQL defaults from user_sessions table (ORM defaults still work)")
