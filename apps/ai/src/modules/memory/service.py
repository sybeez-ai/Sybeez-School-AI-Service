from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import StudentAIMemory
from src.modules.embeddings.service import EmbeddingService
from src.modules.memory.repository import MemoryRepository
from src.modules.memory.schemas import MemoryItem, MemoryRecall
from src.shared.enums import MemoryType


class MemoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MemoryRepository(db)
        self.embeddings = EmbeddingService()

    async def recall(self, *, school_id: UUID, student_id: UUID) -> MemoryRecall:
        rows = await self.repo.list_recent(school_id=school_id, student_id=student_id)
        return MemoryRecall(
            items=[MemoryItem(id=r.id, memory_type=r.memory_type, content=r.content) for r in rows]
        )

    async def remember(
        self,
        *,
        school_id: UUID,
        student_id: UUID,
        content: str,
        memory_type: MemoryType = MemoryType.CONCEPT,
    ) -> StudentAIMemory:
        emb = (await self.embeddings.embed([content])).embeddings[0]
        mem = StudentAIMemory(
            school_id=school_id,
            student_id=student_id,
            memory_type=memory_type.value,
            content=content,
            embedding=emb,
        )
        return await self.repo.create(mem)
