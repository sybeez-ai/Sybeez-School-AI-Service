from uuid import UUID

from pydantic import BaseModel, Field


class SubjectRef(BaseModel):
    id: UUID
    name: str


class CurrentLearning(BaseModel):
    subject_id: UUID | None = None
    topic: str | None = None
    teaching_record_id: UUID | None = None
    taught_content: list[str] = Field(default_factory=list)


class HomeworkRef(BaseModel):
    id: UUID
    title: str
    due_at: str | None = None


class StudentContext(BaseModel):
    id: UUID
    class_id: UUID | None = None


class SchoolContext(BaseModel):
    id: UUID


class AuthorizedLearningContext(BaseModel):
    """Authorized context from Core API — never trust client for these fields."""

    student: StudentContext
    school: SchoolContext
    subjects: list[SubjectRef] = Field(default_factory=list)
    current_learning: CurrentLearning | None = None
    homework: list[HomeworkRef] = Field(default_factory=list)

    def as_prompt_block(self) -> str:
        lines = [
            f"School: {self.school.id}",
            f"Student: {self.student.id}",
        ]
        if self.student.class_id:
            lines.append(f"Class: {self.student.class_id}")
        if self.subjects:
            lines.append("Subjects: " + ", ".join(f"{s.name}({s.id})" for s in self.subjects))
        if self.current_learning:
            cl = self.current_learning
            lines.append(f"Current topic: {cl.topic or 'n/a'}")
            if cl.taught_content:
                lines.append("Taught content: " + "; ".join(cl.taught_content))
        if self.homework:
            lines.append("Homework: " + "; ".join(h.title for h in self.homework))
        return "\n".join(lines)
