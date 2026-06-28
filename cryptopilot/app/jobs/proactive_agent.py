"""Job proactive_agent — Agent chủ động (Phase 5).

Chạy định kỳ (mặc định 6 giờ). Với mỗi user active có holdings: dựng snapshot → Gemini
phân tích (1 call/user) → nếu có nhận định (khác "NONE") thì tạo notification agent_insight.

1 user lỗi không chặn các user còn lại (try/except quanh từng user trong ProactiveAgentService).
"""

import logging

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.adapters.cryptopanic_adapter import CryptoPanicAdapter
from app.agent.gemini_client import GeminiClient
from app.core.config import settings
from app.core.database import SessionLocal
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.notification_service import NotificationService
from app.services.portfolio_service import PortfolioService
from app.services.proactive_service import ProactiveAgentService

logger = logging.getLogger(__name__)


async def run_proactive_agent(
    proactive: ProactiveAgentService,
    notif_service: NotificationService,
) -> int:
    """Lõi logic — trả số notification agent_insight đã tạo."""
    users = proactive.users_with_holdings()
    created = 0
    for user in users:
        insight = await proactive.insight_for_user(user)
        if insight:
            notif_service.create(
                user_id=user.id,
                type_="agent_insight",
                title="Nhận định từ trợ lý",
                message=insight,
            )
            created += 1
    if created:
        logger.info("proactive_agent: tạo %d nhận định", created)
    return created


async def proactive_agent() -> None:
    """Wrapper cho scheduler — bind service thật (Gemini, CoinGecko, CryptoPanic)."""
    db = SessionLocal()
    try:
        market = MarketService(db=db, adapter=CoinGeckoAdapter())
        portfolio = PortfolioService(db=db, market_service=market)
        news = NewsService(
            db=db, adapter=CryptoPanicAdapter(), portfolio_service=portfolio
        )
        client = GeminiClient(
            api_key=settings.GEMINI_API_KEY, model=settings.GEMINI_MODEL
        )
        proactive = ProactiveAgentService(
            db=db,
            portfolio_service=portfolio,
            news_service=news,
            client=client,
        )
        await run_proactive_agent(proactive, NotificationService(db))
    except Exception as exc:  # noqa: BLE001
        logger.warning("proactive_agent lỗi: %s", exc)
    finally:
        db.close()
