import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from src.shared.enums import MessageRole


class AIMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=MessageRole.USER.value)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    conversation = relationship("AIConversation", back_populates="messages")
