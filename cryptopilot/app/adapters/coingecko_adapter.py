"""CoinGeckoAdapter — implement MarketDataInterface, gọi CoinGecko REST API.

Đặc điểm:
  - Async (httpx.AsyncClient) — đây là I/O chờ lâu nhất, async giúp không block event loop
  - Demo API key truyền qua param x_cg_demo_api_key (free tier ~30 calls/phút)
  - Chuẩn hóa response của CoinGecko về kiểu nội bộ → service không phụ thuộc shape của API
  - KHÔNG chứa logic nghiệp vụ, KHÔNG cache (cache nằm ở MarketService) — adapter chỉ "dịch"

Lưu ý test: __init__ nhận tham số `transport` để inject httpx.MockTransport khi viết test,
không cần gọi mạng thật.
"""

from typing import Any

import httpx

from app.adapters.market_data import MarketDataInterface
from app.core.config import settings

_DEFAULT_TIMEOUT = 10.0


class CoinGeckoAdapter(MarketDataInterface):
    def __init__(
        self,
        base_url: str | None = None,
        demo_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or settings.COINGECKO_BASE_URL).rstrip("/")
        self.demo_key = (
            demo_key if demo_key is not None else settings.COINGECKO_DEMO_KEY
        )
        self._transport = transport
        self._timeout = timeout

    # ── Helper gọi GET, inject demo key, raise nếu HTTP lỗi ──
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        if self.demo_key:
            params["x_cg_demo_api_key"] = self.demo_key
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            resp = await client.get(f"{self.base_url}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_prices(self, coingecko_ids: list[str]) -> dict[str, float]:
        if not coingecko_ids:
            return {}
        data = await self._get(
            "/simple/price",
            {"ids": ",".join(coingecko_ids), "vs_currencies": "usd"},
        )
        # data dạng {"bitcoin": {"usd": 67420}, ...} — bỏ qua coin thiếu field usd
        return {
            cid: float(payload["usd"])
            for cid, payload in data.items()
            if isinstance(payload, dict) and "usd" in payload
        }

    async def search_coins(self, query: str) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        data = await self._get("/search", {"query": query})
        coins = data.get("coins", []) if isinstance(data, dict) else []
        return [
            {
                "coingecko_id": c.get("id"),
                "symbol": (c.get("symbol") or "").lower(),
                "name": c.get("name"),
                "image_url": c.get("large") or c.get("thumb"),
            }
            for c in coins
            if c.get("id")
        ]

    async def get_market_history(self, coingecko_id: str, days: int) -> list[dict]:
        data = await self._get(
            f"/coins/{coingecko_id}/market_chart",
            {"vs_currency": "usd", "days": days},
        )
        # data["prices"] = [[timestamp_ms, price], ...]
        prices = data.get("prices", []) if isinstance(data, dict) else []
        return [
            {"timestamp": int(point[0]), "price": float(point[1])}
            for point in prices
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]

    async def get_ohlc(self, coingecko_id: str, days: int) -> list[dict]:
        data = await self._get(
            f"/coins/{coingecko_id}/ohlc",
            {"vs_currency": "usd", "days": days},
        )
        # data = [[timestamp_ms, open, high, low, close], ...]
        rows = data if isinstance(data, list) else []
        return [
            {
                "timestamp": int(r[0]),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
            }
            for r in rows
            if isinstance(r, (list, tuple)) and len(r) >= 5
        ]

    async def get_coin_list(self) -> list[dict]:
        data = await self._get("/coins/list")
        rows = data if isinstance(data, list) else []
        return [
            {
                "coingecko_id": r.get("id"),
                "symbol": (r.get("symbol") or "").lower(),
                "name": r.get("name"),
            }
            for r in rows
            if r.get("id")
        ]
