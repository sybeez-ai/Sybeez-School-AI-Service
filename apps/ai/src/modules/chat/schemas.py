from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=8000)
    subject_id: UUID | None = None
    stream: bool = False


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    reply: str
    sources: list[str] = []
