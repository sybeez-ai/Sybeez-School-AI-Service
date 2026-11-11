"""Let a newly linked parent read existing AI lessons.

Revision ID: 0005_linked_reads
Revises: 0004_profiles
Create Date: 2026-11-11

Replaces the teacher-session read policies in place. No rows are deleted.
The write check is unchanged: only the student can change a lesson.
"""

import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from src.db.rls import teacher_rls_sql
from src.db.sql_script import split_sql

revision: str = "0005_linked_reads"
down_revision: Union[str, None] = "0004_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Previous read rule, kept so downgrade does not drop the tables.
_PREVIOUS_SESSION_USING = (
    "school_id = NULLIF(current_setting('app.school_id', true), '')::uuid AND ("
    "student_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid OR "
    "NULLIF(current_setting('app.user_id', true), '')::uuid = ANY(guardian_user_ids) OR "
    "NULLIF(current_setting('app.user_id', true), '')::uuid = ANY(teacher_user_ids))"
)
_PREVIOUS_SESSION_CHECK = (
    "school_id = NULLIF(current_setting('app.school_id', true), '')::uuid AND "
    "student_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid"
)
_CHILD_TABLES = (
    "teacher_lesson_plans",
    "teacher_board_pages",
    "teacher_board_actions",
    "teacher_messages",
    "teacher_progress",
)


def upgrade() -> None:
    """Replace the read rule when this login owns the lesson tables.

    The school app login is not always the table owner. Skipping in that case
    keeps the deploy moving; a database owner can apply the same statements.
    """
    bind = op.get_bind()
    found = bind.execute(
        sa.text(
            """
            SELECT pg_get_userbyid(c.relowner) AS owner,
                   current_user AS me,
                   pg_has_role(current_user, c.relowner, 'member') AS can_manage
            FROM pg_class c
            WHERE c.relname = 'teacher_sessions' AND c.relkind = 'r'
            LIMIT 1
            """
        )
    ).fetchone()
    if found is None:
        raise RuntimeError("teacher_sessions is missing; cannot update the lesson read rule")
    owner = str(found[0] or "")
    me = str(found[1] or "")
    can_manage = bool(found[2])
    print(f"LESSON_POLICY owner={owner} me={me} can_manage={can_manage}", flush=True)
    if not can_manage:
        print(
            "LESSON_POLICY skipped: this login cannot change the lesson read rule. "
            "A newly linked parent still cannot see older lessons until the table owner applies it.",
            flush=True,
        )
        return
    switched = False
    if owner and owner != me:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", owner):
            raise RuntimeError("unexpected lesson table owner name")
        op.execute(sa.text(f'SET ROLE "{owner}"'))
        switched = True
    try:
        for statement in split_sql(teacher_rls_sql()):
            op.execute(sa.text(statement))
    finally:
        if switched:
            op.execute(sa.text("RESET ROLE"))


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS teacher_sessions_audience ON teacher_sessions")
    op.execute(
        "CREATE POLICY teacher_sessions_audience ON teacher_sessions "
        f"USING ({_PREVIOUS_SESSION_USING}) WITH CHECK ({_PREVIOUS_SESSION_CHECK})"
    )
    user = "NULLIF(current_setting('app.user_id', true), '')::uuid"
    school = "school_id = NULLIF(current_setting('app.school_id', true), '')::uuid"
    read_audience = (
        f"(s.student_user_id = {user} OR {user} = ANY(s.guardian_user_ids) "
        f"OR {user} = ANY(s.teacher_user_ids))"
    )
    write_audience = f"s.student_user_id = {user}"
    for table in _CHILD_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_audience ON {table}")
        op.execute(
            f"CREATE POLICY {table}_audience ON {table} "
            f"USING ({school} AND EXISTS (SELECT 1 FROM teacher_sessions s "
            f"WHERE s.id = {table}.session_id AND s.school_id = {table}.school_id AND {read_audience})) "
            f"WITH CHECK ({school} AND EXISTS (SELECT 1 FROM teacher_sessions s "
            f"WHERE s.id = {table}.session_id AND s.school_id = {table}.school_id AND {write_audience}))"
        )
