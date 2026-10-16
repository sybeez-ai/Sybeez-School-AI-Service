import hmac
from typing import Annotated

from fastapi import APIRouter, Header

from src.api.dependencies import AuthDep
from src.core.config import get_settings
from src.core.exceptions import ForbiddenError
from src.modules.mcq.schemas import McqGenerateRequest, McqGenerateResponse
from src.modules.mcq.service import McqService

router = APIRouter(prefix="/mcq", tags=["mcq"])


@router.post("/generate", response_model=McqGenerateResponse)
async def generate_mcq(
    body: McqGenerateRequest,
    auth: AuthDep,
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
):
    """Draft MCQs for a teacher to review. Called by Core, which enforces the school's monthly cap."""
    if auth.role not in {"TEACHER", "SCHOOL_ADMIN"} or auth.school_id is None:
        raise ForbiddenError("Only teachers and school admins can generate test questions")
    expected = get_settings().core_internal_token
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise ForbiddenError("Question generation is only available through the school platform")
    return await McqService().generate(body)
