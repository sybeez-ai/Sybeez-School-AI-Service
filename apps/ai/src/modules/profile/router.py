"""Per-student learning profile: written from the student's own outcomes, readable by the student,
linked parents and linked teachers (enforced by RLS), resettable by the student or a linked parent."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AuthDep, BearerToken, get_db
from src.core.exceptions import AppError, ForbiddenError, NotFoundError
from src.core.rate_limit import limiter
from src.core.security import require_school
from src.db.models import StudentLearningProfile
from src.modules.context.service import ContextService
from src.modules.profile import logic

logger = logging.getLogger("sybeez.ai.profile")
router = APIRouter(prefix="/profile", tags=["profile"])
STYLE = Literal["visual", "worked_examples", "stories", "step_by_step"]


class OutcomeEvent(BaseModel):
    kind: Literal["outcome", "speaking", "reading"]
    topic: str = Field(default="", max_length=120)
    correct: bool = False
    style: STYLE | None = None
    minutes: float = Field(default=0, ge=0, le=120)
    pages: int = Field(default=0, ge=0, le=200)


class CorrectRequest(BaseModel):
    style_override: STYLE | None = None
    clear_style: bool = False
    dismiss_topics: list[str] = Field(default_factory=list, max_length=20)


def _audit(auth, action: str, target) -> None:
    logger.info("profile_audit action=%s actor=%s role=%s target=%s", action, auth.user_id, auth.role, target)


async def _row(db: AsyncSession, student_user_id: UUID, *, any_id: bool = False) -> StudentLearningProfile | None:
    """any_id also matches the school-side student id (what parent screens hold)."""
    cond = StudentLearningProfile.student_user_id == student_user_id
    if any_id:
        cond = or_(cond, StudentLearningProfile.student_id == student_user_id)
    result = await db.execute(select(StudentLearningProfile).where(cond))
    return result.scalar_one_or_none()


@router.post("/events", status_code=202)
async def record_event(
    body: OutcomeEvent, db: Annotated[AsyncSession, Depends(get_db)], auth: AuthDep, bearer: BearerToken
):
    if not auth.is_student:
        raise ForbiddenError("Only students build their own learning profile")
    if not await limiter.allow(f"profile-event:{auth.user_id}", limit=120):
        raise AppError("Slow down a little", code="rate_limited", status_code=429)
    row = await _row(db, auth.user_id)
    if row is None:
        guardians: list[UUID] = []
        teachers: list[UUID] = []
        student_id = None
        try:
            ctx = await asyncio.wait_for(ContextService().for_user(auth, bearer_token=bearer), 4)
            guardians = [g.user_id for g in ctx.guardians]
            teachers = [t.user_id for t in ctx.teachers]
            student_id = ctx.student.id
        except Exception as exc:
            logger.info("profile context unavailable: %s", type(exc).__name__)
        row = StudentLearningProfile(
            school_id=require_school(auth), student_user_id=auth.user_id, student_id=student_id,
            guardian_user_ids=guardians, teacher_user_ids=teachers, data=logic.empty_profile(),
        )
        db.add(row)
    row.data = logic.apply_event(row.data, body.model_dump(exclude_none=True))
    await db.flush()
    return {"ok": True}


@router.get("/me")
async def my_profile(db: Annotated[AsyncSession, Depends(get_db)], auth: AuthDep):
    if not auth.is_student:
        raise ForbiddenError("Students only; use /profile/student/{id} for a linked student")
    row = await _row(db, auth.user_id)
    return logic.report(row.data if row else None)


@router.get("/student/{student_user_id}")
async def student_profile(student_user_id: UUID, db: Annotated[AsyncSession, Depends(get_db)], auth: AuthDep):
    if auth.role not in {"PARENT", "TEACHER"}:
        raise ForbiddenError("Only a linked parent or teacher can read a student's profile")
    row = await _row(db, student_user_id, any_id=True)  # RLS hides everyone else's students
    if row is None:
        # Same as a student's own empty profile: nothing learned yet. RLS already hides other
        # schools' and unlinked students, so this reveals no more than the old 404 did.
        return logic.report(None)
    _audit(auth, "read", student_user_id)
    return logic.report(row.data)


@router.post("/me/correct")
async def correct_profile(body: CorrectRequest, db: Annotated[AsyncSession, Depends(get_db)], auth: AuthDep):
    if not auth.is_student:
        raise ForbiddenError("Students only")
    row = await _row(db, auth.user_id)
    if row is None:
        raise NotFoundError("No learning profile yet")
    row.data = logic.correct(
        row.data, style_override=body.style_override, clear_style=body.clear_style, dismiss_topics=body.dismiss_topics
    )
    await db.flush()
    _audit(auth, "correct", auth.user_id)
    return logic.report(row.data)


@router.delete("/me")
async def reset_profile(db: Annotated[AsyncSession, Depends(get_db)], auth: AuthDep):
    if not auth.is_student:
        raise ForbiddenError("Students only")
    row = await _row(db, auth.user_id)
    if row is not None:
        row.data = logic.empty_profile()
        row.reset_at = datetime.now(UTC)
        await db.flush()
    _audit(auth, "reset", auth.user_id)
    return logic.report(None)


async def profile_prompt_block(auth, *, timeout: float = 2.0) -> str:
    """Teaching-style hints for the student's own voice/text session; never blocks on failure."""
    if not auth.is_student or auth.school_id is None:
        return ""
    from src.core.database import AsyncSessionLocal, install_tenant_context

    async def _load() -> str:
        async with AsyncSessionLocal() as session:
            install_tenant_context(session, school_id=auth.school_id, user_id=auth.user_id, role=auth.role)
            row = await _row(session, auth.user_id)
            return logic.prompt_block(row.data) if row else ""

    try:
        return await asyncio.wait_for(_load(), timeout)
    except Exception as exc:
        logger.info("profile unavailable: %s", type(exc).__name__)
        return ""


__all__ = ["router", "profile_prompt_block"]
