"""Model Transaction — nguồn chân lý của danh mục.

Mọi số liệu holdings / P&L đều SUY RA từ bảng này (không có bảng holdings riêng — quyết định
đã chốt ở 03-database.md). Holdings được tính động trong PortfolioService.

FK tới `users` (Phase 1 auth) và `coins` (Phase 2). Tham chiếu users qua tên bảng nên model
này không cần import User — giảm coupling với tầng auth.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.coin import Coin


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    coin_id: Mapped[int] = mapped_column(
        ForeignKey("coins.id"), index=True, nullable=False
    )

    type: Mapped[str] = mapped_column(String(4), nullable=False)  # "buy" | "sell"
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)  # USD/coin
    fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )  # thời điểm giao dịch thực tế (user nhập)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Quan hệ tới Coin (đọc symbol/name khi hiển thị). Không tạo back-ref ở User để khỏi
    # phải sửa model User của bạn.
    coin: Mapped["Coin"] = relationship(lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Transaction {self.type} {self.quantity} coin={self.coin_id}>"
