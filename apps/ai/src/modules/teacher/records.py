"""In-memory shape of a teacher session. The SQL store maps rows to this."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class PageRecord:
    id: UUID
    page_index: int
    title: str


@dataclass
class ActionRecord:
    id: UUID
    page_id: UUID
    seq: int
    turn_index: int
    at_ms: int
    action: dict


@dataclass
class MessageRecord:
    id: UUID
    role: str
    content: str
    turn_index: int | None
    created_at: datetime


@dataclass
class ProgressRecord:
    id: UUID
    concept: str
    status: str
    score: float | None
    notes: str | None


@dataclass
class SessionRecord:
    id: UUID
    school_id: UUID
    student_user_id: UUID
    student_id: UUID
    guardian_user_ids: list[UUID]
    teacher_user_ids: list[UUID]
    subject_id: UUID | None
    class_id: UUID | None
    conversation_id: UUID | None
    title: str
    topic: str
    status: str
    phase: str
    grade_band: str
    step_index: int
    attempt: int
    turn_index: int
    awaiting_check: bool
    expected_answer: str
    check_prompt: str
    check_kind: str
    check_choices: list[str] = field(default_factory=list)
    plan: dict | None = None
    plan_version: int = 0
    pages: list[PageRecord] = field(default_factory=list)
    actions: list[ActionRecord] = field(default_factory=list)
    messages: list[MessageRecord] = field(default_factory=list)
    progress: list[ProgressRecord] = field(default_factory=list)
    internal_notes: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
