"""Per-student learning profiles with audience RLS.

Revision ID: 0004_profiles
Revises: 0003_teacher
Create Date: 2026-10-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_profiles"
down_revision: Union[str, None] = "0003_teacher"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The table is created by the School backend migration 0066 (owner role, forced RLS).

    This service connects as sybeez_app, which cannot create tables or alter policies, so this
    revision only verifies that the table and its row level security are in place.
    """
    bind = op.get_bind()
    if "student_learning_profiles" not in set(sa.inspect(bind).get_table_names()):
        raise RuntimeError("student_learning_profiles is missing: deploy School backend migration 0066 first")
    forced = bind.execute(
        sa.text("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'student_learning_profiles'")
    ).scalar()
    if not forced:
        raise RuntimeError("student_learning_profiles must have FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    pass
