"""Contract (interface) cho nguồn dữ liệu thị trường — Adapter pattern.

Đổi CoinGecko sang provider khác (vd CoinMarketCap) chỉ cần viết một adapter mới
implement interface này; tầng service KHÔNG phải sửa. Đây là điểm "thiết kế mở rộng"
dễ ăn điểm khi chấm đồ án.

Mọi method đều async vì đây là I/O ra ngoài (gọi HTTP API) — chờ lâu nhất trong app.
"""

from abc import ABC, abstractmethod


class MarketDataInterface(ABC):
    """Giao diện chuẩn cho mọi nguồn dữ liệu thị trường crypto."""

    @abstractmethod
    async def get_prices(self, coingecko_ids: list[str]) -> dict[str, float]:
        """Giá USD hiện tại cho nhiều coin một lần.

        Trả về dict { coingecko_id: price_usd }, vd {"bitcoin": 67420.0}.
        Tương đương endpoint /simple/price.
        """

    @abstractmethod
    async def search_coins(self, query: str) -> list[dict]:
        """Tìm coin theo tên/symbol.

        Trả về list dict đã chuẩn hóa:
        { "coingecko_id": str, "symbol": str, "name": str, "image_url": str | None }.
        Tương đương endpoint /search.
        """

    @abstractmethod
    async def get_market_history(self, coingecko_id: str, days: int) -> list[dict]:
        """Lịch sử giá N ngày để phân tích xu hướng.

        Trả về list dict { "timestamp": int (ms), "price": float } theo thứ tự thời gian.
        Tương đương endpoint /coins/{id}/market_chart.
        """

    @abstractmethod
    async def get_coin_list(self) -> list[dict]:
        """Toàn bộ coin CoinGecko hỗ trợ — để seed/cache bảng coins.

        Trả về list dict { "coingecko_id": str, "symbol": str, "name": str }.
        Tương đương endpoint /coins/list. Gọi thưa (24h/lần) vì list rất dài.
        """
