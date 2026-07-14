"""MarketService — tầng nghiệp vụ cho dữ liệu thị trường.

Trách nhiệm (tầng "fat"):
  - Gọi adapter lấy giá/lịch sử/search
  - Cache giá ngắn hạn trong RAM để không đụng rate limit free tier (~30 calls/phút)
  - Graceful degradation: CoinGecko lỗi/timeout → trả last_price từ bảng coins + cờ stale,
    KHÔNG làm sập app
  - Upsert bảng coins (cache/reference) để map symbol → coingecko_id và lưu last_price

Route gọi service này; service gọi adapter + model. Logic ở đây dùng lại được cho cả UI
(Phase 3 portfolio) lẫn AI Agent (Phase 4 tool get_coin_price).
"""

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal


from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.market_data import MarketDataInterface
from app.core.config import settings
from app.models.coin import Coin
from app.schemas.market import CoinResult, PricePoint, PriceSnapshot

logger = logging.getLogger("cryptopilot.market")

# TTL cache giá (giây). Đọc từ settings nếu có, mặc định 60s. Có thể đưa vào .env sau
# bằng MARKET_CACHE_TTL_SECONDS mà không sửa code.
_CACHE_TTL = int(getattr(settings, "MARKET_CACHE_TTL_SECONDS", 60))

# Cache RAM mức process: { coingecko_id: (price_usd, fetched_at_epoch) }
# Đơn process (uvicorn 1 worker cho scope đồ án) nên dict module-level là đủ.
_price_cache: dict[str, tuple[float, float]] = {}

# Cache OHLC cho trang chi tiết coin: { (coingecko_id, days): (rows, fetched_at) }
_ohlc_cache: dict[tuple[str, int], tuple[list[dict], float]] = {}


def _clear_price_cache() -> None:
    """Tiện cho test — xóa cache giữa các test case."""
    _price_cache.clear()
    _ohlc_cache.clear()


class MarketService:
    def __init__(self, db: Session, adapter: MarketDataInterface) -> None:
        self.db = db
        self.adapter = adapter

    # ──────────────────────────────────────────────────────────────────────
    # Giá hiện tại
    # ──────────────────────────────────────────────────────────────────────
    async def get_prices(self, coingecko_ids: list[str]) -> PriceSnapshot:
        """Giá USD hiện tại cho nhiều coin, có cache + fallback.

        Luồng:
          1. Coin nào còn trong cache (chưa quá TTL) → lấy luôn, không gọi API
          2. Coin còn lại → gọi adapter một lần
          3. Adapter lỗi → fallback last_price trong DB cho các coin còn thiếu, stale=True
        """
        ids = [c for c in dict.fromkeys(coingecko_ids) if c]  # khử trùng, giữ thứ tự
        if not ids:
            return PriceSnapshot(
                prices={}, stale=False, as_of=datetime.now(timezone.utc)
            )

        now = time.monotonic()
        prices: dict[str, float] = {}
        missing: list[str] = []
        for cid in ids:
            cached = _price_cache.get(cid)
            if cached and (now - cached[1]) < _CACHE_TTL:
                prices[cid] = cached[0]
            else:
                missing.append(cid)

        stale = False
        if missing:
            try:
                fresh = await self.adapter.get_prices(missing)
                fetched_at = time.monotonic()
                for cid, price in fresh.items():
                    prices[cid] = price
                    _price_cache[cid] = (price, fetched_at)
                self._persist_last_prices(fresh)
            except Exception as exc:  # noqa: BLE001 - cố ý bắt rộng cho graceful degradation
                # Graceful degradation: API hỏng không được làm sập app
                logger.warning("CoinGecko get_prices lỗi, dùng giá cache DB: %s", exc)
                fallback = self._fallback_prices(missing)
                if fallback:
                    prices.update(fallback)
                stale = True

        return PriceSnapshot(
            prices=prices, stale=stale, as_of=datetime.now(timezone.utc)
        )

    def _fallback_prices(self, coingecko_ids: list[str]) -> dict[str, float]:
        """Lấy last_price đã lưu trong bảng coins làm giá dự phòng."""
        if not coingecko_ids:
            return {}
        rows = self.db.execute(
            select(Coin).where(Coin.coingecko_id.in_(coingecko_ids))
        ).scalars()
        return {
            r.coingecko_id: float(r.last_price)
            for r in rows
            if r.last_price is not None
        }

    def _persist_last_prices(self, prices: dict[str, float]) -> None:
        """Ghi last_price + last_synced_at vào bảng coins cho fallback lần sau."""
        if not prices:
            return
        rows = self.db.execute(
            select(Coin).where(Coin.coingecko_id.in_(list(prices.keys())))
        ).scalars()
        now = datetime.now(timezone.utc)
        for coin in rows:
            coin.last_price = Decimal(str(prices[coin.coingecko_id]))
            coin.last_synced_at = now
        self.db.commit()

    # ──────────────────────────────────────────────────────────────────────
    # Tìm coin
    # ──────────────────────────────────────────────────────────────────────
    async def search_coins(self, query: str) -> list[CoinResult]:
        """Tìm coin theo tên/symbol; tiện thể upsert vào bảng coins để map về sau."""
        try:
            raw = await self.adapter.search_coins(query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CoinGecko search lỗi: %s", exc)
            return []
        results = [CoinResult(**r) for r in raw]
        self._upsert_coins(results)
        return results

    # ──────────────────────────────────────────────────────────────────────
    # Lịch sử giá
    # ──────────────────────────────────────────────────────────────────────
    async def get_history(self, coingecko_id: str, days: int = 30) -> list[PricePoint]:
        try:
            raw = await self.adapter.get_market_history(coingecko_id, days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CoinGecko history lỗi (%s): %s", coingecko_id, exc)
            return []
        return [PricePoint(**p) for p in raw]

    # ──────────────────────────────────────────────────────────────────────
    # Nến OHLC (trang chi tiết coin — candlestick chart)
    # ──────────────────────────────────────────────────────────────────────
    async def get_coin_ohlc(self, coingecko_id: str, days: int = 30) -> list[dict]:
        """Nến OHLC có TTL cache (như giá) + graceful degradation (lỗi → []).

        Key cache theo (coin, days) vì CoinGecko trả độ chi tiết nến khác nhau
        theo days — không tái dùng chéo giữa các khung được.
        """
        key = (coingecko_id, days)
        cached = _ohlc_cache.get(key)
        if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
            return cached[0]
        try:
            rows = await self.adapter.get_ohlc(coingecko_id, days)
        except Exception as exc:  # noqa: BLE001 — graceful degradation như get_history
            logger.warning("CoinGecko OHLC lỗi (%s, %sd): %s", coingecko_id, days, exc)
            return []
        _ohlc_cache[key] = (rows, time.monotonic())
        return rows

    def get_coin(self, coingecko_id: str) -> Coin | None:
        """Tra bản ghi Coin local theo coingecko_id (name/symbol/image cho trang chi tiết)."""
        return (
            self.db.execute(select(Coin).where(Coin.coingecko_id == coingecko_id))
            .scalars()
            .first()
        )

    # ──────────────────────────────────────────────────────────────────────
    # Đồng bộ danh sách coin (dùng cho job refresh 24h ở Phase 5)
    # ──────────────────────────────────────────────────────────────────────
    async def sync_coin_list(self) -> int:
        """Kéo /coins/list về và upsert vào bảng coins. Trả về số coin xử lý."""
        raw = await self.adapter.get_coin_list()
        results = [CoinResult(**r) for r in raw]
        self._upsert_coins(results)
        return len(results)

    def resolve_symbol(self, symbol: str) -> str | None:
        """Tra local symbol → coingecko_id (không tốn rate limit). None nếu chưa có."""
        coin = (
            self.db.execute(select(Coin).where(Coin.symbol == symbol.strip().lower()))
            .scalars()
            .first()
        )
        return coin.coingecko_id if coin else None

    # ──────────────────────────────────────────────────────────────────────
    # Helper upsert
    # ──────────────────────────────────────────────────────────────────────
    def _upsert_coins(self, coins: list[CoinResult]) -> None:
        if not coins:
            return
        incoming = {c.coingecko_id: c for c in coins}
        existing = {
            row.coingecko_id: row
            for row in self.db.execute(
                select(Coin).where(Coin.coingecko_id.in_(list(incoming.keys())))
            ).scalars()
        }
        for cid, data in incoming.items():
            row = existing.get(cid)
            if row is None:
                self.db.add(
                    Coin(
                        coingecko_id=data.coingecko_id,
                        symbol=data.symbol,
                        name=data.name,
                        image_url=data.image_url,
                    )
                )
            else:
                row.symbol = data.symbol
                row.name = data.name
                if data.image_url:
                    row.image_url = data.image_url
        self.db.commit()
