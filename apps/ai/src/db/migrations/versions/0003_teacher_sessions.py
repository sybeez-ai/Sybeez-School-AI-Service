"""Teacher sessions, lesson plans, board pages, and progress.

Revision ID: 0003_teacher
Revises: 0002_rls
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from src.db.rls import teacher_rls_downgrade_sql, teacher_rls_sql

revision: str = "0003_teacher"
down_revision: Union[str, None] = "0002_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEACHER_TABLES = (
    "teacher_progress",
    "teacher_messages",
    "teacher_board_actions",
    "teacher_board_pages",
    "teacher_lesson_plans",
    "teacher_sessions",
)


def upgrade() -> None:
    from src.db import models  # noqa: F401
    from src.db.base import Base

    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    names = set(_TEACHER_TABLES)
    for table in Base.metadata.sorted_tables:
        if table.name in names and table.name not in existing:
            table.create(bind=bind)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_teacher_sessions_guardians
        ON teacher_sessions USING gin (guardian_user_ids);
        CREATE INDEX IF NOT EXISTS ix_teacher_sessions_teachers
        ON teacher_sessions USING gin (teacher_user_ids);
        """
    )
    op.execute(teacher_rls_sql())


def downgrade() -> None:
    op.execute(teacher_rls_downgrade_sql())
    for name in _TEACHER_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
