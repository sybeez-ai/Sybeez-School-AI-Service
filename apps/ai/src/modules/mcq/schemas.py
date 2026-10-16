from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class McqDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    MIXED = "mixed"


class McqGenerateRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    subject_name: str | None = Field(default=None, max_length=120)
    class_label: str | None = Field(default=None, max_length=80)
    difficulty: McqDifficulty = McqDifficulty.MIXED
    count: int = Field(5, ge=1, le=30)
    options_per_question: int = Field(4, ge=3, le=5)
    language: str = Field("English", min_length=2, max_length=40)
    source_notes: str | None = Field(default=None, max_length=6000)
    avoid_prompts: list[str] = Field(default_factory=list, max_length=100)
    verify: bool = False

    @field_validator("avoid_prompts")
    @classmethod
    def _trim_avoid(cls, value: list[str]) -> list[str]:
        return [v[:500] for v in value]


class McqDraftQuestion(BaseModel):
    prompt: str
    options: list[str]
    correct_index: int
    explanation: str = ""
    difficulty: str = "medium"
    topic_tag: str | None = None
    needs_review: bool = False
    review_reason: str | None = None


class McqGenerateResponse(BaseModel):
    topic: str
    requested: int
    questions: list[McqDraftQuestion]
    dropped_invalid: int = 0
    dropped_duplicates: int = 0
