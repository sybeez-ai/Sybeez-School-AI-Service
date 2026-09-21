from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError
from src.core.security import AuthContext, require_school
from src.db.models import AIConversation, AIMessage
from src.modules.conversations.repository import ConversationRepository
from src.modules.conversations.schemas import ConversationCreate
from src.shared.enums import MessageRole


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ConversationRepository(db)

    async def create(self, auth: AuthContext, data: ConversationCreate, student_id: UUID | None) -> AIConversation:
        school_id = require_school(auth)
        conv = AIConversation(
            school_id=school_id,
            user_id=auth.user_id,
            student_id=student_id,
            subject_id=data.subject_id,
            class_id=data.class_id,
            title=data.title or "AI Teacher session",
            mode=data.mode,
        )
        return await self.repo.create(conv)

    async def list(self, auth: AuthContext) -> list[AIConversation]:
        school_id = require_school(auth)
        return await self.repo.list_for_user(school_id=school_id, user_id=auth.user_id)

    async def get(self, auth: AuthContext, conversation_id: UUID) -> AIConversation:
        school_id = require_school(auth)
        conv = await self.repo.get(conversation_id=conversation_id, school_id=school_id, user_id=auth.user_id)
        if conv is None:
            raise NotFoundError("Conversation not found")
        return conv

    async def append(
        self, *, auth: AuthContext, conversation_id: UUID, role: MessageRole, content: str, meta: dict | None = None
    ) -> AIMessage:
        conv = await self.get(auth, conversation_id)
        if conv.user_id != auth.user_id:
            raise ForbiddenError("Not your conversation")
        msg = AIMessage(
            conversation_id=conv.id,
            school_id=conv.school_id,
            role=role.value,
            content=content,
            meta=meta,
        )
        return await self.repo.add_message(msg)
