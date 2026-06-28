"""Model Conversation — một phiên chat giữa user và AI Agent (Phase 4).

Một user có nhiều conversation; mỗi conversation có nhiều message (xem message.py).
Title là optional — có thể đặt tên/tóm tắt phiên sau này; MVP để trống.

Cú pháp SQLAlchemy 2.0 (Mapped[] / mapped_column) cho đồng bộ với các model khác.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
    )

    def __repr__(self) -> str:  # pragma: no cover - tiện debug
        return f"<Conversation #{self.id} user={self.user_id}>"


# import muộn để tránh vòng import; chỉ dùng cho type relationship ở trên
from app.models.message import Message  # noqa: E402,F401
