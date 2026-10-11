"""Who may read or continue a lesson.

Students continue their own lessons. Parents and teachers may open a lesson only
when Core linked them to that student at session start (and on later student turns).
School and platform admins are not given a blanket view of student lessons.
"""

import copy
from uuid import UUID

from sqlalchemy import cast, false
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from src.core.security import AuthContext
from src.modules.teacher.records import SessionRecord


def same_school(auth: AuthContext, school_id: UUID) -> bool:
    return auth.school_id is not None and auth.school_id == school_id


def role_can_read(auth: AuthContext, session: SessionRecord) -> bool:
    if not same_school(auth, session.school_id):
        return False
    if auth.role == "STUDENT":
        return session.student_user_id == auth.user_id
    if auth.role == "PARENT":
        return auth.user_id in session.guardian_user_ids
    if auth.role == "TEACHER":
        return auth.user_id in session.teacher_user_ids
    return False


def role_can_write(auth: AuthContext, session: SessionRecord) -> bool:
    return auth.role == "STUDENT" and same_school(auth, session.school_id) and session.student_user_id == auth.user_id


def _uuid_array(user_id: UUID):
    return cast(array([user_id]), ARRAY(PG_UUID(as_uuid=True)))


def audience_condition(auth: AuthContext):
    """SQL twin of role_can_read. School id is applied by the caller as well."""
    from src.db.models.teacher import TeacherSession

    if auth.role == "STUDENT":
        return TeacherSession.student_user_id == auth.user_id
    if auth.role == "PARENT":
        return TeacherSession.guardian_user_ids.op("@>")(_uuid_array(auth.user_id))
    if auth.role == "TEACHER":
        return TeacherSession.teacher_user_ids.op("@>")(_uuid_array(auth.user_id))
    return false()


def public_plan(plan: dict | None, *, role: str) -> dict | None:
    if not plan:
        return None
    data = copy.deepcopy(plan)
    data.pop("reasoning", None)
    steps = []
    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        item = dict(step)
        item.pop("reasoning", None)
        if role == "STUDENT":
            item.pop("expected_answer", None)
        steps.append(item)
    data["steps"] = steps
    return data


def linked_ids(people) -> list[UUID]:
    found: list[UUID] = []
    for person in people or []:
        user_id = getattr(person, "user_id", None)
        if isinstance(user_id, UUID) and user_id not in found:
            found.append(user_id)
    return found
