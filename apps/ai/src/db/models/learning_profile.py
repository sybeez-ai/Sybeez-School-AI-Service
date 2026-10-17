import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StudentLearningProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """How one student learns best, built from their own outcomes with the AI teacher.

    Audience (RLS): the student, linked parents and linked teachers may read; only the student writes.
    """

    __tablename__ = "student_learning_profiles"
    __table_args__ = (
        Index("uq_student_learning_profiles_student", "school_id", "student_user_id", unique=True),
        Index("ix_student_learning_profiles_guardians", "guardian_user_ids", postgresql_using="gin"),
        Index("ix_student_learning_profiles_teachers", "teacher_user_ids", postgresql_using="gin"),
    )

    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    student_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    guardian_user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    teacher_user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
