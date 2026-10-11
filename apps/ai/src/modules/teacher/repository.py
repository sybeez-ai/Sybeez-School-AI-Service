"""Persist teacher sessions. Reads are limited to the student and linked adults."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.security import AuthContext
from src.db.models.teacher import (
    TeacherBoardAction,
    TeacherBoardPage,
    TeacherLessonPlan,
    TeacherMessage,
    TeacherProgress,
    TeacherSession,
)
from src.modules.teacher.access import audience_condition
from src.modules.teacher.records import ActionRecord, MessageRecord, PageRecord, ProgressRecord, SessionRecord
from src.shared.utils import utcnow


class SqlTeacherStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, record: SessionRecord) -> SessionRecord:
        self.db.add(self._row(record))
        await self.db.flush()
        await self._insert_children(record, plans=set(), pages=set(), actions=set(), messages=set())
        await self._upsert_progress(record)
        await self.db.flush()
        return record

    async def save(self, record: SessionRecord) -> SessionRecord:
        row = await self.db.get(TeacherSession, record.id)
        if row is None:
            return await self.create(record)
        self._apply(row, record)
        known = await self._known(record.id)
        await self._insert_children(record, **known)
        await self._upsert_progress(record)
        await self.db.flush()
        return record

    async def get(self, auth: AuthContext, session_id: UUID) -> SessionRecord | None:
        if auth.school_id is None:
            return None
        stmt = (
            select(TeacherSession)
            .where(
                TeacherSession.id == session_id,
                TeacherSession.school_id == auth.school_id,
                audience_condition(auth),
            )
            .options(
                selectinload(TeacherSession.plans),
                selectinload(TeacherSession.pages),
                selectinload(TeacherSession.actions),
                selectinload(TeacherSession.messages),
                selectinload(TeacherSession.progress_rows),
            )
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return self._record(row, with_children=True)

    async def list(self, auth: AuthContext, limit: int = 50) -> list[SessionRecord]:
        if auth.school_id is None:
            return []
        stmt = (
            select(TeacherSession)
            .where(TeacherSession.school_id == auth.school_id, audience_condition(auth))
            .order_by(TeacherSession.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self._record(row, with_children=False) for row in rows]

    def _row(self, record: SessionRecord) -> TeacherSession:
        row = TeacherSession(id=record.id, school_id=record.school_id, student_user_id=record.student_user_id)
        self._apply(row, record)
        return row

    def _apply(self, row: TeacherSession, record: SessionRecord) -> None:
        row.school_id = record.school_id
        row.student_user_id = record.student_user_id
        row.student_id = record.student_id
        row.guardian_user_ids = list(record.guardian_user_ids)
        row.teacher_user_ids = list(record.teacher_user_ids)
        row.subject_id = record.subject_id
        row.class_id = record.class_id
        row.conversation_id = record.conversation_id
        row.title = record.title
        row.topic = record.topic
        row.status = record.status
        row.phase = record.phase
        row.grade_band = record.grade_band
        row.step_index = record.step_index
        row.attempt = record.attempt
        row.turn_index = record.turn_index
        row.awaiting_check = record.awaiting_check
        row.expected_answer = record.expected_answer
        row.check_prompt = record.check_prompt
        row.check_kind = record.check_kind
        row.check_choices = list(record.check_choices)
        row.internal_notes = record.internal_notes
        row.updated_at = record.updated_at or utcnow()

    async def _known(self, session_id: UUID) -> dict:
        plans = await self.db.execute(select(TeacherLessonPlan.version).where(TeacherLessonPlan.session_id == session_id))
        pages = await self.db.execute(select(TeacherBoardPage.id).where(TeacherBoardPage.session_id == session_id))
        actions = await self.db.execute(select(TeacherBoardAction.id).where(TeacherBoardAction.session_id == session_id))
        messages = await self.db.execute(select(TeacherMessage.id).where(TeacherMessage.session_id == session_id))
        return {
            "plans": set(plans.scalars().all()),
            "pages": set(pages.scalars().all()),
            "actions": set(actions.scalars().all()),
            "messages": set(messages.scalars().all()),
        }

    async def _insert_children(self, record: SessionRecord, *, plans: set, pages: set, actions: set, messages: set) -> None:
        if record.plan is not None and record.plan_version not in plans:
            self.db.add(
                TeacherLessonPlan(
                    school_id=record.school_id,
                    session_id=record.id,
                    version=record.plan_version,
                    plan=record.plan,
                )
            )
        for page in record.pages:
            if page.id in pages:
                continue
            self.db.add(
                TeacherBoardPage(
                    id=page.id,
                    school_id=record.school_id,
                    session_id=record.id,
                    page_index=page.page_index,
                    title=page.title,
                )
            )
        await self.db.flush()
        for action in record.actions:
            if action.id in actions:
                continue
            self.db.add(
                TeacherBoardAction(
                    id=action.id,
                    school_id=record.school_id,
                    session_id=record.id,
                    page_id=action.page_id,
                    seq=action.seq,
                    turn_index=action.turn_index,
                    at_ms=action.at_ms,
                    action=action.action,
                )
            )
        for message in record.messages:
            if message.id in messages:
                continue
            self.db.add(
                TeacherMessage(
                    id=message.id,
                    school_id=record.school_id,
                    session_id=record.id,
                    role=message.role,
                    content=message.content,
                    turn_index=message.turn_index,
                    created_at=message.created_at,
                )
            )

    async def _upsert_progress(self, record: SessionRecord) -> None:
        for item in record.progress:
            stmt = select(TeacherProgress).where(
                TeacherProgress.session_id == record.id,
                TeacherProgress.concept == item.concept,
            )
            row = (await self.db.execute(stmt)).scalar_one_or_none()
            if row is None:
                self.db.add(
                    TeacherProgress(
                        id=item.id,
                        school_id=record.school_id,
                        session_id=record.id,
                        student_id=record.student_id,
                        concept=item.concept,
                        status=item.status,
                        score=item.score,
                        notes=item.notes,
                    )
                )
            else:
                row.status = item.status
                row.score = item.score
                row.notes = item.notes
                item.id = row.id

    def _record(self, row: TeacherSession, *, with_children: bool) -> SessionRecord:
        record = SessionRecord(
            id=row.id,
            school_id=row.school_id,
            student_user_id=row.student_user_id,
            student_id=row.student_id,
            guardian_user_ids=list(row.guardian_user_ids or []),
            teacher_user_ids=list(row.teacher_user_ids or []),
            subject_id=row.subject_id,
            class_id=row.class_id,
            conversation_id=row.conversation_id,
            title=row.title,
            topic=row.topic or "",
            status=row.status,
            phase=row.phase,
            grade_band=row.grade_band,
            step_index=row.step_index,
            attempt=row.attempt,
            turn_index=row.turn_index,
            awaiting_check=row.awaiting_check,
            expected_answer=row.expected_answer or "",
            check_prompt=row.check_prompt or "",
            check_kind=row.check_kind or "ask",
            check_choices=list(row.check_choices or []),
            internal_notes=row.internal_notes or "",
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        if not with_children:
            return record
        plans = sorted(row.plans, key=lambda item: item.version)
        if plans:
            record.plan = plans[-1].plan
            record.plan_version = plans[-1].version
        record.pages = [
            PageRecord(id=page.id, page_index=page.page_index, title=page.title)
            for page in sorted(row.pages, key=lambda item: item.page_index)
        ]
        record.actions = [
            ActionRecord(
                id=action.id,
                page_id=action.page_id,
                seq=action.seq,
                turn_index=action.turn_index,
                at_ms=action.at_ms,
                action=action.action,
            )
            for action in sorted(row.actions, key=lambda item: item.seq)
        ]
        record.messages = [
            MessageRecord(
                id=message.id,
                role=message.role,
                content=message.content,
                turn_index=message.turn_index,
                created_at=message.created_at,
            )
            for message in sorted(row.messages, key=lambda item: item.created_at)
        ]
        record.progress = [
            ProgressRecord(
                id=item.id,
                concept=item.concept,
                status=item.status,
                score=item.score,
                notes=item.notes,
            )
            for item in row.progress_rows
        ]
        return record
