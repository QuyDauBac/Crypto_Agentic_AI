"""Tests Phase 5 — Scheduled jobs (lõi logic, không cần scheduler/mạng thật).

- run_price_check: kích hoạt khi giá chạm ngưỡng → tạo notification + tắt alert; idempotent
- run_proactive_agent: tạo agent_insight khi có nhận định; bỏ qua khi NONE / danh mục rỗng
- run_refresh_coins: trả số coin đồng bộ
- run_portfolio_snapshot (Phase 9): lưu snapshot user có holdings; skip user rỗng/lỗi giá,
  không chặn user khác; upsert idempotent trong cùng ngày
"""

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from app.core.database import Base
from app.jobs.portfolio_snapshot import run_portfolio_snapshot
from app.jobs.price_check import run_price_check
from app.jobs.proactive_agent import run_proactive_agent
from app.jobs.refresh_coins import run_refresh_coins
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.user import User
from app.schemas.alert import AlertCreate
from app.schemas.market import PriceSnapshot
from app.schemas.transaction import TransactionCreate
from app.services.alert_service import AlertService
from app.services.notification_service import NotificationService
from app.services.portfolio_service import PortfolioService
from app.services.proactive_service import ProactiveAgentService


class FakeMarket:
    def __init__(self, prices=None, coin_list_count=0):
        self._prices = prices or {}
        self._coin_list_count = coin_list_count

    async def get_prices(self, coingecko_ids):
        return PriceSnapshot(
            prices={c: self._prices[c] for c in coingecko_ids if c in self._prices},
            stale=False,
            as_of=datetime.now(timezone.utc),
        )

    async def sync_coin_list(self):
        return self._coin_list_count


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, email="a@test.com", hashed_password="x"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _mk_alert(db, condition, threshold, coingecko_id="bitcoin"):
    return AlertService(db).create_alert(
        1,
        AlertCreate(
            coingecko_id=coingecko_id,
            symbol=coingecko_id[:3],
            name=coingecko_id,
            condition=condition,  # type: ignore[arg-type]
            threshold_price=Decimal(threshold),
        ),
    )


# ────────────────────────────── price_check ──────────────────────────────
def test_price_check_triggers_and_creates_notification(db):
    _mk_alert(db, "above", "60000")
    market = FakeMarket(prices={"bitcoin": 65000.0})  # vượt ngưỡng
    alert_svc = AlertService(db)
    notif_svc = NotificationService(db)

    n = asyncio.run(run_price_check(market, alert_svc, notif_svc))
    assert n == 1
    notifs = notif_svc.list_for_user(1)
    assert len(notifs) == 1
    assert notifs[0].type == "price_alert"
    assert notifs[0].alert_id is not None
    # alert đã bị tắt (one-shot)
    assert alert_svc.get_active_alerts() == []


def test_price_check_idempotent_no_double_trigger(db):
    _mk_alert(db, "above", "60000")
    market = FakeMarket(prices={"bitcoin": 65000.0})
    alert_svc, notif_svc = AlertService(db), NotificationService(db)

    asyncio.run(run_price_check(market, alert_svc, notif_svc))
    # chạy lại chu kỳ sau: alert đã tắt → không tạo thêm notification
    n2 = asyncio.run(run_price_check(market, alert_svc, notif_svc))
    assert n2 == 0
    assert len(notif_svc.list_for_user(1)) == 1


def test_price_check_below_and_no_trigger(db):
    _mk_alert(db, "below", "2000", coingecko_id="ethereum")
    # giá 2500 > ngưỡng 2000 → KHÔNG chạm (below cần price <= threshold)
    market = FakeMarket(prices={"ethereum": 2500.0})
    alert_svc, notif_svc = AlertService(db), NotificationService(db)
    n = asyncio.run(run_price_check(market, alert_svc, notif_svc))
    assert n == 0
    assert alert_svc.get_active_alerts()  # vẫn còn active


def test_price_check_no_active_alerts(db):
    n = asyncio.run(
        run_price_check(FakeMarket(), AlertService(db), NotificationService(db))
    )
    assert n == 0


# ────────────────────────────── refresh_coins ──────────────────────────────
def test_refresh_coins_returns_count(db):
    n = asyncio.run(run_refresh_coins(FakeMarket(coin_list_count=42)))
    assert n == 42


# ────────────────────────────── proactive_agent ──────────────────────────────
class FakeProactive:
    """Giả ProactiveAgentService — trả nhận định cố định theo kịch bản."""

    def __init__(self, users, insight):
        self._users = users
        self._insight = insight

    def users_with_holdings(self):
        return self._users

    async def insight_for_user(self, user):
        return self._insight


def test_proactive_creates_insight_when_text(db):
    user = db.get(User, 1)
    proactive = FakeProactive([user], "Danh mục tập trung 100% BTC — rủi ro cao.")
    notif_svc = NotificationService(db)
    n = asyncio.run(run_proactive_agent(proactive, notif_svc))
    assert n == 1
    notifs = notif_svc.list_for_user(1)
    assert notifs[0].type == "agent_insight"
    assert "BTC" in notifs[0].message


def test_proactive_skips_when_none(db):
    user = db.get(User, 1)
    proactive = FakeProactive([user], None)  # Gemini bảo NONE
    notif_svc = NotificationService(db)
    n = asyncio.run(run_proactive_agent(proactive, notif_svc))
    assert n == 0
    assert notif_svc.list_for_user(1) == []


def test_proactive_skips_empty_user_list(db):
    n = asyncio.run(
        run_proactive_agent(FakeProactive([], "x"), NotificationService(db))
    )
    assert n == 0


# ────────────────────────────── ProactiveAgentService.insight_for_user ──────────────────────────────
class FakeClient:
    def __init__(self, text, configured=True):
        self._text = text
        self._configured = configured

    @property
    def is_configured(self):
        return self._configured

    async def generate(self, *, system_instruction, turns, tool_specs):
        from app.agent.gemini_client import AgentResponse

        return AgentResponse(text=self._text)


class FakePortfolio:
    async def get_summary(self, uid):
        return {
            "holdings": [{"symbol": "BTC", "pnl_pct": -20.0}],
            "total_value_usd": 100,
        }

    async def get_allocation(self, uid):
        return {"allocation": [{"symbol": "BTC", "percent": 100.0}]}


class FakeNews:
    async def get_filtered(self, user, limit=5, coingecko_ids=None):
        return {"news": []}


def test_insight_returns_none_on_none_text(db):
    user = db.get(User, 1)
    svc = ProactiveAgentService(db, FakePortfolio(), FakeNews(), FakeClient("NONE"))
    assert asyncio.run(svc.insight_for_user(user)) is None


def test_insight_returns_text(db):
    user = db.get(User, 1)
    svc = ProactiveAgentService(
        db, FakePortfolio(), FakeNews(), FakeClient("Cảnh báo: tập trung 100% BTC.")
    )
    out = asyncio.run(svc.insight_for_user(user))
    assert out is not None and "BTC" in out


def test_insight_none_when_not_configured(db):
    user = db.get(User, 1)
    svc = ProactiveAgentService(
        db, FakePortfolio(), FakeNews(), FakeClient("x", configured=False)
    )
    assert asyncio.run(svc.insight_for_user(user)) is None


# ────────────────────────────── portfolio_snapshot (Phase 9) ──────────────────────────────
def _snap_tx(coingecko_id, qty, price):
    return TransactionCreate(
        coingecko_id=coingecko_id,
        symbol=coingecko_id[:3],
        name=coingecko_id,
        type="buy",
        quantity=Decimal(str(qty)),
        price=Decimal(str(price)),
        executed_at=datetime(2026, 1, 1),
    )


def test_portfolio_snapshot_saves_for_user_with_holdings(db):
    user = db.get(User, 1)
    portfolio = PortfolioService(db, FakeMarket(prices={"bitcoin": 200.0}))
    portfolio.add_transaction(1, _snap_tx("bitcoin", 1, 100))

    n = asyncio.run(run_portfolio_snapshot([user], portfolio, today=date(2026, 6, 1)))
    assert n == 1
    row = db.query(PortfolioSnapshot).filter_by(user_id=1).one()
    assert row.total_value == Decimal("200.0")
    assert row.snapshot_date == date(2026, 6, 1)


def test_portfolio_snapshot_skips_user_without_holdings(db):
    user = db.get(User, 1)
    portfolio = PortfolioService(db, FakeMarket())
    n = asyncio.run(run_portfolio_snapshot([user], portfolio, today=date(2026, 6, 1)))
    assert n == 0
    assert db.query(PortfolioSnapshot).count() == 0


def test_portfolio_snapshot_skips_user_on_price_failure_without_blocking_others(db):
    db.add(User(id=2, email="b@test.com", hashed_password="x"))
    db.commit()
    user1, user2 = db.get(User, 1), db.get(User, 2)

    setup = PortfolioService(db, FakeMarket())
    setup.add_transaction(1, _snap_tx("bitcoin", 1, 100))  # user 1: giá bitcoin sẽ lỗi
    setup.add_transaction(
        2, _snap_tx("ethereum", 1, 40)
    )  # user 2: giá lấy được bình thường

    # Market chỉ có giá ethereum — mô phỏng CoinGecko lỗi hoàn toàn cho bitcoin (không
    # có fallback cache), current_price None cho toàn bộ holdings của user 1.
    portfolio = PortfolioService(db, FakeMarket(prices={"ethereum": 50.0}))

    n = asyncio.run(
        run_portfolio_snapshot([user1, user2], portfolio, today=date(2026, 6, 1))
    )
    assert n == 1
    saved_user_ids = {r.user_id for r in db.query(PortfolioSnapshot).all()}
    assert saved_user_ids == {2}


def test_portfolio_snapshot_idempotent_same_day(db):
    user = db.get(User, 1)
    portfolio = PortfolioService(db, FakeMarket(prices={"bitcoin": 200.0}))
    portfolio.add_transaction(1, _snap_tx("bitcoin", 1, 100))

    today = date(2026, 6, 1)
    asyncio.run(run_portfolio_snapshot([user], portfolio, today=today))
    asyncio.run(
        run_portfolio_snapshot([user], portfolio, today=today)
    )  # job chạy lại trong ngày

    rows = db.query(PortfolioSnapshot).filter_by(user_id=1, snapshot_date=today).all()
    assert len(rows) == 1
