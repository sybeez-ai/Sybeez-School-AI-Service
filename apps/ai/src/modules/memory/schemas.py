from uuid import UUID

from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    id: UUID | None = None
    memory_type: str
    content: str


class MemoryRecall(BaseModel):
    items: list[MemoryItem] = Field(default_factory=list)

    def as_prompt_block(self) -> str:
        if not self.items:
            return "No prior AI memory."
        return "\n".join(f"- ({m.memory_type}) {m.content}" for m in self.items)
