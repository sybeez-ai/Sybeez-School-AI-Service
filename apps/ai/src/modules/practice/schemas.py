from uuid import UUID

from pydantic import BaseModel, Field

from src.shared.enums import PracticeDifficulty


class PracticeRequest(BaseModel):
    subject_id: UUID | None = None
    topic: str | None = None
    difficulty: PracticeDifficulty = PracticeDifficulty.ADAPTIVE
    count: int = Field(5, ge=1, le=20)


class PracticeQuestion(BaseModel):
    id: str
    prompt: str
    question_type: str = "short_answer"
    hint: str | None = None


class PracticeResponse(BaseModel):
    topic: str
    difficulty: str
    questions: list[PracticeQuestion]
