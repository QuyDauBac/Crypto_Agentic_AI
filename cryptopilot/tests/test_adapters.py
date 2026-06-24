"""Tests Phase 2 — Market Data layer.

Không gọi mạng thật:
  - Adapter: dùng httpx.MockTransport để giả response CoinGecko
  - Service: dùng FakeAdapter (implement MarketDataInterface) để kiểm cache + graceful degradation
  - Route: override dependency get_market_service

Chạy async bằng asyncio.run() để không cần thêm pytest-asyncio.
"""

import asyncio
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.adapters.market_data import MarketDataInterface
from app.api import market as market_module
from app.core.database import Base
from app.models.coin import Coin
from app.services.market_service import MarketService, _clear_price_cache


# ──────────────────────────── Fixtures ────────────────────────────
@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clear_cache():
    _clear_price_cache()
    yield
    _clear_price_cache()


def make_adapter(handler):
    return CoinGeckoAdapter(
        base_url="https://api.test/v3",
        demo_key="",
        transport=httpx.MockTransport(handler),
    )


class FakeAdapter(MarketDataInterface):
    """Adapter giả để test service mà không đụng mạng."""

    def __init__(self):
        self.price_calls = 0
        self.prices_data = {"bitcoin": 67000.0, "ethereum": 3500.0}
        self.raise_on_prices = False

    async def get_prices(self, coingecko_ids):
        self.price_calls += 1
        if self.raise_on_prices:
            raise httpx.ConnectTimeout("boom")
        return {c: self.prices_data[c] for c in coingecko_ids if c in self.prices_data}

    async def search_coins(self, query):
        return [
            {
                "coingecko_id": "bitcoin",
                "symbol": "btc",
                "name": "Bitcoin",
                "image_url": None,
            }
        ]

    async def get_market_history(self, coingecko_id, days):
        return [{"timestamp": 1, "price": 1.0}]

    async def get_coin_list(self):
        return [{"coingecko_id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}]


# ──────────────────────────── Adapter ────────────────────────────
def test_adapter_get_prices_normalizes():
    def handler(request):
        assert request.url.path.endswith("/simple/price")
        return httpx.Response(
            200, json={"bitcoin": {"usd": 67420}, "ethereum": {"usd": 3500}}
        )

    prices = asyncio.run(make_adapter(handler).get_prices(["bitcoin", "ethereum"]))
    assert prices == {"bitcoin": 67420.0, "ethereum": 3500.0}


def test_adapter_get_prices_empty_input_no_call():
    def handler(request):  # pragma: no cover - không được gọi
        raise AssertionError("không nên gọi mạng khi input rỗng")

    assert asyncio.run(make_adapter(handler).get_prices([])) == {}


def test_adapter_search_normalizes_and_skips_missing_id():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "coins": [
                    {
                        "id": "bitcoin",
                        "symbol": "BTC",
                        "name": "Bitcoin",
                        "large": "http://img/btc.png",
                    },
                    {"symbol": "X", "name": "no id — bị loại"},
                ]
            },
        )

    results = asyncio.run(make_adapter(handler).search_coins("bit"))
    assert len(results) == 1
    assert results[0]["coingecko_id"] == "bitcoin"
    assert results[0]["symbol"] == "btc"  # đã hạ chữ thường
    assert results[0]["image_url"] == "http://img/btc.png"


def test_adapter_history_drops_malformed_points():
    def handler(request):
        return httpx.Response(
            200,
            json={"prices": [[1700000000000, 100.0], [1700000600000, 101.5], [123]]},
        )

    hist = asyncio.run(make_adapter(handler).get_market_history("bitcoin", 1))
    assert hist == [
        {"timestamp": 1700000000000, "price": 100.0},
        {"timestamp": 1700000600000, "price": 101.5},
    ]


# ──────────────────────────── Service ────────────────────────────
def test_service_caches_within_ttl(db):
    adapter = FakeAdapter()
    svc = MarketService(db, adapter)
    snap1 = asyncio.run(svc.get_prices(["bitcoin"]))
    snap2 = asyncio.run(svc.get_prices(["bitcoin"]))
    assert snap1.prices["bitcoin"] == 67000.0
    assert snap2.prices["bitcoin"] == 67000.0
    assert adapter.price_calls == 1  # lần 2 lấy từ cache, không gọi lại API
    assert snap1.stale is False


def test_service_graceful_degradation_uses_db_fallback(db):
    db.add(
        Coin(
            coingecko_id="bitcoin",
            symbol="btc",
            name="Bitcoin",
            last_price=Decimal("60000"),
        )
    )
    db.commit()

    adapter = FakeAdapter()
    adapter.raise_on_prices = True
    svc = MarketService(db, adapter)

    snap = asyncio.run(svc.get_prices(["bitcoin"]))
    assert snap.stale is True
    assert snap.prices["bitcoin"] == 60000.0  # giá cache cuối từ DB


def test_service_persists_last_price_after_fetch(db):
    db.add(Coin(coingecko_id="bitcoin", symbol="btc", name="Bitcoin"))
    db.commit()

    svc = MarketService(db, FakeAdapter())
    asyncio.run(svc.get_prices(["bitcoin"]))

    coin = db.query(Coin).filter_by(coingecko_id="bitcoin").one()
    assert coin.last_price is not None
    assert float(coin.last_price) == 67000.0
    assert coin.last_synced_at is not None


def test_service_search_upserts_and_resolves_symbol(db):
    svc = MarketService(db, FakeAdapter())
    results = asyncio.run(svc.search_coins("bit"))
    assert results[0].coingecko_id == "bitcoin"
    # search xong đã upsert vào bảng coins → tra symbol local được
    assert svc.resolve_symbol("btc") == "bitcoin"
    assert svc.resolve_symbol("doge") is None


# ──────────────────────────── Route ────────────────────────────
def _app_with_fake(db, adapter):
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    app = FastAPI()
    static_dir = Path(market_module.__file__).resolve().parent.parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(market_module.router)
    app.dependency_overrides[market_module.get_market_service] = lambda: MarketService(
        db=db, adapter=adapter
    )
    return app


def test_route_api_prices_returns_json(db):
    client = TestClient(_app_with_fake(db, FakeAdapter()))
    r = client.get("/market/api/prices?ids=bitcoin,ethereum")
    assert r.status_code == 200
    body = r.json()
    assert body["prices"]["bitcoin"] == 67000.0
    assert body["stale"] is False


def test_route_market_page_renders(db):
    client = TestClient(_app_with_fake(db, FakeAdapter()))
    r = client.get("/market?q=bit")
    assert r.status_code == 200
    assert "Bitcoin" in r.text
