from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    subject_id: UUID | None = None
    class_id: UUID | None = None
    title: str | None = Field(default=None, max_length=255)
    mode: str = "board"


class ConversationOut(BaseModel):
    id: UUID
    school_id: UUID
    user_id: UUID
    student_id: UUID | None
    subject_id: UUID | None
    class_id: UUID | None
    title: str | None
    mode: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = []
