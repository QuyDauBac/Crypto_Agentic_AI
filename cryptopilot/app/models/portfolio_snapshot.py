"""Model PortfolioSnapshot — 1 điểm giá trị danh mục/user/ngày (Phase 9 chart lịch sử).

Không suy ra được từ transactions (giá thị trường thay đổi mỗi ngày dù không giao dịch
gì), nên cần bảng riêng ghi lại total_value tại các mốc thời gian — job nền (Phase 5
scheduler) ghi 1 lần/ngày. Dashboard đọc bảng này để vẽ biểu đồ hiệu suất vs BTC.

Unique (user_id, snapshot_date): job chạy nhiều lần trong ngày (restart, lệch giờ)
không tạo trùng — upsert theo cặp khóa này.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "snapshot_date", name="uq_portfolio_snapshot_user_date"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PortfolioSnapshot user={self.user_id} date={self.snapshot_date} value={self.total_value}>"
