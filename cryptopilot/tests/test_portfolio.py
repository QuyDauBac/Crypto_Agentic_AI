"""Tests Phase 3 — Portfolio.

- Holdings: gộp đúng net_quantity + avg_cost qua nhiều buy/sell
- Dashboard: P&L, allocation, stale flag (dùng FakeMarket, không gọi mạng)
- CRUD: scope theo user (user B không xóa được tx của user A)
- Route: dashboard cần auth (401), hoạt động khi override dependency
- Phase 9: snapshot lịch sử (get_value_history/save_snapshot/get_current_value),
  đóng gói chart_data theo khung thời gian
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import portfolio as pf_module
from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.models.coin import Coin
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.transaction import Transaction  # noqa: F401  (đăng ký bảng)
from app.models.user import User
from app.schemas.market import PricePoint, PriceSnapshot
from app.schemas.transaction import TransactionCreate
from app.services.portfolio_service import PortfolioService
from app.services.market_service import _clear_price_cache


# ──────────────────────────── Fakes & fixtures ────────────────────────────
class FakeMarket:
    """Giả MarketService — chỉ cần get_prices + get_history (async)."""

    def __init__(self, prices=None, stale=False, history=None):
        self._prices = prices or {}
        self._stale = stale
        self._history = history or []

    async def get_prices(self, coingecko_ids):
        return PriceSnapshot(
            prices={c: self._prices[c] for c in coingecko_ids if c in self._prices},
            stale=self._stale,
            as_of=datetime.now(timezone.utc),
        )

    async def get_history(self, coingecko_id, days):
        return [PricePoint(**p) for p in self._history]


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # seed 1 user
    session.add(User(id=1, email="a@test.com", hashed_password="x"))
    session.add(User(id=2, email="b@test.com", hashed_password="x"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clear_cache():
    _clear_price_cache()
    yield
    _clear_price_cache()


def make_service(db, market=None):
    return PortfolioService(db=db, market_service=market or FakeMarket())


def _tx(coingecko_id, type_, qty, price, when="2026-01-01T00:00", symbol="", name=""):
    return TransactionCreate(
        coingecko_id=coingecko_id,
        symbol=symbol or coingecko_id[:3],
        name=name or coingecko_id,
        type=type_,
        quantity=Decimal(str(qty)),
        price=Decimal(str(price)),
        executed_at=datetime.fromisoformat(when),
    )


# ──────────────────────────── Holdings math ────────────────────────────
def test_holdings_avg_cost_and_net_quantity(db):
    svc = make_service(db)
    svc.add_transaction(1, _tx("bitcoin", "buy", 1, 100))
    svc.add_transaction(1, _tx("bitcoin", "buy", 1, 200))
    svc.add_transaction(1, _tx("bitcoin", "sell", "0.5", 300))

    holdings = svc.get_holdings(1)
    assert len(holdings) == 1
    h = holdings[0]
    assert h.net_quantity == Decimal("1.5")
    assert h.avg_cost_price == Decimal("150")  # 300 cost / 2 mua, bán không đổi avg
    assert h.cost_basis == Decimal("225.0")  # 1.5 × 150


def test_holdings_excludes_fully_sold(db):
    svc = make_service(db)
    svc.add_transaction(1, _tx("bitcoin", "buy", 1, 100))
    svc.add_transaction(1, _tx("bitcoin", "sell", 1, 120))
    assert svc.get_holdings(1) == []


# ──────────────────────────── Dashboard / P&L / allocation ────────────────────────────
def test_dashboard_pnl_and_allocation(db):
    import asyncio

    market = FakeMarket(prices={"bitcoin": 300.0, "ethereum": 150.0})
    svc = make_service(db, market)
    # BTC: nắm 1.5 @ avg 150 → value 450, cost 225, pnl +225 (+100%)
    svc.add_transaction(1, _tx("bitcoin", "buy", 1, 100))
    svc.add_transaction(1, _tx("bitcoin", "buy", 1, 200))
    svc.add_transaction(1, _tx("bitcoin", "sell", "0.5", 300))
    # ETH: nắm 1 @ 100 → value 150, cost 100, pnl +50
    svc.add_transaction(1, _tx("ethereum", "buy", 1, 100))

    d = asyncio.run(svc.get_dashboard(1))
    assert d.total_value == pytest.approx(600.0)
    assert d.total_cost == pytest.approx(325.0)
    assert d.total_pnl == pytest.approx(275.0)

    by_id = {h.coingecko_id: h for h in d.holdings}
    assert by_id["bitcoin"].unrealized_pnl == pytest.approx(225.0)
    assert by_id["bitcoin"].pnl_pct == pytest.approx(100.0)
    assert by_id["bitcoin"].allocation_pct == pytest.approx(75.0)
    assert by_id["ethereum"].allocation_pct == pytest.approx(25.0)


def test_dashboard_stale_when_market_down(db):
    import asyncio

    market = FakeMarket(prices={"bitcoin": 50.0}, stale=True)
    svc = make_service(db, market)
    svc.add_transaction(1, _tx("bitcoin", "buy", 1, 100))
    d = asyncio.run(svc.get_dashboard(1))
    assert d.stale is True


def test_dashboard_btc_benchmark(db):
    import asyncio

    market = FakeMarket(
        prices={"bitcoin": 110.0},
        history=[{"timestamp": 1, "price": 100.0}, {"timestamp": 2, "price": 130.0}],
    )
    svc = make_service(db, market)
    svc.add_transaction(1, _tx("bitcoin", "buy", 1, 100))
    d = asyncio.run(svc.get_dashboard(1))
    assert d.benchmark is not None
    assert d.benchmark.btc_change_pct == pytest.approx(30.0)  # (130-100)/100


# ──────────────────────────── CRUD scope ────────────────────────────
def test_transactions_scoped_per_user(db):
    svc = make_service(db)
    tx = svc.add_transaction(1, _tx("bitcoin", "buy", 1, 100))
    # user 2 KHÔNG xóa/sửa được tx của user 1
    assert svc.delete_transaction(2, tx.id) is False
    assert svc.update_transaction(2, tx.id, _tx("bitcoin", "buy", 9, 9)) is None
    # user 1 thì được
    assert svc.get_transaction(1, tx.id) is not None
    assert svc.delete_transaction(1, tx.id) is True


def test_add_reuses_existing_coin_row(db):
    svc = make_service(db)
    svc.add_transaction(1, _tx("bitcoin", "buy", 1, 100))
    svc.add_transaction(1, _tx("bitcoin", "buy", 2, 110))
    assert db.query(Coin).filter_by(coingecko_id="bitcoin").count() == 1


# ──────────────────────────── Routes ────────────────────────────
def _build_app(db, market=None, user=None):
    app = FastAPI()
    static_dir = Path(pf_module.__file__).resolve().parent.parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(pf_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[pf_module.get_portfolio_service] = lambda: (
        PortfolioService(db=db, market_service=market or FakeMarket())
    )
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_route_dashboard_requires_auth(db):
    # KHÔNG override get_current_user, không gửi cookie → 401
    app = _build_app(db)
    client = TestClient(app)
    res = client.get("/portfolio", follow_redirects=False)
    assert res.status_code == 401


def test_route_dashboard_renders_for_user(db):
    user = db.get(User, 1)
    market = FakeMarket(prices={"bitcoin": 300.0})
    app = _build_app(db, market=market, user=user)
    # seed 1 giao dịch qua service
    PortfolioService(db, market).add_transaction(
        1, _tx("bitcoin", "buy", 1, 100, name="Bitcoin")
    )
    client = TestClient(app)
    res = client.get("/portfolio")
    assert res.status_code == 200
    assert "Bitcoin" in res.text


def test_route_add_then_delete_transaction(db):
    user = db.get(User, 1)
    app = _build_app(db, user=user)
    client = TestClient(app)
    res = client.post(
        "/portfolio/transactions",
        data={
            "coingecko_id": "bitcoin",
            "symbol": "btc",
            "name": "Bitcoin",
            "type": "buy",
            "quantity": "2",
            "price": "100",
            "fee": "",
            "note": "test",
            "executed_at": "2026-01-01T10:00",
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    txs = PortfolioService(db, FakeMarket()).list_transactions(1)
    assert len(txs) == 1

    res2 = client.post(
        f"/portfolio/transactions/{txs[0].id}/delete", follow_redirects=False
    )
    assert res2.status_code == 303
    assert PortfolioService(db, FakeMarket()).list_transactions(1) == []


# ──────────────────────────── Phase 9: snapshot lịch sử ────────────────────────────
def _seed_snapshot(db, user_id, d, value, cost=0.0):
    db.add(
        PortfolioSnapshot(
            user_id=user_id,
            snapshot_date=d,
            total_value=Decimal(str(value)),
            total_cost=Decimal(str(cost)),
        )
    )
    db.commit()


def test_get_value_history_filters_by_days_and_orders(db):
    svc = make_service(db)
    today = date.today()
    _seed_snapshot(db, 1, today - timedelta(days=40), 100.0)  # ngoài cửa sổ 30 ngày
    _seed_snapshot(db, 1, today - timedelta(days=5), 200.0)
    _seed_snapshot(db, 1, today, 300.0)

    history = svc.get_value_history(1, 30)
    assert [v for _, v in history] == [200.0, 300.0]  # sắp tăng dần theo ngày
    assert history[0][0] == today - timedelta(days=5)


def test_save_snapshot_upserts_same_day(db):
    svc = make_service(db)
    today = date.today()
    svc.save_snapshot(1, today, 100.0, 80.0)
    svc.save_snapshot(
        1, today, 150.0, 80.0
    )  # job chạy lại trong ngày → update, không tạo trùng

    rows = db.query(PortfolioSnapshot).filter_by(user_id=1, snapshot_date=today).all()
    assert len(rows) == 1
    assert rows[0].total_value == Decimal("150.0")


def test_get_current_value_none_when_no_holdings(db):
    import asyncio

    svc = make_service(db)
    assert asyncio.run(svc.get_current_value(1)) is None


def test_get_current_value_returns_totals(db):
    import asyncio

    market = FakeMarket(prices={"bitcoin": 200.0})
    svc = make_service(db, market)
    svc.add_transaction(1, _tx("bitcoin", "buy", 1, 100))
    result = asyncio.run(svc.get_current_value(1))
    assert result == pytest.approx((200.0, 100.0))


def test_get_current_value_none_when_price_fetch_fails_entirely(db):
    import asyncio

    # FakeMarket không trả giá cho coin nào (mô phỏng CoinGecko lỗi hoàn toàn,
    # không có fallback cache) → current_price None cho mọi holding.
    market = FakeMarket(prices={})
    svc = make_service(db, market)
    svc.add_transaction(1, _tx("bitcoin", "buy", 1, 100))
    assert asyncio.run(svc.get_current_value(1)) is None


# ──────────────────────────── Phase 9: chart_data windowing ────────────────────────────
def _epoch_ms(d):
    return int(
        datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000
    )


def _consecutive_history(today, n, values):
    """n ngày liên tục kết thúc ở `today`, giá trị lấy từ `values` (len == n)."""
    dates = [today - timedelta(days=i) for i in range(n - 1, -1, -1)]
    return list(zip(dates, values))


def test_continuous_days_zero_when_empty(db):
    assert pf_module._continuous_days([]) == 0


def test_continuous_days_breaks_on_gap(db):
    today = date.today()
    # hôm nay + hôm qua liên tục, nhưng 5 ngày trước bị đứt quãng (gap 3 ngày)
    value_history = [
        (today - timedelta(days=5), 90.0),
        (today - timedelta(days=1), 100.0),
        (today, 110.0),
    ]
    assert pf_module._continuous_days(value_history) == 2  # chỉ đếm hôm nay + hôm qua


def test_build_chart_data_locked_below_window_threshold(db):
    today = date.today()
    # chỉ 2 ngày liên tục — chưa đủ cả 7D (cần >=7)
    value_history = _consecutive_history(today, 2, [100.0, 110.0])
    btc_history = [
        PricePoint(timestamp=_epoch_ms(d), price=50.0) for d, _ in value_history
    ]
    chart = pf_module._build_chart_data(value_history, btc_history)
    for tf, days in pf_module._CHART_WINDOWS.items():
        assert chart[tf]["unlocked"] is False
        assert chart[tf]["days_remaining"] == days - 2
        assert chart[tf]["labels"] == []


def test_build_chart_data_unlocks_only_windows_with_enough_continuous_days(db):
    today = date.today()
    # đúng 7 ngày liên tục — 7D unlocked, các khung dài hơn vẫn khóa với days_remaining đúng
    values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 200.0]
    value_history = _consecutive_history(today, 7, values)
    btc_history = [
        PricePoint(timestamp=_epoch_ms(d), price=50.0 + i)
        for i, (d, _) in enumerate(value_history)
    ]
    chart = pf_module._build_chart_data(value_history, btc_history)

    assert chart["7D"]["unlocked"] is True
    assert chart["7D"]["days_remaining"] == 0
    assert len(chart["7D"]["labels"]) == 7
    assert chart["7D"]["portfolio"] == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 100.0]

    assert chart["30D"]["unlocked"] is False
    assert chart["30D"]["days_remaining"] == 23
    assert chart["30D"]["labels"] == []
    assert chart["90D"]["days_remaining"] == 83
    assert chart["1Y"]["days_remaining"] == 358


def test_route_dashboard_shows_accumulating_message_when_no_history(db):
    user = db.get(User, 1)
    app = _build_app(db, market=FakeMarket(prices={"bitcoin": 300.0}), user=user)
    PortfolioService(db, FakeMarket(prices={"bitcoin": 300.0})).add_transaction(
        1, _tx("bitcoin", "buy", 1, 100, name="Bitcoin")
    )
    client = TestClient(app)
    res = client.get("/portfolio")
    assert res.status_code == 200
    assert "Đang tích lũy dữ liệu lịch sử" in res.text


def test_route_dashboard_locks_larger_windows_with_few_days(db):
    """3 ngày snapshot liên tục: KHÔNG được mở khóa 1Y chỉ vì 'có vài điểm' (bug cũ)."""
    user = db.get(User, 1)
    today = date.today()
    for days_ago, value in [(2, 100.0), (1, 150.0), (0, 200.0)]:
        _seed_snapshot(db, 1, today - timedelta(days=days_ago), value)
    market = FakeMarket(
        prices={"bitcoin": 300.0},
        history=[
            {"timestamp": _epoch_ms(today - timedelta(days=2)), "price": 50.0},
            {"timestamp": _epoch_ms(today - timedelta(days=1)), "price": 55.0},
            {"timestamp": _epoch_ms(today), "price": 60.0},
        ],
    )
    app = _build_app(db, market=market, user=user)
    PortfolioService(db, market).add_transaction(
        1, _tx("bitcoin", "buy", 1, 100, name="Bitcoin")
    )
    client = TestClient(app)
    res = client.get("/portfolio")
    assert res.status_code == 200
    # chưa đủ 7 ngày liên tục cho khung nhỏ nhất → vẫn hiện thông báo tích lũy
    assert "Đang tích lũy dữ liệu lịch sử" in res.text
    assert 'id="cp-perf-chart"' not in res.text


def test_route_dashboard_renders_chart_when_7_continuous_days(db):
    user = db.get(User, 1)
    today = date.today()
    history_pricepoints = []
    for days_ago in range(6, -1, -1):
        d = today - timedelta(days=days_ago)
        _seed_snapshot(db, 1, d, 100.0 + days_ago)
        history_pricepoints.append(
            {"timestamp": _epoch_ms(d), "price": 50.0 + days_ago}
        )
    market = FakeMarket(prices={"bitcoin": 300.0}, history=history_pricepoints)
    app = _build_app(db, market=market, user=user)
    PortfolioService(db, market).add_transaction(
        1, _tx("bitcoin", "buy", 1, 100, name="Bitcoin")
    )
    client = TestClient(app)
    res = client.get("/portfolio")
    assert res.status_code == 200
    assert "Đang tích lũy dữ liệu lịch sử" not in res.text
    assert 'id="cp-perf-chart"' in res.text
    assert 'class="cp-tf-btn is-locked"' in res.text  # 30D/90D/1Y vẫn khóa
