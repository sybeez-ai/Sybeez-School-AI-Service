import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.shared.enums import MemoryType

EMBEDDING_DIM = 1536


class StudentAIMemory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Derived AI intelligence — not authoritative school data."""

    __tablename__ = "student_ai_memory"

    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(64), default=MemoryType.PREFERENCE.value, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
