"""Short-lived Gemini Live tokens for web and mobile voice.

The client authenticates with the same School backend JWT; the server keeps
GEMINI_API_KEY and returns a single-use ephemeral token (docs: ai.google.dev
gemini-api/docs/ephemeral-tokens). Ephemeral tokens only work on v1alpha/v1beta
BidiGenerateContentConstrained.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter

from src.api.dependencies import AuthDep
from src.core.config import get_settings
from src.core.exceptions import AppError, ForbiddenError, UpstreamError

logger = logging.getLogger("sybeez.ai.voice")

router = APIRouter(prefix="/voice", tags=["voice"])

TOKEN_URL = "https://generativelanguage.googleapis.com/v1alpha/auth_tokens"
CONSTRAINED_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContentConstrained"
)
SESSION_MINUTES = 30
START_WITHIN_MINUTES = 2


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post("/gemini/session")
async def gemini_session(auth: AuthDep):
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    settings = get_settings()
    if not settings.gemini_api_key:
        raise AppError("Voice is not configured", code="voice_unavailable", status_code=503)
    model = settings.gemini_live_model
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=SESSION_MINUTES)
    body = {
        "uses": 1,
        "expireTime": _iso(expires),
        "newSessionExpireTime": _iso(now + timedelta(minutes=START_WITHIN_MINUTES)),
        "bidiGenerateContentSetup": {
            "model": f"models/{model}",
            "generationConfig": {"responseModalities": ["AUDIO"]},
            "sessionResumption": {},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                TOKEN_URL, json=body, headers={"x-goog-api-key": settings.gemini_api_key}
            )
    except httpx.HTTPError as exc:
        logger.warning("gemini token request failed: %s", type(exc).__name__)
        raise UpstreamError("Voice provider unreachable") from None
    if response.status_code >= 400:
        logger.warning("gemini token request rejected: status=%s", response.status_code)
        raise UpstreamError("Voice provider rejected the session request")
    name = (response.json() or {}).get("name")
    if not name:
        raise UpstreamError("Voice provider returned no token")
    return {
        "value": name,
        "expires_at": _iso(expires),
        "ws_url": CONSTRAINED_WS_URL,
        "session": {"model": model, "provider": "gemini"},
    }
