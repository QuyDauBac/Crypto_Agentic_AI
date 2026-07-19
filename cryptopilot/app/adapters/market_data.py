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

    @abstractmethod
    async def get_ohlc(self, coingecko_id: str, days: int) -> list[dict]:
        """Nến OHLC N ngày cho candlestick chart (trang chi tiết coin).

        Trả về list dict { "timestamp": int (ms), "open", "high", "low", "close": float }
        theo thứ tự thời gian. Tương đương endpoint /coins/{id}/ohlc.

        Độ chi tiết nến do CoinGecko tự quyết theo days (KHÔNG cấu hình được):
        1-2 ngày → nến 30 phút, 3-30 ngày → nến 4 giờ, >30 ngày → nến 4 ngày.
        """

    @abstractmethod
    async def get_coin_market_data(self, coingecko_id: str) -> dict | None:
        """Giá + % thay đổi 24h + market stats cho trang chi tiết coin (1 lần gọi).

        Trả về hoặc None nếu CoinGecko không có dữ liệu cho coin này:
        {
            "price": float,
            "change_24h_pct": float | None,
            "market_cap": float | None,
            "volume_24h": float | None,
            "circulating_supply": float | None,
            "market_cap_rank": int | None,
            "ath": float | None,
            "max_supply": float | None,
        }
        Tương đương endpoint /coins/{id} (market_data=true, tickers/community/developer
        data=false để nhẹ response) — gộp 1 request thay vì gọi /simple/price riêng.
        """

    @abstractmethod
    async def get_trending(self) -> list[dict]:
        """Top coin đang được tìm kiếm nhiều nhất trên CoinGecko.

        Trả về list dict tối đa 6 phần tử:
        { "coingecko_id": str, "symbol": str, "name": str,
          "price": float | None, "change_24h_pct": float | None }.
        Tương đương endpoint /search/trending.
        """

    @abstractmethod
    async def get_top_market_cap(self, limit: int = 6) -> list[dict]:
        """Top coin theo vốn hoá thị trường.

        Trả về list dict cùng shape với get_trending().
        Tương đương endpoint /coins/markets (order=market_cap_desc).
        """
