"""NewsService — tin tức crypto lọc theo coin user đang giữ (Phase 4 tool get_crypto_news).

Lấy TÊN các coin trong danh mục hiện tại của user (qua holdings) → truyền làm filter
cho adapter tin tức (NewsDataInterface — hiện là CoinTelegraph RSS, lọc theo tag tên
coin). Nếu user không giữ coin nào / không truyền filter → tin tổng quát.

TTL cache RAM (như MarketService — _price_cache/_ohlc_cache): RSS chỉ cập nhật ~1
lần/giờ, không có lý do fetch mới mỗi lần load trang; cache còn giảm tải cho server
CoinTelegraph khi nhiều request trùng filter tới gần nhau.

Graceful: adapter đã tự nuốt lỗi và trả []; service chỉ định hình kết quả.
"""

import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.news_data import NewsDataInterface
from app.core.config import settings
from app.models.coin import Coin
from app.models.user import User
from app.services.portfolio_service import PortfolioService

logger = logging.getLogger(__name__)

# TTL cache tin tức (giây). Dài hơn giá (60s) vì RSS cập nhật hàng giờ — 60s sẽ chỉ
# né được request trùng tích tắc, không tránh được tải lặp lại thực sự.
_NEWS_CACHE_TTL = int(getattr(settings, "NEWS_CACHE_TTL_SECONDS", 300))

# Cache RAM mức process: { (currencies theo thứ tự, limit): (posts, fetched_at_epoch) }
_news_cache: dict[tuple[tuple[str, ...] | None, int], tuple[list[dict], float]] = {}


def _clear_news_cache() -> None:
    """Tiện cho test — xóa cache giữa các test case."""
    _news_cache.clear()


class NewsService:
    def __init__(
        self,
        db: Session,
        adapter: NewsDataInterface,
        portfolio_service: PortfolioService,
    ) -> None:
        self.db = db
        self.adapter = adapter
        self.portfolio = portfolio_service

    def _held_coin_names(self, user_id: int) -> list[str]:
        return [h.coin.name for h in self.portfolio.get_holdings(user_id)]

    async def _get_posts_cached(
        self, currencies: list[str] | None, limit: int
    ) -> list[dict]:
        key = (tuple(currencies) if currencies else None, limit)
        cached = _news_cache.get(key)
        if cached and (time.monotonic() - cached[1]) < _NEWS_CACHE_TTL:
            return cached[0]
        posts = await self.adapter.get_posts(currencies=currencies, limit=limit)
        _news_cache[key] = (posts, time.monotonic())
        return posts

    async def get_filtered(
        self,
        user: User,
        limit: int = 5,
        coingecko_ids: list[str] | None = None,
    ) -> dict:
        """Tin tức lọc theo coin user giữ (hoặc theo coingecko_ids nếu Agent chỉ định).

        Adapter (NewsDataInterface) nhận TÊN coin đầy đủ ("Bitcoin"); ta lấy tên từ
        holdings. MVP: nếu Agent truyền ids, ta vẫn ưu tiên tên từ danh mục để đảm
        bảo khớp; nếu không có gì thì lấy tin tổng quát.
        """
        names = self._held_coin_names(user.id)
        posts = await self._get_posts_cached(names or None, limit)
        if not posts:
            return {
                "news": [],
                "note": "Không có tin (nguồn tin lỗi hoặc không có tin phù hợp).",
            }
        return {"news": posts, "filtered_by": names}

    async def get_news_for_coin(self, coingecko_id: str, limit: int = 10) -> list[dict]:
        """Tin tức cho đúng 1 coin — trang chi tiết /market/coin/{id}.

        Adapter lọc theo TÊN coin ("Ethereum" → tag CoinTelegraph) chứ không phải id
        CoinGecko — map qua bảng coins local. Coin chưa có trong bảng → [] (route đã
        upsert qua search trước khi gọi đây, nên chỉ xảy ra với id không tồn tại).
        Graceful như get_filtered: nguồn lỗi → adapter tự trả [].
        """
        coin = (
            self.db.execute(select(Coin).where(Coin.coingecko_id == coingecko_id))
            .scalars()
            .first()
        )
        if coin is None:
            return []
        return await self._get_posts_cached([coin.name], limit)
