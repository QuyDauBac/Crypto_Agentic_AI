"""AlertService — quản lý cảnh báo giá (Phase 5).

Hai nhóm việc:
  1. CRUD alerts (scope theo user_id — user A không đụng alert của user B)
  2. Logic phát hiện chạm ngưỡng (evaluate) + one-shot trigger — tách thuần để test dễ

Job price_check (app/jobs) gọi get_active_alerts() + evaluate() + trigger().
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.coin import Coin
from app.schemas.alert import AlertCreate


class AlertService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ────────────────────────── CRUD (scope theo user) ──────────────────────────
    def list_alerts(self, user_id: int) -> list[Alert]:
        return list(
            self.db.execute(
                select(Alert)
                .where(Alert.user_id == user_id)
                .order_by(Alert.is_active.desc(), Alert.id.desc())
            ).scalars()
        )

    def create_alert(self, user_id: int, data: AlertCreate) -> Alert:
        coin = self._get_or_create_coin(data.coingecko_id, data.symbol, data.name)
        alert = Alert(
            user_id=user_id,
            coin_id=coin.id,
            condition=data.condition,
            threshold_price=data.threshold_price,
            is_active=True,
        )
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def delete_alert(self, user_id: int, alert_id: int) -> bool:
        alert = (
            self.db.execute(
                select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id)
            )
            .scalars()
            .first()
        )
        if alert is None:
            return False
        self.db.delete(alert)
        self.db.commit()
        return True

    def _get_or_create_coin(self, coingecko_id: str, symbol: str, name: str) -> Coin:
        coin = (
            self.db.execute(select(Coin).where(Coin.coingecko_id == coingecko_id))
            .scalars()
            .first()
        )
        if coin is None:
            coin = Coin(
                coingecko_id=coingecko_id,
                symbol=(symbol or coingecko_id).lower(),
                name=name or coingecko_id,
            )
            self.db.add(coin)
            self.db.commit()
            self.db.refresh(coin)
        return coin

    # ────────────────────────── Dùng cho job price_check ──────────────────────────
    def get_active_alerts(self) -> list[Alert]:
        """Mọi alert đang bật của TẤT CẢ user (job chạy nền, không scope user)."""
        return list(
            self.db.execute(select(Alert).where(Alert.is_active.is_(True))).scalars()
        )

    @staticmethod
    def evaluate(condition: str, threshold: Decimal, price: float) -> bool:
        """Pure: giá có chạm ngưỡng theo điều kiện không. Tách riêng để unit-test."""
        p = Decimal(str(price))
        if condition == "above":
            return p >= threshold
        if condition == "below":
            return p <= threshold
        return False

    def trigger(self, alert: Alert) -> None:
        """One-shot: tắt alert + ghi thời điểm kích hoạt (idempotent cho chu kỳ sau)."""
        alert.is_active = False
        alert.triggered_at = datetime.now(timezone.utc)
        self.db.commit()
