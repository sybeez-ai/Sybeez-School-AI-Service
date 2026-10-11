from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from src.modules.teacher.protocol import PROTOCOL_VERSION


class StartSessionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    subject_id: UUID | None = None
    title: str | None = Field(default=None, max_length=255)
    stream: bool = False
    pace: bool = False


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    stream: bool = False
    pace: bool = False


class TurnResponse(BaseModel):
    session_id: UUID
    message_id: UUID
    phase: str
    status: str
    step_index: int
    chat_text: str
    actions: list[dict]
    events: list[dict]
    awaiting_check: bool
    check_prompt: str | None = None
    refused: bool = False
    redirected: bool = False
    protocol: str = PROTOCOL_VERSION


class SessionSummary(BaseModel):
    id: UUID
    student_id: UUID
    title: str
    topic: str
    status: str
    phase: str
    step_index: int
    updated_at: datetime | None


class ReplayAction(BaseModel):
    seq: int
    turn_index: int
    at_ms: int
    action: dict


class SessionDetail(BaseModel):
    id: UUID
    student_id: UUID
    title: str
    topic: str
    status: str
    phase: str
    grade_band: str
    step_index: int
    protocol: str = PROTOCOL_VERSION
    awaiting_check: bool
    check_prompt: str | None = None
    check_kind: str
    check_choices: list[str] = []
    plan: dict | None = None
    pages: list[dict]
    actions: list[ReplayAction]
    messages: list[dict]
    progress: list[dict]
    created_at: datetime | None
    updated_at: datetime | None
