"""Model Message — một tin nhắn trong conversation (Phase 4).

CHỈ lưu nội dung tin nhắn của user và assistant (đúng lựa chọn đã chốt ở 03-database.md).
Các tool call trong vòng ReAct KHÔNG persist — chúng diễn ra trong runtime một lượt trả lời.

role giới hạn ở {"user", "assistant"} (validate ở tầng service, lưu dạng String cho gọn SQLite).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover - tiện debug
        return f"<Message #{self.id} {self.role}>"


from app.models.conversation import Conversation  # noqa: E402,F401
