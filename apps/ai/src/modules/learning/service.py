from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import AuthContext, require_school
from src.modules.context.service import ContextService
from src.modules.conversations.service import ConversationService
from src.modules.learning.schemas import LearningSummary
from src.modules.memory.service import MemoryService


class LearningService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.context = ContextService()
        self.memory = MemoryService(db)
        self.conversations = ConversationService(db)

    async def summary(self, auth: AuthContext, *, bearer_token: str | None = None) -> LearningSummary:
        school_id = require_school(auth)
        learning = await self.context.for_user(auth, bearer_token=bearer_token)
        recalled = await self.memory.recall(auth, student_id=learning.student.id)
        convs = await self.conversations.list(auth)
        topic = learning.current_learning.topic if learning.current_learning else None
        return LearningSummary(
            student_id=learning.student.id,
            school_id=school_id,
            current_topic=topic,
            memory_highlights=[m.content for m in recalled.items[:5]],
            recent_conversation_ids=[c.id for c in convs[:5]],
            suggested_next=f"Review {topic} with a short practice set" if topic else "Start a new AI Teacher conversation",
        )
