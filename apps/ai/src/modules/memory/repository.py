import logging
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import StudentAIMemory
from src.shared.vector import clamp_limit, same_uuid, vector_literal

logger = logging.getLogger("sybeez.ai.memory")

MEMORY_VECTOR_SQL = text(
    """
    SELECT id, school_id, student_id, 1 - (embedding <=> CAST(:embedding AS vector)) AS score
    FROM student_ai_memory
    WHERE school_id = CAST(:school_id AS uuid)
      AND student_id = CAST(:student_id AS uuid)
      AND embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:embedding AS vector)
    LIMIT :limit
    """
)


class MemoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_recent(self, *, school_id: UUID, student_id: UUID, limit: int = 8) -> list[StudentAIMemory]:
        school_id = UUID(str(school_id))
        student_id = UUID(str(student_id))
        result = await self.db.execute(
            select(StudentAIMemory)
            .where(StudentAIMemory.school_id == school_id, StudentAIMemory.student_id == student_id)
            .order_by(StudentAIMemory.updated_at.desc())
            .limit(clamp_limit(limit))
        )
        return [
            row
            for row in result.scalars().all()
            if same_uuid(row.school_id, school_id) and same_uuid(row.student_id, student_id)
        ]

    async def similarity_search(
        self,
        *,
        school_id: UUID,
        student_id: UUID,
        embedding: list[float],
        limit: int = 8,
    ) -> list[StudentAIMemory]:
        school_id = UUID(str(school_id))
        student_id = UUID(str(student_id))
        params = {
            "embedding": vector_literal(embedding),
            "school_id": str(school_id),
            "student_id": str(student_id),
            "limit": clamp_limit(limit),
        }
        try:
            async with self.db.begin_nested():
                result = await self.db.execute(MEMORY_VECTOR_SQL, params)
                rows = result.fetchall()
        except Exception as exc:
            logger.warning("memory vector search failed: %s", type(exc).__name__)
            return []

        found: list[StudentAIMemory] = []
        for row in rows:
            if not same_uuid(getattr(row, "school_id", None), school_id) or not same_uuid(
                getattr(row, "student_id", None), student_id
            ):
                logger.warning(
                    "dropped cross-tenant memory row",
                    extra={"row_school_id": str(getattr(row, "school_id", None)), "token_school_id": str(school_id)},
                )
                continue
            memory = await self.db.get(StudentAIMemory, row.id)
            if memory is None:
                continue
            if not same_uuid(memory.school_id, school_id) or not same_uuid(memory.student_id, student_id):
                logger.warning(
                    "dropped cross-tenant memory row",
                    extra={"row_school_id": str(memory.school_id), "token_school_id": str(school_id)},
                )
                continue
            found.append(memory)
        return found

    async def create(self, memory: StudentAIMemory) -> StudentAIMemory:
        self.db.add(memory)
        await self.db.flush()
        return memory
