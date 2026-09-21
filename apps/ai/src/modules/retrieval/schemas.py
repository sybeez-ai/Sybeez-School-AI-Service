from uuid import UUID

from pydantic import BaseModel, Field


class RetrievalHit(BaseModel):
    chunk_id: UUID | None = None
    content: str
    score: float | None = None
    source: str | None = None


class RetrievalResult(BaseModel):
    hits: list[RetrievalHit] = Field(default_factory=list)

    def as_prompt_block(self) -> str:
        if not self.hits:
            return "No retrieved knowledge chunks."
        parts = []
        for i, h in enumerate(self.hits, 1):
            parts.append(f"[{i}] {h.content}")
        return "\n".join(parts)
