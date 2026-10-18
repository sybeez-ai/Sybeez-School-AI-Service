"""Short-lived Gemini Live tokens plus the agent endpoints (plan, text fallback).

The client authenticates with the same School backend JWT; the server keeps
GEMINI_API_KEY and returns a single-use ephemeral token (docs: ai.google.dev
gemini-api/docs/ephemeral-tokens). Ephemeral tokens only work on v1alpha/v1beta
BidiGenerateContentConstrained.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.api.dependencies import AuthDep, BearerToken
from src.core.config import get_settings
from src.core.exceptions import AppError, ForbiddenError, UpstreamError
from src.core.rate_limit import limiter
from src.modules.context.features import disabled_labels, prompt_block
from src.modules.context.service import ContextService
from src.modules.profile.router import profile_prompt_block
from src.modules.voice import agent
from src.providers.gemini_live import build_gemini_live_setup, build_system_prompt
from src.providers.llm import get_llm

logger = logging.getLogger("sybeez.ai.voice")

router = APIRouter(prefix="/voice", tags=["voice"])

TOKEN_URL = "https://generativelanguage.googleapis.com/v1alpha/auth_tokens"
CONSTRAINED_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContentConstrained"
)
SESSION_MINUTES = 15  # hard cap per Live session (cost control)
START_WITHIN_MINUTES = 2
MINTS_PER_MINUTE = 6
CONTEXT_TIMEOUT_SECONDS = 3.0


class SessionRequest(BaseModel):
    page: str = Field(default="", max_length=120)
    portal: str = Field(default="student", max_length=20)


class AuditEvent(BaseModel):
    """One agent action, reported by the browser right after a tool ran. Never carries typed values."""

    tool: str = Field(max_length=64, pattern=r"^[a-z_0-9]+$")
    ok: bool
    portal: str = Field(default="student", max_length=24)
    page: str = Field(default="", max_length=200)
    target: str = Field(default="", max_length=120)
    confirmed: bool = False
    detail: str = Field(default="", max_length=200)


class StepMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant|tool)$")
    content: str | None = Field(default=None, max_length=6000)
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = Field(default=None, max_length=64)


class StepRequest(BaseModel):
    messages: list[StepMessage] = Field(min_length=1, max_length=40)
    tools: list[dict] = Field(default_factory=list, max_length=48)
    page: str = Field(default="", max_length=200)
    portal: str = Field(default="student", max_length=24)


class PlanRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    subject: str = Field(default="", max_length=60)
    language: str = Field(default="English", max_length=30)


class TextRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    page: str = Field(default="", max_length=120)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _student_context(auth, bearer: str | None):
    """Authorized class/subject/lesson context from Core; never blocks voice if Core is slow."""
    try:
        ctx = await asyncio.wait_for(ContextService().for_user(auth, bearer_token=bearer), CONTEXT_TIMEOUT_SECONDS)
        return ctx.as_prompt_block(), ctx.grade_band
    except Exception as exc:
        logger.info("voice context unavailable: %s", type(exc).__name__)
        return "", None


@router.post("/gemini/session")
async def gemini_session(auth: AuthDep, bearer: BearerToken, body: SessionRequest | None = None):
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    settings = get_settings()
    if not settings.gemini_api_key:
        raise AppError("Voice is not configured", code="voice_unavailable", status_code=503)
    if not await limiter.allow(f"voice-mint:{auth.user_id}", limit=MINTS_PER_MINUTE):
        raise AppError("Too many voice sessions, try again shortly", code="rate_limited", status_code=429)
    model = settings.gemini_live_model
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=SESSION_MINUTES)
    token_body = {
        "uses": 1,
        "expireTime": _iso(expires),
        "newSessionExpireTime": _iso(now + timedelta(minutes=START_WITHIN_MINUTES)),
        # Without a fieldMask Google locks the WHOLE setup to the token's copy, which silently drops
        # the client's systemInstruction and tools (the model then chats but never calls a tool).
        # Lock only model/generationConfig/sessionResumption; prompt and tools come from the setup.
        "fieldMask": "model,generationConfig,sessionResumption",
        "bidiGenerateContentSetup": {
            "model": f"models/{model}",
            "generationConfig": {"responseModalities": ["AUDIO"]},
            "sessionResumption": {},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                TOKEN_URL, json=token_body, headers={"x-goog-api-key": settings.gemini_api_key}
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
    (context_block, grade_band), profile_block, off = await asyncio.gather(
        _student_context(auth, bearer), profile_prompt_block(auth), disabled_labels(bearer)
    )
    if off:
        context_block = (context_block + "\n" + prompt_block(off)).strip()
    prompt = build_system_prompt(
        context_block, grade_band if (not body or body.portal == "student") else None,
        (body.page if body else ""), (body.portal if body else "student"), profile_block,
    )
    return {
        "value": name,
        "expires_at": _iso(expires),
        "ws_url": CONSTRAINED_WS_URL,
        "setup": build_gemini_live_setup(settings, system_prompt=prompt),
        "session": {"model": model, "voice": settings.gemini_live_voice, "provider": "gemini",
                    "max_minutes": SESSION_MINUTES},
    }


@router.post("/agent/plan")
async def agent_plan(body: PlanRequest, auth: AuthDep, bearer: BearerToken):
    """Qwen builds a guarded lesson outline (speech + board label + which tab) for the agent."""
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    if not await limiter.allow(f"voice-plan:{auth.user_id}", limit=20):
        raise AppError("Slow down a little", code="rate_limited", status_code=429)
    _, grade_band = await _student_context(auth, bearer)
    try:
        plan = await agent.make_plan(
            get_llm(), topic=body.topic, subject=body.subject, grade_band=grade_band, language=body.language
        )
    except PermissionError:
        message = agent.refusal_for(body.topic, grade_band) or "Let's pick a school topic."
        return {"allowed": False, "message": message}
    return {"allowed": True, **plan.model_dump()}


@router.post("/agent/text")
async def agent_text(body: TextRequest, auth: AuthDep, bearer: BearerToken):
    """Text fallback when Live voice is unavailable (Qwen, same safety rules)."""
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    if not await limiter.allow(f"voice-text:{auth.user_id}", limit=30):
        raise AppError("Slow down a little", code="rate_limited", status_code=429)
    context_block, grade_band = await _student_context(auth, bearer)
    try:
        reply = await agent.text_answer(
            get_llm(), message=body.message, context_block=context_block, grade_band=grade_band, page=body.page
        )
    except Exception as exc:
        logger.warning("text fallback failed: %s", type(exc).__name__)
        raise UpstreamError("Teacher is busy, please try again") from None
    return {"reply": reply}


@router.post("/agent/audit", status_code=202)
async def agent_audit(body: AuditEvent, auth: AuthDep):
    """Audit trail of what Sybeez did for a user (structured log line in CloudWatch)."""
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    if not await limiter.allow(f"voice-audit:{auth.user_id}", limit=240):
        raise AppError("Too many audit events", code="rate_limited", status_code=429)
    logger.info(
        "agent_audit user=%s school=%s portal=%s tool=%s ok=%s confirmed=%s page=%r target=%r detail=%r",
        auth.user_id, auth.school_id, body.portal, body.tool, body.ok, body.confirmed,
        body.page, body.target, body.detail,
    )
    return {"recorded": True}


@router.post("/agent/step")
async def agent_step(body: StepRequest, auth: AuthDep, bearer: BearerToken):
    """One step of the typed (text) agent loop on Qwen. Same tools and persona as voice."""
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    if not await limiter.allow(f"voice-step:{auth.user_id}", limit=90):
        raise AppError("Slow down a little", code="rate_limited", status_code=429)
    student = body.portal == "student"
    (context_block, grade_band), off = await asyncio.gather(_student_context(auth, bearer), disabled_labels(bearer))
    extra = f"Portal: {body.portal[:24]}. Current page: {body.page[:100]}."
    if context_block:
        extra += "\nUser context (authoritative):\n" + context_block[:1200]
    if off:
        extra += "\n" + prompt_block(off)
    if student:
        extra += "\n" + (await profile_prompt_block(auth))[:900]
    messages = []
    for m in body.messages:
        item: dict = {"role": m.role, "content": m.content or ""}
        if m.tool_calls:
            item["tool_calls"] = m.tool_calls[:6]
        if m.role == "tool":
            item["tool_call_id"] = m.tool_call_id or ""
        messages.append(item)
    result = await agent.agent_step(
        messages=messages, declarations=body.tools, system_extra=extra,
        grade_band=grade_band if student else None, student=student,
    )
    logger.info("agent_step user=%s portal=%s provider=%s tool_calls=%d", auth.user_id, body.portal,
                result["provider"], len(result["message"].get("tool_calls") or []))
    return result
