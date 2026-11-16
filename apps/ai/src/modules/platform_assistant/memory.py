"""Per-user platform assistant chats, including voice transcripts.

Rows live in the existing ai_conversations and ai_messages tables. The AI
database role cannot create tables or schemas. A fixed school id keeps these
rows out of any real school's tenant, and the session sets that id so row
level security accepts the write.

A database error does not block the reply. The console still answers, and the
next successful write stores the conversation.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("sybeez.ai.platform.memory")

# Not a school. Row level security only sees this value for platform chats.
PLATFORM_SCHOOL_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
_MODES = {"chat": "platform-chat", "voice": "platform-voice"}


def _mode(channel: str) -> str:
    return _MODES.get(channel, "platform-chat")


def _channel(mode: str) -> str:
    return "voice" if mode == "platform-voice" else "chat"


@dataclass
class RememberedTurn:
    conversation_id: str | None = None
    history: list[dict] = field(default_factory=list)
    _session: AsyncSession | None = None
    _row_id: uuid.UUID | None = None

    async def save_assistant(self, text: str) -> None:
        if self._session is None or self._row_id is None or not text.strip():
            await self.close()
            return
        await _append(self._session, self._row_id, "assistant", text)
        await self._session.commit()
        await self.close()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None


async def _session_for(user_id: uuid.UUID) -> AsyncSession:
    from src.core.database import AsyncSessionLocal, install_tenant_context

    session = AsyncSessionLocal()
    install_tenant_context(session, school_id=PLATFORM_SCHOOL_ID, user_id=user_id)
    return session


async def remember_turn(
    *,
    user_id: uuid.UUID,
    conversation_id: str | None,
    channel: str,
    user_text: str,
    history: list[dict],
) -> RememberedTurn:
    remembered = RememberedTurn(history=list(history[-12:]))
    session = None
    try:
        from src.db.models.ai_conversation import AIConversation
        from src.db.models.ai_message import AIMessage

        session = await _session_for(user_id)
        row = await _open(session, AIConversation, user_id, conversation_id, channel, user_text)
        prior = (
            await session.execute(
                select(AIMessage)
                .where(AIMessage.conversation_id == row.id, AIMessage.school_id == PLATFORM_SCHOOL_ID)
                .order_by(AIMessage.created_at.asc())
            )
        ).scalars().all()
        if prior:
            remembered.history = [{"role": item.role, "content": item.content} for item in prior[-12:]]
        await _append(session, row.id, "user", user_text)
        await session.commit()
        remembered.conversation_id = str(row.id)
        remembered._session = session
        remembered._row_id = row.id
    except Exception as exc:
        logger.warning("platform chat memory skipped: %s", type(exc).__name__)
        if session is not None:
            await session.close()
    return remembered


async def _open(session, model, user_id, conversation_id, channel, user_text):
    row = None
    if conversation_id:
        try:
            key = uuid.UUID(conversation_id)
        except ValueError:
            key = None
        if key is not None:
            row = (
                await session.execute(
                    select(model).where(
                        model.id == key,
                        model.user_id == user_id,
                        model.school_id == PLATFORM_SCHOOL_ID,
                        model.mode.in_(tuple(_MODES.values())),
                    )
                )
            ).scalar_one_or_none()
    if row is None:
        title = " ".join(user_text.split())[:80] or "New chat"
        row = model(
            school_id=PLATFORM_SCHOOL_ID,
            user_id=user_id,
            title=title,
            mode=_mode(channel),
        )
        session.add(row)
        await session.flush()
    return row


async def start_conversation(user_id: uuid.UUID, *, title: str, channel: str) -> dict | None:
    try:
        from src.db.models.ai_conversation import AIConversation

        async with await _session_for(user_id) as session:
            row = AIConversation(
                school_id=PLATFORM_SCHOOL_ID,
                user_id=user_id,
                title=(title or "New chat")[:80],
                mode=_mode(channel),
            )
            session.add(row)
            await session.commit()
            return {"id": str(row.id), "title": row.title or "New chat", "channel": _channel(row.mode)}
    except Exception as exc:
        logger.warning("platform chat create skipped: %s", type(exc).__name__)
        return None


async def list_conversations(user_id: uuid.UUID) -> list[dict]:
    try:
        from src.db.models.ai_conversation import AIConversation

        async with await _session_for(user_id) as session:
            rows = (
                await session.execute(
                    select(AIConversation)
                    .where(
                        AIConversation.user_id == user_id,
                        AIConversation.school_id == PLATFORM_SCHOOL_ID,
                        AIConversation.mode.in_(tuple(_MODES.values())),
                    )
                    .order_by(AIConversation.updated_at.desc())
                )
            ).scalars().all()
            return [
                {"id": str(row.id), "title": row.title or "New chat", "channel": _channel(row.mode)}
                for row in rows
            ]
    except Exception as exc:
        logger.warning("platform chat list skipped: %s", type(exc).__name__)
        return []


async def conversation_messages(user_id: uuid.UUID, conversation_id: str) -> list[dict] | None:
    found = await _owned(user_id, conversation_id)
    if found is None:
        return None
    session, model_row = found
    from src.db.models.ai_message import AIMessage

    rows = (
        await session.execute(
            select(AIMessage)
            .where(AIMessage.conversation_id == model_row.id, AIMessage.school_id == PLATFORM_SCHOOL_ID)
            .order_by(AIMessage.created_at.asc())
        )
    ).scalars().all()
    payload = [{"role": row.role, "content": row.content} for row in rows]
    await session.close()
    return payload


async def rename_conversation(user_id: uuid.UUID, conversation_id: str, title: str) -> dict | None:
    row = await _owned(user_id, conversation_id)
    if row is None:
        return None
    session, model_row = row
    model_row.title = title.strip()[:80] or "New chat"
    await session.commit()
    payload = {"id": str(model_row.id), "title": model_row.title, "channel": _channel(model_row.mode)}
    await session.close()
    return payload


async def delete_conversation(user_id: uuid.UUID, conversation_id: str) -> bool:
    found = await _owned(user_id, conversation_id)
    if found is None:
        return False
    session, model_row = found
    from src.db.models.ai_message import AIMessage

    await session.execute(
        delete(AIMessage).where(
            AIMessage.conversation_id == model_row.id,
            AIMessage.school_id == PLATFORM_SCHOOL_ID,
        )
    )
    await session.delete(model_row)
    await session.commit()
    await session.close()
    return True


async def append_transcript(user_id: uuid.UUID, conversation_id: str, role: str, content: str) -> bool:
    found = await _owned(user_id, conversation_id)
    if found is None:
        return False
    session, model_row = found
    model_row.mode = "platform-voice"
    await _append(session, model_row.id, role, content)
    await session.commit()
    await session.close()
    return True


async def _owned(user_id: uuid.UUID, conversation_id: str):
    try:
        key = uuid.UUID(conversation_id)
    except ValueError:
        return None
    try:
        from src.db.models.ai_conversation import AIConversation

        session = await _session_for(user_id)
        row = (
            await session.execute(
                select(AIConversation).where(
                    AIConversation.id == key,
                    AIConversation.user_id == user_id,
                    AIConversation.school_id == PLATFORM_SCHOOL_ID,
                    AIConversation.mode.in_(tuple(_MODES.values())),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            await session.close()
            return None
        return session, row
    except Exception as exc:
        logger.warning("platform chat lookup skipped: %s", type(exc).__name__)
        return None


async def _append(session, conversation_id, role: str, content: str) -> None:
    from src.db.models.ai_conversation import AIConversation
    from src.db.models.ai_message import AIMessage

    session.add(
        AIMessage(
            conversation_id=conversation_id,
            school_id=PLATFORM_SCHOOL_ID,
            role=role,
            content=content[:8000],
        )
    )
    parent = await session.get(AIConversation, conversation_id)
    if parent is not None:
        parent.updated_at = datetime.now(timezone.utc)
    await session.flush()
