import hmac
from typing import Annotated

from fastapi import APIRouter, Header

from src.api.dependencies import AuthDep
from src.core.config import get_settings
from src.core.exceptions import ForbiddenError
from src.core.rate_limit import limiter
from src.modules.translate.schemas import TranslateRequest, TranslateResponse
from src.modules.translate.service import TranslateService

router = APIRouter(prefix="/translate", tags=["translate"])


@router.post("/notice", response_model=TranslateResponse)
async def translate_notice(
    body: TranslateRequest,
    auth: AuthDep,
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
):
    """Translate a school notice. Called only by Core, which owns caching, review and audit."""
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    expected = get_settings().core_internal_token
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise ForbiddenError("Translation is only available through the school platform")
    if not await limiter.allow(f"translate:{auth.school_id}", limit=60):
        from src.core.exceptions import AppError

        raise AppError("Too many translations, try again shortly", code="rate_limited", status_code=429)
    return await TranslateService().translate(body)
