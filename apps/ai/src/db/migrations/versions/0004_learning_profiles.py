"""Per-student learning profiles with audience RLS.

Revision ID: 0004_profiles
Revises: 0003_teacher
Create Date: 2026-10-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from src.db.rls import profile_rls_downgrade_sql, profile_rls_sql
from src.db.sql_script import split_sql

revision: str = "0004_profiles"
down_revision: Union[str, None] = "0003_teacher"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from src.db import models  # noqa: F401
    from src.db.base import Base

    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name == "student_learning_profiles" and table.name not in existing:
            table.create(bind=bind)
    for statement in split_sql(profile_rls_sql()):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_sql(profile_rls_downgrade_sql()):
        op.execute(statement)
    op.execute("DROP TABLE IF EXISTS student_learning_profiles CASCADE")
