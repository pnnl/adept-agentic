"""Add trigger to set tool_outputs.message_id=NULL on session_messages deletion

Revision ID: 20260120_0000
Revises: 20260117_0001
Create Date: 2026-01-20 00:00:00.000000

Purpose:
    Add trigger function and trigger to handle cascade deletion workaround
    for partitioned table FK constraint limitation.

    PostgreSQL doesn't support FK from tool_outputs → session_messages when
    session_messages is partitioned. This trigger manually sets message_id=NULL
    when messages are deleted.

Background:
    - session_messages is a partitioned table (monthly partitions)
    - PostgreSQL FK constraints don't work with partitioned target tables
    - Solution: Trigger on session_messages DELETE sets tool_outputs.message_id=NULL
    - This prevents FK violations and orphaned references

See: SQL migration 003_add_message_deletion_trigger.sql
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260120_0000'
down_revision: Union[str, None] = '20260117_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create trigger function and trigger to handle message deletion.

    When a session_message is deleted:
    1. Trigger executes BEFORE DELETE
    2. Updates tool_outputs.message_id = NULL for linked outputs
    3. Allows message deletion without FK violation
    """
    # Check if tables exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    table_names = inspector.get_table_names()
    if 'session_messages' not in table_names:
        print("ℹ️  session_messages table doesn't exist yet, skipping trigger")
        return

    if 'tool_outputs' not in table_names:
        print("ℹ️  tool_outputs table doesn't exist yet, skipping trigger")
        return

    # Part 1: Create trigger function (idempotent with CREATE OR REPLACE)
    op.execute("""
        CREATE OR REPLACE FUNCTION set_tool_outputs_message_id_null()
        RETURNS TRIGGER AS $$
        BEGIN
            -- When a message is deleted, set message_id=NULL for all linked tool outputs
            UPDATE tool_outputs
            SET message_id = NULL
            WHERE message_id = OLD.id;

            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Part 2: Create trigger (idempotent with DROP IF EXISTS first)
    op.execute("DROP TRIGGER IF EXISTS on_session_message_deleted ON session_messages")

    op.execute("""
        CREATE TRIGGER on_session_message_deleted
        BEFORE DELETE ON session_messages
        FOR EACH ROW
        EXECUTE FUNCTION set_tool_outputs_message_id_null();
    """)

    print("✅ Created message deletion trigger and function")


def downgrade() -> None:
    """
    Remove trigger and trigger function.

    WARNING: Removing this trigger means tool_outputs.message_id will NOT
    be nullified on message deletion, potentially leaving orphaned references.
    """
    # Check if table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'session_messages' not in inspector.get_table_names():
        print("ℹ️  session_messages table doesn't exist, skipping")
        return

    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS on_session_message_deleted ON session_messages")

    # Drop function
    op.execute("DROP FUNCTION IF EXISTS set_tool_outputs_message_id_null()")

    print("✅ Removed message deletion trigger and function")
