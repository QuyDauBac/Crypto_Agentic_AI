"""Pydantic schemas cho tầng market data — kiểu trả về chuẩn hóa cho route/service.

Tách riêng khỏi shape của CoinGecko: dù provider trả gì, app luôn làm việc với
các schema dưới đây.
"""

from datetime import datetime

from pydantic import BaseModel


class CoinResult(BaseModel):
    """Một coin trong kết quả tìm kiếm."""

    coingecko_id: str
    symbol: str
    name: str
    image_url: str | None = None


class PriceSnapshot(BaseModel):
    """Ảnh chụp giá nhiều coin tại một thời điểm.

    `stale=True` nghĩa là CoinGecko lỗi/timeout và đây là giá cache cuối (graceful
    degradation) — UI nên hiển thị cờ "dữ liệu cũ".
    """

    prices: dict[str, float]  # { coingecko_id: price_usd }
    stale: bool = False
    as_of: datetime | None = None


class PricePoint(BaseModel):
    """Một điểm trong lịch sử giá."""

    timestamp: int  # epoch milliseconds
    price: float
