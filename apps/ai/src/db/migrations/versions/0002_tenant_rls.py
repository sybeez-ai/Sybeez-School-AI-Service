"""Enable school row level security on AI-owned tables.

Revision ID: 0002_rls
Revises: 0001_ai
Create Date: 2026-10-11
"""

from typing import Sequence, Union

from alembic import op

from src.db.rls import rls_downgrade_sql, rls_sql

revision: str = "0002_rls"
down_revision: Union[str, None] = "0001_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(rls_sql())


def downgrade() -> None:
    op.execute(rls_downgrade_sql())
