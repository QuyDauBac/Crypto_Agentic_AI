"""Model Alert — cảnh báo giá user đặt cho một coin (Phase 5).

One-shot: khi job price_check phát hiện giá chạm ngưỡng → set is_active=false + ghi
triggered_at, để chu kỳ sau không tạo lại notification (idempotent).

FK tới users + coins. relationship coin (joined) để hiển thị symbol/name.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.coin import Coin


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    coin_id: Mapped[int] = mapped_column(
        ForeignKey("coins.id"), index=True, nullable=False
    )

    condition: Mapped[str] = mapped_column(String(5), nullable=False)  # above | below
    threshold_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    coin: Mapped["Coin"] = relationship(lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Alert #{self.id} {self.condition} {self.threshold_price}>"
