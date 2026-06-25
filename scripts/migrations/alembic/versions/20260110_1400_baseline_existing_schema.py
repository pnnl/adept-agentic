"""Baseline migration - captures existing schema state

This migration represents the existing database schema as of 2026-01-10.
It does NOT create any tables or make any changes - it simply marks
the database as being at this baseline revision for future migrations.

Tables included in baseline:
- user_sessions (Historical Retention Layer)
- session_messages (Historical Retention Layer)
- tool_outputs (Historical Retention Layer + Phase 1 ORM refactor)
- context_archives (Active Context Layer)
- checkpoints (LangGraph 1.0.5 schema from existing migrations)

Note: This migration should be applied with `alembic stamp head` to mark
the database as current without running any DDL operations.

Revision ID: 001_baseline
Revises:
Create Date: 2026-01-10 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Baseline migration - no operations performed.

    The schema already exists from manual migrations. This migration
    simply establishes a baseline for future Alembic-managed migrations.

    To mark your database as current without running this migration:
    ```
    alembic stamp head
    ```
    """
    pass


def downgrade() -> None:
    """
    Baseline migration - no downgrade operations.

    Downgrading from baseline would require dropping all tables,
    which should be done manually if needed.
    """
    pass
