"""Job price_check — cảnh báo giá (Phase 5).

Chạy định kỳ (mặc định 10 phút). GỘP 1 call giá cho tất cả coin có alert (không lặp
từng coin) — quan trọng vì CoinGecko free chỉ ~30 calls/phút.

Idempotent: alert chạm ngưỡng → AlertService.trigger() tắt nó (is_active=false), nên chu
kỳ sau không tạo lại notification.

`core` nhận dependency để unit-test; `price_check` là wrapper mở session + bind adapter thật.
"""

import logging

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.core.database import SessionLocal
from app.services.alert_service import AlertService
from app.services.market_service import MarketService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_COND_VI = {"above": "vượt lên trên", "below": "rớt xuống dưới"}


async def run_price_check(
    market: MarketService,
    alert_service: AlertService,
    notif_service: NotificationService,
) -> int:
    """Lõi logic — trả số alert đã kích hoạt. Test gọi thẳng hàm này với fake deps."""
    alerts = alert_service.get_active_alerts()
    if not alerts:
        return 0

    coin_ids = sorted({a.coin.coingecko_id for a in alerts})
    snapshot = await market.get_prices(coin_ids)  # cũng tự cập nhật coins.last_price
    prices = snapshot.prices

    triggered = 0
    for alert in alerts:
        price = prices.get(alert.coin.coingecko_id)
        if price is None:
            continue
        if AlertService.evaluate(alert.condition, alert.threshold_price, price):
            alert_service.trigger(alert)
            label = alert.coin.symbol.upper()
            notif_service.create(
                user_id=alert.user_id,
                type_="price_alert",
                title=f"{label} chạm ngưỡng",
                message=(
                    f"{label} hiện {price}$, "
                    f"{_COND_VI.get(alert.condition, '')} ngưỡng "
                    f"{alert.threshold_price}$ bạn đặt."
                ),
                alert_id=alert.id,
            )
            triggered += 1

    if triggered:
        logger.info("price_check: kích hoạt %d alert", triggered)
    return triggered


async def price_check() -> None:
    """Wrapper cho scheduler — mở session riêng, bind adapter thật, nuốt lỗi mỗi chu kỳ."""
    db = SessionLocal()
    try:
        market = MarketService(db=db, adapter=CoinGeckoAdapter())
        await run_price_check(market, AlertService(db), NotificationService(db))
    except Exception as exc:  # noqa: BLE001 — 1 chu kỳ lỗi không được làm sập scheduler
        logger.warning("price_check lỗi: %s", exc)
    finally:
        db.close()
