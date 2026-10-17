"""Reading buddy: mints a short Gemini Live token locked to one passage. Called only by Core,
which owns passages, daily caps, progress and audit; the browser never supplies the prompt."""

import hmac
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from src.api.dependencies import AuthDep
from src.core.config import get_settings
from src.core.exceptions import AppError, ForbiddenError, UpstreamError
from src.core.rate_limit import limiter
from src.modules.reading.prompt import SESSION_MINUTES, build_reading_prompt, build_reading_setup
from src.modules.voice.router import CONSTRAINED_WS_URL, TOKEN_URL, _iso

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
    if not settings.gemini_api_key:
        raise AppError("Voice is not configured", code="voice_unavailable", status_code=503)
    if not await limiter.allow(f"reading-mint:{auth.user_id}", limit=4):
        raise AppError("Please wait a moment", code="rate_limited", status_code=429)
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=SESSION_MINUTES)
    token_body = {
        "uses": 1,
        "expireTime": _iso(expires),
        "newSessionExpireTime": _iso(now + timedelta(minutes=2)),
        "fieldMask": "model,generationConfig,sessionResumption",
        "bidiGenerateContentSetup": {
            "model": f"models/{settings.gemini_live_model}",
            "generationConfig": {"responseModalities": ["AUDIO"]},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(TOKEN_URL, json=token_body, headers={"x-goog-api-key": settings.gemini_api_key})
    except httpx.HTTPError as exc:
        logger.warning("reading token request failed: %s", type(exc).__name__)
        raise UpstreamError("Voice provider unreachable") from None
    if response.status_code >= 400:
        logger.warning("reading token rejected: status=%s", response.status_code)
        raise UpstreamError("Voice provider rejected the session request")
    name = (response.json() or {}).get("name")
    if not name:
        raise UpstreamError("Voice provider returned no token")
    prompt = build_reading_prompt(body.passage, body.class_level)
    return {
        "value": name,
        "expires_at": _iso(expires),
        "ws_url": CONSTRAINED_WS_URL,
        "setup": build_reading_setup(settings, system_prompt=prompt),
        "session": {"model": settings.gemini_live_model, "provider": "gemini", "max_minutes": SESSION_MINUTES},
    }
