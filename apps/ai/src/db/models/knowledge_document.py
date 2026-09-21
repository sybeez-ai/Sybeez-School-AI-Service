import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.shared.enums import DocumentStatus


class KnowledgeDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "knowledge_documents"

    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), default="teaching_record", nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=DocumentStatus.READY.value, nullable=False)

    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")
