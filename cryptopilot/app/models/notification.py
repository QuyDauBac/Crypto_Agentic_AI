"""Model Notification — thông báo in-app cho user (Phase 5).

type:
  price_alert   = từ job price_check khi alert chạm ngưỡng (có alert_id)
  agent_insight = từ job proactive_agent (nhận định text của Gemini, alert_id = null)

Gom chung một bảng để hộp thông báo + badge "chưa đọc" hiển thị cả hai loại.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # price_alert | agent_insight
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id"), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Notification #{self.id} {self.type} read={self.is_read}>"
