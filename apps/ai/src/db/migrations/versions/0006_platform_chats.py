"""Platform assistant conversations, owned by the signed-in user.

Revision ID: 0006_platform_chats
Revises: 0005_linked_reads
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_platform_chats"
down_revision: Union[str, None] = "0005_linked_reads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The app role cannot create tables in public on this Postgres.
    # It can create a schema it owns, which is where these chats live.
    op.execute("CREATE SCHEMA IF NOT EXISTS platform_assistant")
    op.create_table(
        "platform_assistant_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="platform_assistant",
    )
    op.create_index(
        "ix_platform_assistant_conversations_user_id",
        "platform_assistant_conversations",
        ["user_id"],
        schema="platform_assistant",
    )
    op.create_table(
        "platform_assistant_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_assistant.platform_assistant_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="platform_assistant",
    )
    op.create_index(
        "ix_platform_assistant_messages_conversation_id",
        "platform_assistant_messages",
        ["conversation_id"],
        schema="platform_assistant",
    )


def downgrade() -> None:
    op.drop_table("platform_assistant_messages", schema="platform_assistant")
    op.drop_table("platform_assistant_conversations", schema="platform_assistant")
    op.execute("DROP SCHEMA IF EXISTS platform_assistant")
