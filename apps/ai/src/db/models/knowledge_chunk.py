import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIM = 1536


class KnowledgeChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    class_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    document = relationship("KnowledgeDocument", back_populates="chunks")
