"""Model Coin — bảng cache/reference cho dữ liệu CoinGecko.

Đây KHÔNG phải nguồn chân lý về giá: giá real-time vẫn lấy trực tiếp từ CoinGecko
qua Adapter. Bảng này dùng để:
  - Map symbol → coingecko_id (CoinGecko nhận id "bitcoin", không nhận symbol "btc")
  - Lưu last_price làm fallback khi API lỗi (graceful degradation)
  - transactions/alerts (các phase sau) tham chiếu coin qua FK thay vì rải chuỗi id khắp nơi

Dùng cú pháp SQLAlchemy 2.0 (Mapped[] / mapped_column) cho đồng bộ với model User.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Coin(Base):
    __tablename__ = "coins"

    id: Mapped[int] = mapped_column(primary_key=True)

    # id chuẩn của CoinGecko, e.g. "bitcoin" — đây mới là cái gửi lên API
    coingecko_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)  # "btc"
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # "Bitcoin"
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Giá USD lần sync gần nhất — chỉ để hiển thị nhanh + fallback khi CoinGecko lỗi
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - tiện debug
        return f"<Coin {self.coingecko_id} ({self.symbol})>"
