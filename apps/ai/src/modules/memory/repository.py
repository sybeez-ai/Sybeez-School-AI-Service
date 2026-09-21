from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import StudentAIMemory


class MemoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_recent(self, *, school_id: UUID, student_id: UUID, limit: int = 8) -> list[StudentAIMemory]:
        result = await self.db.execute(
            select(StudentAIMemory)
            .where(StudentAIMemory.school_id == school_id, StudentAIMemory.student_id == student_id)
            .order_by(StudentAIMemory.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, memory: StudentAIMemory) -> StudentAIMemory:
        self.db.add(memory)
        await self.db.flush()
        return memory
