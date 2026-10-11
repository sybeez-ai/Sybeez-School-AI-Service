from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import AuthContext, require_school
from src.modules.embeddings.service import EmbeddingService
from src.modules.retrieval.repository import RetrievalRepository
from src.modules.retrieval.schemas import RetrievalHit, RetrievalResult


class RetrievalService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = RetrievalRepository(db)
        self.embeddings = EmbeddingService()

    async def search(
        self,
        auth: AuthContext,
        *,
        query: str,
        subject_id: UUID | None = None,
        class_id: UUID | None = None,
        k: int = 5,
    ) -> RetrievalResult:
        school_id = require_school(auth)
        emb = (await self.embeddings.embed([query])).embeddings[0]
        rows = await self.repo.similarity_search(
            school_id=school_id,
            embedding=emb,
            subject_id=subject_id,
            class_id=class_id,
            limit=k,
        )
        hits = [
            RetrievalHit(
                chunk_id=chunk.id,
                content=chunk.content,
                score=score,
                source=str(chunk.document_id),
            )
            for chunk, score in rows
        ]
        return RetrievalResult(hits=hits)
