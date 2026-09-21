import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIConversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """AI-owned conversation. school_id/student_id are opaque refs from Core."""

    __tablename__ = "ai_conversations"

    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="board", nullable=False)

    messages = relationship("AIMessage", back_populates="conversation", cascade="all, delete-orphan")
