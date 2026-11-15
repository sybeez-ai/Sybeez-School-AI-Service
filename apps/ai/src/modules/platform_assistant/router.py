"""AI assistant for the Sybeez platform console (super admin and platform team).

Platform sessions carry no school, so the school chat (conversations stored per school,
student learning context) does not apply. This endpoint is stateless: the browser sends
the recent turns and the page the operator is on; nothing is stored.
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.api.dependencies import AuthDep, BearerToken
from src.core.exceptions import AppError, ForbiddenError, UpstreamError
from src.core.rate_limit import limiter
from src.modules.platform_assistant.prompt import (
    PLATFORM_ROLES,
    PLATFORM_SYSTEM,
    plain_markdown,
    platform_page_context,
)
from src.modules.usage.report import publish_llm_usage
from src.modules.usage.tokens import usage_start
from src.providers.llm import get_llm, guarded_complete

router = APIRouter(prefix="/platform-assistant", tags=["platform-assistant"])

SYSTEM = PLATFORM_SYSTEM


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class PlatformChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[Turn] = Field(default_factory=list, max_length=20)
    page: str | None = Field(default=None, max_length=200)


class PlatformChatResponse(BaseModel):
    reply: str


@router.post("/chat", response_model=PlatformChatResponse)
async def platform_chat(body: PlatformChatRequest, auth: AuthDep, bearer: BearerToken) -> PlatformChatResponse:
    if auth.role not in PLATFORM_ROLES:
        raise ForbiddenError("The platform assistant is only for the Sybeez platform team")
    if not await limiter.allow(f"platform-assistant:{auth.user_id}", limit=30):
        raise AppError("Too many messages, try again shortly", code="rate_limited", status_code=429)
    history = "\n".join(f"{t.role}: {t.content}" for t in body.history[-12:])
    page_line = platform_page_context(body.page, limit=200)
    user = (
        (f"{page_line}\n\n" if page_line else "")
        + (f"=== CONVERSATION ===\n{history}\n\n" if history else "")
        + f"user: {body.message}\n\nRespond as the platform AI assistant."
    )
    llm = get_llm()
    started = usage_start(llm)
    try:
        reply = plain_markdown(await guarded_complete(llm, system=SYSTEM, user=user))
    except UpstreamError:
        reply = "The AI assistant could not answer just now. Please try again in a moment."
    else:
        await publish_llm_usage(llm, auth=auth, bearer=bearer, capability="CHAT", start=started)
    return PlatformChatResponse(reply=reply)
