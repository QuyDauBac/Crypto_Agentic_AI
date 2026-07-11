"""Model OKXSyncedFill — đánh dấu 1 fill (giao dịch) OKX đã được import thành Transaction.

Mục đích DUY NHẤT: chống trùng lặp khi user bấm "Đồng bộ" nhiều lần — mỗi fill từ OKX
(nhận diện qua okx_fill_id = tradeId của OKX) chỉ tạo ra 1 Transaction, lần sync sau
gặp lại fill đó thì bỏ qua.

Không có FK tới OKXConnection (chỉ cần user_id) để đơn giản — nếu user disconnect rồi
connect lại API key khác, lịch sử đã sync vẫn giữ nguyên (tránh sync trùng lần nữa).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OKXSyncedFill(Base):
    __tablename__ = "okx_synced_fills"
    __table_args__ = (UniqueConstraint("user_id", "okx_fill_id", name="uq_user_fill"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    okx_fill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OKXSyncedFill {self.okx_fill_id} user_id={self.user_id}>"
