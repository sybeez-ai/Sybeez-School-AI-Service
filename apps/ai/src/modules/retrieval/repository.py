import logging
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import KnowledgeChunk
from src.shared.vector import clamp_limit, same_uuid, vector_literal

logger = logging.getLogger("sybeez.ai.retrieval")

# School predicate is mandatory. Embeddings are bound parameters, not SQL text.
KNOWLEDGE_VECTOR_SQL = text(
    """
    SELECT id, school_id, 1 - (embedding <=> CAST(:embedding AS vector)) AS score
    FROM knowledge_chunks
    WHERE school_id = CAST(:school_id AS uuid)
      AND embedding IS NOT NULL
      AND (CAST(:subject_id AS uuid) IS NULL OR subject_id = CAST(:subject_id AS uuid))
      AND (CAST(:class_id AS uuid) IS NULL OR class_id = CAST(:class_id AS uuid))
    ORDER BY embedding <=> CAST(:embedding AS vector)
    LIMIT :limit
    """
)


class RetrievalRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def similarity_search(
        self,
        *,
        school_id: UUID,
        embedding: list[float],
        subject_id: UUID | None = None,
        class_id: UUID | None = None,
        limit: int = 5,
    ) -> list[tuple[KnowledgeChunk, float | None]]:
        school_id = UUID(str(school_id))
        limit = clamp_limit(limit)
        params = {
            "embedding": vector_literal(embedding),
            "school_id": str(school_id),
            "subject_id": str(subject_id) if subject_id else None,
            "class_id": str(class_id) if class_id else None,
            "limit": limit,
        }
        rows = []
        try:
            async with self.db.begin_nested():
                result = await self.db.execute(KNOWLEDGE_VECTOR_SQL, params)
                rows = result.fetchall()
        except Exception as exc:
            logger.warning("knowledge vector search failed: %s", type(exc).__name__)
            rows = []

        hits: list[tuple[KnowledgeChunk, float | None]] = []
        if rows:
            for row in rows:
                if not same_uuid(getattr(row, "school_id", None), school_id):
                    self._drop(getattr(row, "school_id", None), school_id)
                    continue
                chunk = await self.db.get(KnowledgeChunk, row.id)
                if chunk is None or not same_uuid(chunk.school_id, school_id):
                    if chunk is not None:
                        self._drop(chunk.school_id, school_id)
                    continue
                score = getattr(row, "score", None)
                hits.append((chunk, float(score) if score is not None else None))
            if hits:
                return hits

        query = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.school_id == school_id)
            .order_by(KnowledgeChunk.created_at.desc())
            .limit(limit)
        )
        if subject_id:
            query = query.where(KnowledgeChunk.subject_id == subject_id)
        if class_id:
            query = query.where(KnowledgeChunk.class_id == class_id)
        result = await self.db.execute(query)
        for chunk in result.scalars().all():
            if not same_uuid(chunk.school_id, school_id):
                self._drop(chunk.school_id, school_id)
                continue
            hits.append((chunk, None))
        return hits

    def _drop(self, row_school: object, school_id: UUID) -> None:
        logger.warning(
            "dropped cross-tenant knowledge row",
            extra={"row_school_id": str(row_school), "token_school_id": str(school_id)},
        )
