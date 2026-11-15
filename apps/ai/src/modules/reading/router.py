"""Reading buddy session. Called only by Core, which owns passages, caps, and audit.

The child is heard with Amazon Transcribe and prompted with Amazon Polly.
Gemini is not called. The browser never supplies the prompt.
"""

import hmac
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from src.api.dependencies import AuthDep
from src.core.budget import DAILY_LIMIT_MESSAGE, allow_voice
from src.core.config import get_settings
from src.core.exceptions import AppError, ForbiddenError
from src.core.rate_limit import limiter
from src.modules.reading.prompt import SESSION_MINUTES
from src.modules.voice.router import _iso

logger = logging.getLogger("sybeez.ai.reading")
router = APIRouter(prefix="/reading", tags=["reading"])


class ReadingSessionRequest(BaseModel):
    passage: str = Field(min_length=10, max_length=1500)
    class_level: int = Field(ge=1, le=5)


@router.post("/gemini/session")
async def reading_session(
    body: ReadingSessionRequest,
    auth: AuthDep,
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
):
    if auth.role != "STUDENT" or auth.school_id is None:
        raise ForbiddenError("The reading buddy is for students")
    settings = get_settings()
    if not x_internal_token or not hmac.compare_digest(x_internal_token, settings.core_internal_token):
        raise ForbiddenError("Reading sessions start from the school platform")
    if not await limiter.allow(f"reading-mint:{auth.user_id}", limit=4):
        raise AppError("Please wait a moment", code="rate_limited", status_code=429)
    if not await allow_voice(auth):
        raise AppError(DAILY_LIMIT_MESSAGE, code="rate_limited", status_code=429)
    from src.providers.bedrock_chat import nova_lite_model_id

    now = datetime.now(UTC)
    expires = now + timedelta(minutes=SESSION_MINUTES)
    region = (settings.aws_region or "").strip() or "ap-south-1"
    return {
        "value": "aws",
        "expires_at": _iso(expires),
        "ws_url": "",
        "setup": {"provider": "aws", "engine": "transcribe-polly"},
        "session": {
            "model": nova_lite_model_id(region, settings.bedrock_model_id),
            "provider": "aws",
            "max_minutes": SESSION_MINUTES,
        },
    }
