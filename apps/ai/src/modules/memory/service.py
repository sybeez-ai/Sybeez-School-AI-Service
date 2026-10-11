import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import AuthContext, require_school
from src.db.models import StudentAIMemory
from src.modules.embeddings.service import EmbeddingService
from src.modules.memory.repository import MemoryRepository
from src.modules.memory.schemas import MemoryItem, MemoryRecall
from src.shared.enums import MemoryType

logger = logging.getLogger("sybeez.ai.memory")


class MemoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MemoryRepository(db)
        self.embeddings = EmbeddingService()

    async def recall(self, auth: AuthContext, *, student_id: UUID, query: str | None = None) -> MemoryRecall:
        school_id = require_school(auth)
        if query:
            try:
                embedding = (await self.embeddings.embed([query])).embeddings[0]
                rows = await self.repo.similarity_search(
                    school_id=school_id,
                    student_id=student_id,
                    embedding=embedding,
                )
            except Exception as exc:
                logger.warning("memory recall vector path failed: %s", type(exc).__name__)
                rows = []
            if rows:
                return self._recall(rows)
        rows = await self.repo.list_recent(school_id=school_id, student_id=student_id)
        return self._recall(rows)

    async def remember(
        self,
        auth: AuthContext,
        *,
        student_id: UUID,
        content: str,
        memory_type: MemoryType = MemoryType.CONCEPT,
    ) -> StudentAIMemory:
        school_id = require_school(auth)
        embedding = (await self.embeddings.embed([content])).embeddings[0]
        memory = StudentAIMemory(
            school_id=school_id,
            student_id=student_id,
            memory_type=memory_type.value,
            content=content,
            embedding=embedding,
        )
        return await self.repo.create(memory)

    def _recall(self, rows: list[StudentAIMemory]) -> MemoryRecall:
        return MemoryRecall(
            items=[MemoryItem(id=row.id, memory_type=row.memory_type, content=row.content) for row in rows]
        )
