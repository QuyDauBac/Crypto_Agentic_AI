"""NewsService — tin tức crypto lọc theo coin user đang giữ (Phase 4 tool get_crypto_news).

Lấy symbol các coin trong danh mục hiện tại của user (qua holdings) → truyền làm filter
currencies cho CryptoPanic. Nếu user không giữ coin nào / không truyền filter → tin tổng quát.

Graceful: adapter đã tự nuốt lỗi và trả []; service chỉ định hình kết quả.
"""

import logging

from sqlalchemy.orm import Session

from app.adapters.cryptopanic_adapter import CryptoPanicAdapter
from app.models.user import User
from app.services.portfolio_service import PortfolioService

logger = logging.getLogger(__name__)


class NewsService:
    def __init__(
        self,
        db: Session,
        adapter: CryptoPanicAdapter,
        portfolio_service: PortfolioService,
    ) -> None:
        self.db = db
        self.adapter = adapter
        self.portfolio = portfolio_service

    def _held_symbols(self, user_id: int) -> list[str]:
        return [h.coin.symbol for h in self.portfolio.get_holdings(user_id)]

    async def get_filtered(
        self,
        user: User,
        limit: int = 5,
        coingecko_ids: list[str] | None = None,
    ) -> dict:
        """Tin tức lọc theo coin user giữ (hoặc theo coingecko_ids nếu Agent chỉ định).

        coingecko_ids ở đây là id CoinGecko (vd 'bitcoin'); CryptoPanic dùng symbol (BTC),
        nên ta map qua holdings symbol. MVP: nếu Agent truyền ids, ta vẫn ưu tiên symbol
        từ danh mục để đảm bảo khớp; nếu không có gì thì lấy tin tổng quát.
        """
        symbols = self._held_symbols(user.id)
        posts = await self.adapter.get_posts(currencies=symbols or None, limit=limit)
        if not posts:
            return {
                "news": [],
                "note": (
                    "Không có tin (chưa cấu hình CRYPTOPANIC_TOKEN, "
                    "hoặc không có tin phù hợp)."
                ),
            }
        return {"news": posts, "filtered_by": [s.upper() for s in symbols]}
