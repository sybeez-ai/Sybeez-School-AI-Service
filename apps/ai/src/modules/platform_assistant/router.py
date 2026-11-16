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
    PLATFORM_TOOL_NOTE,
    platform_page_context,
)
from src.modules.platform_assistant.tools import apply_platform_tool_policy, with_platform_tools
from src.modules.usage.report import publish_usage
from src.modules.usage.tokens import usage_record
from src.modules.voice import agent

router = APIRouter(prefix="/platform-assistant", tags=["platform-assistant"])

SYSTEM = PLATFORM_SYSTEM + "\n" + PLATFORM_TOOL_NOTE


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ToolDeclaration(BaseModel):
    name: str = Field(max_length=64)
    description: str = Field(default="", max_length=800)
    parameters: dict = Field(default_factory=dict)


class PlatformChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[Turn] = Field(default_factory=list, max_length=20)
    page: str | None = Field(default=None, max_length=200)
    tools: list[ToolDeclaration] = Field(default_factory=list, max_length=48)
    conversation_id: str | None = None
    channel: str = "chat"


class PlatformChatResponse(BaseModel):
    reply: str
    message: dict
    confirmation_required: bool = False
    executed: bool = True
    conversation_id: str | None = None


def _declarations(tools: list[ToolDeclaration]) -> list[dict]:
    provided = [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters or {"type": "OBJECT", "properties": {}},
        }
        for tool in tools
    ]
    return with_platform_tools(provided)


@router.post("/chat", response_model=PlatformChatResponse)
async def platform_chat(body: PlatformChatRequest, auth: AuthDep, bearer: BearerToken) -> PlatformChatResponse:
    if auth.role not in PLATFORM_ROLES:
        raise ForbiddenError("The platform assistant is only for the Sybeez platform team")
    if not await limiter.allow(f"platform-assistant:{auth.user_id}", limit=30):
        raise AppError("Too many messages, try again shortly", code="rate_limited", status_code=429)
    from src.modules.platform_assistant.memory import remember_turn

    stored = await remember_turn(
        user_id=auth.user_id,
        conversation_id=body.conversation_id,
        channel=body.channel,
        user_text=body.message,
        history=[{"role": turn.role, "content": turn.content} for turn in body.history],
    )
    messages = stored.history
    messages.append({"role": "user", "content": body.message})
    page_line = platform_page_context(body.page, limit=200)
    try:
        result = await agent.agent_step(
            messages=messages,
            declarations=_declarations(body.tools),
            system_extra=page_line,
            system_override=SYSTEM,
        )
    except UpstreamError:
        await stored.close()
        reply = "The AI assistant could not answer just now. Please try again in a moment."
        return PlatformChatResponse(
            reply=reply, message={"role": "assistant", "content": reply}, conversation_id=stored.conversation_id
        )
    usage = result.pop("usage", None)
    if usage is not None:
        await publish_usage(
            usage_record(usage, school_id=auth.school_id, user_id=auth.user_id, role=auth.role, capability="CHAT"),
            bearer,
        )
    result = apply_platform_tool_policy(result)
    message = result.get("message") or {"role": "assistant", "content": ""}
    reply = str(message.get("content") or "")
    if reply:
        await stored.save_assistant(reply)
    else:
        await stored.close()
    return PlatformChatResponse(
        reply=reply,
        message=message,
        confirmation_required=bool(result.get("confirmation_required")),
        executed=bool(result.get("executed", True)),
        conversation_id=stored.conversation_id,
    )


class ConversationOut(BaseModel):
    id: str
    title: str
    channel: str


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    channel: str = "chat"


class TranscriptTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8000)


@router.post("/conversations", response_model=ConversationOut)
async def create_conversation(body: ConversationRename, auth: AuthDep):
    if auth.role not in PLATFORM_ROLES:
        raise ForbiddenError("The platform assistant is only for the Sybeez platform team")
    from src.modules.platform_assistant.memory import start_conversation

    row = await start_conversation(auth.user_id, title=body.title, channel=body.channel)
    if row is None:
        raise AppError("Could not start a chat", code="unavailable", status_code=503)
    return row


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(auth: AuthDep):
    if auth.role not in PLATFORM_ROLES:
        raise ForbiddenError("The platform assistant is only for the Sybeez platform team")
    from src.modules.platform_assistant.memory import list_conversations as load

    return await load(auth.user_id)


@router.get("/conversations/{conversation_id}/messages")
async def read_conversation(conversation_id: str, auth: AuthDep):
    if auth.role not in PLATFORM_ROLES:
        raise ForbiddenError("The platform assistant is only for the Sybeez platform team")
    from src.modules.platform_assistant.memory import conversation_messages

    rows = await conversation_messages(auth.user_id, conversation_id)
    if rows is None:
        raise AppError("Chat not found", code="not_found", status_code=404)
    return {"messages": rows}


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(conversation_id: str, body: ConversationRename, auth: AuthDep):
    if auth.role not in PLATFORM_ROLES:
        raise ForbiddenError("The platform assistant is only for the Sybeez platform team")
    from src.modules.platform_assistant.memory import rename_conversation as rename

    row = await rename(auth.user_id, conversation_id, body.title)
    if row is None:
        raise AppError("Chat not found", code="not_found", status_code=404)
    return row


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, auth: AuthDep):
    if auth.role not in PLATFORM_ROLES:
        raise ForbiddenError("The platform assistant is only for the Sybeez platform team")
    from src.modules.platform_assistant.memory import delete_conversation as remove

    if not await remove(auth.user_id, conversation_id):
        raise AppError("Chat not found", code="not_found", status_code=404)


@router.post("/conversations/{conversation_id}/messages", status_code=204)
async def append_transcript(conversation_id: str, body: TranscriptTurn, auth: AuthDep):
    if auth.role not in PLATFORM_ROLES:
        raise ForbiddenError("The platform assistant is only for the Sybeez platform team")
    from src.modules.platform_assistant.memory import append_transcript as append

    if not await append(auth.user_id, conversation_id, body.role, body.content):
        raise AppError("Chat not found", code="not_found", status_code=404)
