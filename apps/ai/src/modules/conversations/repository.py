from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import AIConversation, AIMessage


class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, conv: AIConversation) -> AIConversation:
        self.db.add(conv)
        await self.db.flush()
        return conv

    async def get(self, *, conversation_id: UUID, school_id: UUID, user_id: UUID) -> AIConversation | None:
        result = await self.db.execute(
            select(AIConversation)
            .options(selectinload(AIConversation.messages))
            .where(
                AIConversation.id == conversation_id,
                AIConversation.school_id == school_id,
                AIConversation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, *, school_id: UUID, user_id: UUID, limit: int = 50) -> list[AIConversation]:
        result = await self.db.execute(
            select(AIConversation)
            .where(AIConversation.school_id == school_id, AIConversation.user_id == user_id)
            .order_by(AIConversation.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add_message(self, msg: AIMessage) -> AIMessage:
        self.db.add(msg)
        await self.db.flush()
        return msg

    async def recent_messages(self, conversation_id: UUID, limit: int = 20) -> list[AIMessage]:
        result = await self.db.execute(
            select(AIMessage)
            .where(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.created_at.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
        return list(reversed(rows))
