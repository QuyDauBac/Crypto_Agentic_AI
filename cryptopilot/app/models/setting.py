"""Model Setting — cấu hình hệ thống dạng key/value (Phase 6, theo 03-database.md).

Admin chỉnh được ở runtime mà không cần sửa code/.env. Hai key có tác dụng thật:
  alert.default_threshold_usd → giá trị ngưỡng gợi ý sẵn trong form đặt cảnh báo
  proactive.enabled           → bật/tắt job proactive_agent (tiết kiệm quota Gemini)
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Setting {self.key}={self.value!r}>"
