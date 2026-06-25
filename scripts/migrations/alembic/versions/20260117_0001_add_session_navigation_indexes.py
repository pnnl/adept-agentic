"""Add indexes for session navigation Phase 2

Revision ID: 20260117_0001
Revises: 20260117_0000
Create Date: 2026-01-17 00:01:00.000000

Purpose:
    Add 5 performance indexes for the enhanced session navigation UI (Phase 2):
    1. GIN index on tags array for tag filtering
    2. Trigram index on title for fuzzy text search
    3. Trigram index on JSONB summary_5w for search
    4. Index on estimated_cost_usd for cost-based sorting
    5. Index on total_tokens for token-based sorting

    These indexes enable:
    - Fast tag-based filtering (multi-select tags)
    - Fuzzy search on session titles (partial match)
    - Search within AI-generated summaries
    - Efficient sorting by cost and token usage
    - Pagination with LIMIT/OFFSET queries

See: docs/implementation-plans/STREAMLIT_SESSION_NAVIGATION_PHASE2_ENHANCED_UI_PLAN_20260117.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260117_0001'
down_revision: Union[str, None] = '20260117_0000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add performance indexes for session navigation Phase 2.

    Indexes are created with IF NOT EXISTS for idempotency.
    """
    # Check if table exists first (idempotent)
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'user_sessions' not in inspector.get_table_names():
        print("ℹ️  user_sessions table doesn't exist yet, skipping index creation")
        return

    # Enable pg_trgm extension for fuzzy text search (idempotent)
    print("Enabling pg_trgm extension for fuzzy text search...")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Index 1: GIN index on tags array for tag filtering
    print("Creating index: idx_user_sessions_tags (GIN on tags array)...")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_sessions_tags
        ON user_sessions USING GIN (tags)
    """)

    # Index 2: Trigram index on title for fuzzy text search
    print("Creating index: idx_user_sessions_title_trgm (trigram on title)...")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_sessions_title_trgm
        ON user_sessions USING gin (title gin_trgm_ops)
    """)

    # Index 3: Trigram index on JSONB summary_5w for search
    # Note: Use ->> operator to extract JSONB as text (gin_trgm_ops requires text type)
    print("Creating index: idx_user_sessions_metadata_summary (trigram on JSONB summary)...")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_sessions_metadata_summary
        ON user_sessions USING gin ((session_metadata->>'summary_5w') gin_trgm_ops)
    """)

    # Index 4: Index on estimated_cost_usd for cost-based sorting
    print("Creating index: idx_user_sessions_cost (cost sorting)...")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_sessions_cost
        ON user_sessions(estimated_cost_usd DESC NULLS LAST)
    """)

    # Index 5: Index on total_tokens for token-based sorting
    print("Creating index: idx_user_sessions_tokens (token sorting)...")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_sessions_tokens
        ON user_sessions(total_tokens DESC NULLS LAST)
    """)

    print("✅ Added 5 performance indexes for session navigation Phase 2")


def downgrade() -> None:
    """
    Remove performance indexes for session navigation Phase 2.

    Note: This doesn't remove pg_trgm extension (may be used elsewhere).
    Indexes are dropped with IF EXISTS for idempotency.
    """
    # Check if table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'user_sessions' not in inspector.get_table_names():
        print("ℹ️  user_sessions table doesn't exist, skipping")
        return

    print("Dropping index: idx_user_sessions_tokens...")
    op.execute("DROP INDEX IF EXISTS idx_user_sessions_tokens")

    print("Dropping index: idx_user_sessions_cost...")
    op.execute("DROP INDEX IF EXISTS idx_user_sessions_cost")

    print("Dropping index: idx_user_sessions_metadata_summary...")
    op.execute("DROP INDEX IF EXISTS idx_user_sessions_metadata_summary")

    print("Dropping index: idx_user_sessions_title_trgm...")
    op.execute("DROP INDEX IF EXISTS idx_user_sessions_title_trgm")

    print("Dropping index: idx_user_sessions_tags...")
    op.execute("DROP INDEX IF EXISTS idx_user_sessions_tags")

    print("✅ Removed 5 performance indexes from user_sessions table")
    print("ℹ️  Note: pg_trgm extension not removed (may be used elsewhere)")
