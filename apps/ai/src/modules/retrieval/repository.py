from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import KnowledgeChunk


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
        # Cosine distance via pgvector; if embeddings are zero-stubs, fall back to recent chunks
        q = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.school_id == school_id)
            .order_by(KnowledgeChunk.created_at.desc())
            .limit(limit)
        )
        if subject_id:
            q = q.where(KnowledgeChunk.subject_id == subject_id)
        if class_id:
            q = q.where(KnowledgeChunk.class_id == class_id)

        # Prefer vector search when embedding column is populated
        try:
            sql = text(
                """
                SELECT id, content, 1 - (embedding <=> :emb) AS score
                FROM knowledge_chunks
                WHERE school_id = :school_id
                  AND embedding IS NOT NULL
                  AND (:subject_id IS NULL OR subject_id = :subject_id)
                  AND (:class_id IS NULL OR class_id = :class_id)
                ORDER BY embedding <=> :emb
                LIMIT :limit
                """
            )
            result = await self.db.execute(
                sql,
                {
                    "emb": str(embedding),
                    "school_id": str(school_id),
                    "subject_id": str(subject_id) if subject_id else None,
                    "class_id": str(class_id) if class_id else None,
                    "limit": limit,
                },
            )
            rows = result.fetchall()
            if rows:
                out: list[tuple[KnowledgeChunk, float | None]] = []
                for row in rows:
                    chunk = await self.db.get(KnowledgeChunk, row.id)
                    if chunk:
                        out.append((chunk, float(row.score) if row.score is not None else None))
                if out:
                    return out
        except Exception:
            pass

        result = await self.db.execute(q)
        return [(c, None) for c in result.scalars().all()]
