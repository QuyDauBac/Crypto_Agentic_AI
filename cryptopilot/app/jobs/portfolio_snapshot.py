"""Job portfolio_snapshot — ghi 1 điểm giá trị danh mục/user/ngày (Phase 9 chart).

Chạy 1 lần/ngày. Với mỗi user active có holdings: tính total_value/total_cost hiện tại
qua PortfolioService.get_current_value() rồi upsert snapshot hôm nay (save_snapshot tự
check-exists nên job chạy nhiều lần trong ngày — restart, lệch giờ — không tạo trùng).

CoinGecko lỗi hoàn toàn cho 1 user (get_current_value trả None) → skip user đó hôm nay,
log lại — không lưu total_value sai (0/thiếu) đè lên snapshot đúng của ngày trước.
1 user lỗi không chặn các user còn lại.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.core.database import SessionLocal
from app.models.transaction import Transaction
from app.models.user import User
from app.services.market_service import MarketService
from app.services.portfolio_service import PortfolioService

logger = logging.getLogger(__name__)


def _users_with_holdings(db: Session) -> list[User]:
    """User đang active VÀ có ít nhất 1 giao dịch (user danh mục rỗng không cần snapshot)."""
    user_ids = list(db.execute(select(Transaction.user_id).distinct()).scalars())
    if not user_ids:
        return []
    return list(
        db.execute(
            select(User).where(User.id.in_(user_ids), User.is_active.is_(True))
        ).scalars()
    )


async def run_portfolio_snapshot(
    users: list[User], portfolio: PortfolioService, today: date | None = None
) -> int:
    """Lõi logic — trả số snapshot đã lưu. Test gọi thẳng hàm này với fake portfolio."""
    today = today or date.today()
    saved = 0
    for user in users:
        try:
            result = await portfolio.get_current_value(user.id)
        except Exception as exc:  # noqa: BLE001 — 1 user lỗi không chặn các user còn lại
            logger.warning(
                "portfolio_snapshot: lỗi tính giá trị user %d: %s", user.id, exc
            )
            continue
        if result is None:
            logger.warning(
                "portfolio_snapshot: bỏ qua user %d hôm %s "
                "(không có holdings hoặc CoinGecko lỗi hoàn toàn)",
                user.id,
                today,
            )
            continue
        total_value, total_cost = result
        portfolio.save_snapshot(user.id, today, total_value, total_cost)
        saved += 1
    if saved:
        logger.info("portfolio_snapshot: lưu %d snapshot cho ngày %s", saved, today)
    return saved


async def portfolio_snapshot() -> None:
    """Wrapper cho scheduler — mở session riêng, bind adapter thật, nuốt lỗi mỗi chu kỳ."""
    db = SessionLocal()
    try:
        market = MarketService(db=db, adapter=CoinGeckoAdapter())
        portfolio = PortfolioService(db=db, market_service=market)
        users = _users_with_holdings(db)
        await run_portfolio_snapshot(users, portfolio)
    except Exception as exc:  # noqa: BLE001
        logger.warning("portfolio_snapshot lỗi: %s", exc)
    finally:
        db.close()
