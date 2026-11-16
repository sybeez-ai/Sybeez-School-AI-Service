import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PlatformAssistantConversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One platform-console chat or voice session, owned by the signed-in user."""

    __tablename__ = "platform_assistant_conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New chat")
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="chat")


class PlatformAssistantMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "platform_assistant_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
