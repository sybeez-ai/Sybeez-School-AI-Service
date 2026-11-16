"""Per-user platform assistant chats, including voice transcripts.

A missing table or a database error does not block the reply. The console
still answers, and the next successful write stores the conversation.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("sybeez.ai.platform.memory")


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


async def remember_turn(
    *,
    user_id: uuid.UUID,
    conversation_id: str | None,
    channel: str,
    user_text: str,
    history: list[dict],
) -> RememberedTurn:
    remembered = RememberedTurn(history=list(history[-12:]))
    try:
        from src.core.database import AsyncSessionLocal
        from src.db.models.platform_chat import PlatformAssistantConversation, PlatformAssistantMessage

        session = AsyncSessionLocal()
        row = await _open(session, PlatformAssistantConversation, user_id, conversation_id, channel, user_text)
        prior = (
            await session.execute(
                select(PlatformAssistantMessage)
                .where(PlatformAssistantMessage.conversation_id == row.id)
                .order_by(PlatformAssistantMessage.created_at.asc())
            )
        ).scalars().all()
        if prior:
            remembered.history = [{"role": item.role, "content": item.content} for item in prior[-12:]]
        await _append(session, row.id, "user", user_text, PlatformAssistantMessage)
        await session.commit()
        remembered.conversation_id = str(row.id)
        remembered._session = session
        remembered._row_id = row.id
    except Exception as exc:
        logger.warning("platform chat memory skipped: %s", type(exc).__name__)
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
                    select(model).where(model.id == key, model.user_id == user_id)
                )
            ).scalar_one_or_none()
    if row is None:
        title = " ".join(user_text.split())[:80] or "New chat"
        row = model(user_id=user_id, title=title, channel=channel if channel in {"chat", "voice"} else "chat")
        session.add(row)
        await session.flush()
    return row


async def start_conversation(user_id: uuid.UUID, *, title: str, channel: str) -> dict | None:
    try:
        from src.core.database import AsyncSessionLocal
        from src.db.models.platform_chat import PlatformAssistantConversation

        async with AsyncSessionLocal() as session:
            row = PlatformAssistantConversation(
                user_id=user_id,
                title=(title or "New chat")[:80],
                channel=channel if channel in {"chat", "voice"} else "chat",
            )
            session.add(row)
            await session.commit()
            return {"id": str(row.id), "title": row.title, "channel": row.channel}
    except Exception as exc:
        logger.warning("platform chat create skipped: %s", type(exc).__name__)
        return None


async def list_conversations(user_id: uuid.UUID) -> list[dict]:
    try:
        from src.core.database import AsyncSessionLocal
        from src.db.models.platform_chat import PlatformAssistantConversation

        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(PlatformAssistantConversation)
                    .where(PlatformAssistantConversation.user_id == user_id)
                    .order_by(PlatformAssistantConversation.updated_at.desc())
                )
            ).scalars().all()
            return [{"id": str(row.id), "title": row.title, "channel": row.channel} for row in rows]
    except Exception as exc:
        logger.warning("platform chat list skipped: %s", type(exc).__name__)
        return []


async def conversation_messages(user_id: uuid.UUID, conversation_id: str) -> list[dict] | None:
    found = await _owned(user_id, conversation_id)
    if found is None:
        return None
    session, model_row = found
    from src.db.models.platform_chat import PlatformAssistantMessage

    rows = (
        await session.execute(
            select(PlatformAssistantMessage)
            .where(PlatformAssistantMessage.conversation_id == model_row.id)
            .order_by(PlatformAssistantMessage.created_at.asc())
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
    model_row.title = title.strip()[:80]
    await session.commit()
    payload = {"id": str(model_row.id), "title": model_row.title, "channel": model_row.channel}
    await session.close()
    return payload


async def delete_conversation(user_id: uuid.UUID, conversation_id: str) -> bool:
    found = await _owned(user_id, conversation_id)
    if found is None:
        return False
    session, model_row = found
    await session.delete(model_row)
    await session.commit()
    await session.close()
    return True


async def append_transcript(user_id: uuid.UUID, conversation_id: str, role: str, content: str) -> bool:
    found = await _owned(user_id, conversation_id)
    if found is None:
        return False
    session, model_row = found
    if model_row.channel != "voice":
        model_row.channel = "voice"
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
        from src.core.database import AsyncSessionLocal
        from src.db.models.platform_chat import PlatformAssistantConversation

        session = AsyncSessionLocal()
        row = (
            await session.execute(
                select(PlatformAssistantConversation).where(
                    PlatformAssistantConversation.id == key,
                    PlatformAssistantConversation.user_id == user_id,
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


async def _append(session, conversation_id, role: str, content: str, message_model=None) -> None:
    if message_model is None:
        from src.db.models.platform_chat import PlatformAssistantMessage

        message_model = PlatformAssistantMessage
    session.add(message_model(conversation_id=conversation_id, role=role, content=content[:8000]))
    await session.flush()
