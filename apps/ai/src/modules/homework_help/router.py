from fastapi import APIRouter

from src.api.dependencies import AuthDep
from src.core.exceptions import AppError, ForbiddenError
from src.core.rate_limit import limiter
from src.modules.homework_help import service as S

router = APIRouter(prefix="/homework-help", tags=["homework-help"])


@router.post("", response_model=S.HelpResponse)
async def help_me(body: S.HelpRequest, auth: AuthDep):
    if auth.role != "STUDENT" or auth.school_id is None:
        raise ForbiddenError("Homework help is for students")
    if not await limiter.allow(f"hwhelp:{auth.user_id}", limit=60):
        raise AppError("Let's take a short break and try again in a minute", code="rate_limited", status_code=429)
    return await S.help_student(body)
