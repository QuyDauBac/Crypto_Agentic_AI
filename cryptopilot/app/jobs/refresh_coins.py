"""Job refresh_coins — làm mới cache coin (Phase 5).

Chạy 24h/lần. Kéo CoinGecko /coins/list (1 call) → upsert bảng coins để map
symbol → coingecko_id luôn đúng. Tra cứu lúc user nhập giao dịch dùng bảng local này,
không tốn rate limit.
"""

import logging

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.core.database import SessionLocal
from app.services.market_service import MarketService

logger = logging.getLogger(__name__)


async def run_refresh_coins(market: MarketService) -> int:
    """Lõi — trả số coin đã upsert."""
    count = await market.sync_coin_list()
    logger.info("refresh_coins: đồng bộ %d coin", count)
    return count


async def refresh_coins() -> None:
    """Wrapper cho scheduler."""
    db = SessionLocal()
    try:
        market = MarketService(db=db, adapter=CoinGeckoAdapter())
        await run_refresh_coins(market)
    except Exception as exc:  # noqa: BLE001
        logger.warning("refresh_coins lỗi: %s", exc)
    finally:
        db.close()
