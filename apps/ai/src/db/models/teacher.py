import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TeacherSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One whiteboard lesson. Audience is the student plus linked parents and teachers."""

    __tablename__ = "teacher_sessions"
    __table_args__ = (
        Index("ix_teacher_sessions_guardians", "guardian_user_ids", postgresql_using="gin"),
        Index("ix_teacher_sessions_teachers", "teacher_user_ids", postgresql_using="gin"),
    )

    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    student_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    guardian_user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    teacher_user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="AI Teacher")
    topic: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="understand")
    grade_band: Mapped[str] = mapped_column(String(32), nullable=False, default="elementary")
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    awaiting_check: Mapped[bool] = mapped_column(nullable=False, default=False)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    check_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    check_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="ask")
    check_choices: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    internal_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    plans = relationship("TeacherLessonPlan", back_populates="session", cascade="all, delete-orphan")
    pages = relationship("TeacherBoardPage", back_populates="session", cascade="all, delete-orphan")
    actions = relationship("TeacherBoardAction", back_populates="session", cascade="all, delete-orphan")
    messages = relationship("TeacherMessage", back_populates="session", cascade="all, delete-orphan")
    progress_rows = relationship("TeacherProgress", back_populates="session", cascade="all, delete-orphan")


class TeacherLessonPlan(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "teacher_lesson_plans"

    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teacher_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session = relationship("TeacherSession", back_populates="plans")


class TeacherBoardPage(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "teacher_board_pages"

    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teacher_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="Board")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session = relationship("TeacherSession", back_populates="pages")


class TeacherBoardAction(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "teacher_board_actions"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_teacher_board_actions_seq"),)

    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teacher_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teacher_board_pages.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    at_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    action: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session = relationship("TeacherSession", back_populates="actions")


class TeacherMessage(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "teacher_messages"

    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teacher_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    turn_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session = relationship("TeacherSession", back_populates="messages")


class TeacherProgress(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "teacher_progress"
    __table_args__ = (UniqueConstraint("session_id", "concept", name="uq_teacher_progress_session_concept"),)

    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teacher_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    concept: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    session = relationship("TeacherSession", back_populates="progress_rows")
