from pydantic import BaseModel, Field


class EvaluationRequest(BaseModel):
    question_id: str
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    expected: str | None = None
    topic: str | None = None


class EvaluationResponse(BaseModel):
    correct: bool
    score: float
    feedback: str
    concepts_demonstrated: list[str] = []
    concepts_missing: list[str] = []
