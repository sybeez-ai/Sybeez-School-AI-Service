from uuid import UUID

from pydantic import BaseModel, Field


class LearningSummary(BaseModel):
    student_id: UUID
    school_id: UUID
    current_topic: str | None = None
    memory_highlights: list[str] = Field(default_factory=list)
    recent_conversation_ids: list[UUID] = Field(default_factory=list)
    suggested_next: str | None = None
