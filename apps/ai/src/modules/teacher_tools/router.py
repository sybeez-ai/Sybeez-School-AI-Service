import hmac
from typing import Annotated

from fastapi import APIRouter, Header

from src.api.dependencies import AuthDep
from src.core.config import get_settings
from src.core.exceptions import AppError, ForbiddenError
from src.core.rate_limit import limiter
from src.modules.teacher_tools import service as S

router = APIRouter(prefix="/teacher-tools", tags=["teacher-tools"])


async def _guard(auth, token: str | None, bucket: str, limit: int) -> None:
    if auth.role not in {"TEACHER", "SCHOOL_ADMIN"} or auth.school_id is None:
        raise ForbiddenError("Only teachers and school admins can use these tools")
    expected = get_settings().core_internal_token
    if not token or not hmac.compare_digest(token, expected):
        raise ForbiddenError("Only available through the school platform")
    if not await limiter.allow(f"tt:{bucket}:{auth.user_id}", limit=limit):
        raise AppError("Slow down a little", code="rate_limited", status_code=429)


@router.post("/draft", response_model=S.DraftResponse)
async def draft(body: S.DraftRequest, auth: AuthDep, x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None):
    await _guard(auth, x_internal_token, "draft", 20)
    return await S.draft(body)


@router.post("/grade", response_model=S.GradeResponse)
async def grade(body: S.GradeRequest, auth: AuthDep, x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None):
    await _guard(auth, x_internal_token, "grade", 120)
    return await S.grade(body)
