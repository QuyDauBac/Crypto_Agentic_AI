"""Contract (interface) cho nguồn tin tức crypto — Adapter pattern (như MarketDataInterface).

Lịch sử đổi nguồn (lý do interface này ra đời):
  - CryptoPanic: ngừng free tier từ 04/2026 → không dùng nữa (adapter giữ lại phòng hờ)
  - cryptocurrency.cv: dự kiến thay thế nhưng deployment đã chết (Vercel DEPLOYMENT_DISABLED,
    verify 07/2026) → không khả thi nếu không self-host
  - CoinTelegraph RSS: nguồn hiện tại — free, không cần key, lọc theo coin phía server qua tag

Đổi nguồn tin lần nữa chỉ cần viết adapter mới implement interface này.
"""

from abc import ABC, abstractmethod


class NewsDataInterface(ABC):
    """Giao diện chuẩn cho mọi nguồn tin tức crypto."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Nguồn tin sẵn sàng dùng chưa (có token/không cần token...).

        UI dựa vào cờ này để phân biệt "chưa cấu hình" với "không có tin".
        """

    @abstractmethod
    async def get_posts(
        self, currencies: list[str] | None = None, limit: int = 5
    ) -> list[dict]:
        """Tin tức mới nhất, chuẩn hoá: {title, source, url, published_at, currencies}.

        `currencies`: danh sách nhận diện coin để lọc — TÊN đầy đủ của coin
        ("Bitcoin", "Ethereum"), không phải symbol; None → tin tổng quát.
        `published_at`: chuỗi ISO 8601.
        Graceful: nguồn lỗi/timeout/chưa cấu hình → trả [] (không ném).
        """
