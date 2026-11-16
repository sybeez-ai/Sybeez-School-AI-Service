"""Record that platform chats do not need new tables.

Revision ID: 0006_platform_chats
Revises: 0005_linked_reads

The AI role cannot CREATE in public and cannot CREATE SCHEMA on this database.
Platform chats are rows in ai_conversations (mode platform-chat or platform-voice)
with a sentinel school id. This revision only advances the version pointer.
"""

from typing import Sequence, Union

revision: str = "0006_platform_chats"
down_revision: Union[str, None] = "0005_linked_reads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
