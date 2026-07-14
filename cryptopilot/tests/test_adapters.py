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
from app.services.news_service import _clear_news_cache


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
    _clear_news_cache()
    yield
    _clear_price_cache()
    _clear_news_cache()


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
        self.ohlc_calls = 0
        self.raise_on_ohlc = False

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

    async def get_ohlc(self, coingecko_id, days):
        self.ohlc_calls += 1
        if self.raise_on_ohlc:
            raise httpx.ConnectTimeout("boom")
        return [
            {
                "timestamp": 1700000000000,
                "open": 100.0,
                "high": 110.0,
                "low": 95.0,
                "close": 105.0,
            }
        ]


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
    # dòng kết quả link sang trang chi tiết coin
    assert "/market/coin/bitcoin" in r.text


# ──────────────────────────── OHLC (trang chi tiết coin) ────────────────────────────
def test_adapter_ohlc_normalizes_and_drops_malformed():
    def handler(request):
        assert request.url.path.endswith("/coins/bitcoin/ohlc")
        assert request.url.params["vs_currency"] == "usd"
        assert request.url.params["days"] == "7"
        return httpx.Response(
            200,
            json=[
                [1700000000000, 100.0, 110.0, 95.0, 105.0],
                [1700014400000, 105.0, 112.0, 104.0, 111.0],
                [1700028800000, 111.0],  # thiếu field — bị loại
            ],
        )

    ohlc = asyncio.run(make_adapter(handler).get_ohlc("bitcoin", 7))
    assert ohlc == [
        {
            "timestamp": 1700000000000,
            "open": 100.0,
            "high": 110.0,
            "low": 95.0,
            "close": 105.0,
        },
        {
            "timestamp": 1700014400000,
            "open": 105.0,
            "high": 112.0,
            "low": 104.0,
            "close": 111.0,
        },
    ]


def test_service_ohlc_caches_within_ttl(db):
    adapter = FakeAdapter()
    svc = MarketService(db, adapter)
    r1 = asyncio.run(svc.get_coin_ohlc("bitcoin", 30))
    r2 = asyncio.run(svc.get_coin_ohlc("bitcoin", 30))
    assert r1 == r2
    assert adapter.ohlc_calls == 1  # lần 2 lấy từ cache
    # khung days khác → cache key khác → gọi lại API
    asyncio.run(svc.get_coin_ohlc("bitcoin", 7))
    assert adapter.ohlc_calls == 2


def test_service_ohlc_graceful_returns_empty_on_error(db):
    adapter = FakeAdapter()
    adapter.raise_on_ohlc = True
    svc = MarketService(db, adapter)
    assert asyncio.run(svc.get_coin_ohlc("bitcoin", 30)) == []


# ──────────────────────────── News cho 1 coin ────────────────────────────
class FakeNewsAdapter:
    """Giả NewsDataInterface — bắt lại tham số currencies để assert mapping tên coin."""

    def __init__(self, posts=None, configured=True):
        self.posts = posts or []
        self._configured = configured
        self.last_currencies = None
        self.call_count = 0

    @property
    def is_configured(self):
        return self._configured

    async def get_posts(self, currencies=None, limit=5):
        self.call_count += 1
        self.last_currencies = currencies
        return self.posts[:limit]


def _news_service(db, adapter):
    from app.services.news_service import NewsService

    # get_news_for_coin không đụng portfolio_service — truyền None đủ cho test này
    return NewsService(db=db, adapter=adapter, portfolio_service=None)


def test_news_for_coin_maps_coingecko_id_to_name(db):
    db.add(Coin(coingecko_id="bitcoin", symbol="btc", name="Bitcoin"))
    db.commit()
    fake = FakeNewsAdapter(
        posts=[
            {
                "title": "BTC pumps",
                "source": "x",
                "url": "u",
                "published_at": "2026-07-13T00:00:00Z",
                "currencies": ["Bitcoin"],
            }
        ]
    )
    svc = _news_service(db, fake)
    posts = asyncio.run(svc.get_news_for_coin("bitcoin", limit=10))
    # map id → TÊN coin đầy đủ (tag CoinTelegraph dùng tên, không phải symbol)
    assert fake.last_currencies == ["Bitcoin"]
    assert posts[0]["title"] == "BTC pumps"


def test_news_for_coin_unknown_coin_returns_empty_without_calling_api(db):
    fake = FakeNewsAdapter(posts=[{"title": "x"}])
    svc = _news_service(db, fake)
    assert asyncio.run(svc.get_news_for_coin("khong-ton-tai")) == []
    assert fake.last_currencies is None  # không gọi adapter


def test_news_for_coin_caches_within_ttl(db):
    db.add(Coin(coingecko_id="bitcoin", symbol="btc", name="Bitcoin"))
    db.commit()
    fake = FakeNewsAdapter(posts=[{"title": "BTC news"}])
    svc = _news_service(db, fake)

    r1 = asyncio.run(svc.get_news_for_coin("bitcoin", limit=10))
    r2 = asyncio.run(svc.get_news_for_coin("bitcoin", limit=10))
    assert r1 == r2
    assert fake.call_count == 1  # lần 2 lấy từ cache, không gọi RSS lại

    # limit khác → cache key khác → gọi lại
    asyncio.run(svc.get_news_for_coin("bitcoin", limit=5))
    assert fake.call_count == 2


def test_get_filtered_caches_within_ttl(db):
    from app.models.transaction import Transaction  # noqa: F401 — đăng ký bảng
    from app.models.user import User
    from datetime import datetime
    from decimal import Decimal
    from app.schemas.transaction import TransactionCreate
    from app.services.portfolio_service import PortfolioService

    db.add(User(id=1, email="a@test.com", hashed_password="x"))
    db.commit()
    market = MarketService(db, FakeAdapter())
    portfolio = PortfolioService(db=db, market_service=market)
    portfolio.add_transaction(
        1,
        TransactionCreate(
            coingecko_id="bitcoin", symbol="btc", name="Bitcoin", type="buy",
            quantity=Decimal("1"), price=Decimal("100"),
            executed_at=datetime(2026, 1, 1),
        ),
    )
    fake = FakeNewsAdapter(posts=[{"title": "x"}])
    from app.services.news_service import NewsService

    svc = NewsService(db=db, adapter=fake, portfolio_service=portfolio)
    user = db.query(User).filter_by(id=1).first()

    asyncio.run(svc.get_filtered(user, limit=5))
    asyncio.run(svc.get_filtered(user, limit=5))
    assert fake.call_count == 1  # lần 2 lấy từ cache


# ──────────────────────────── Route /market/coin/{id} ────────────────────────────
def _app_with_coin_detail(db, adapter, news_adapter):
    app = _app_with_fake(db, adapter)
    app.dependency_overrides[market_module.get_news_service] = lambda: _news_service(
        db, news_adapter
    )
    return app


def test_route_coin_detail_renders_and_upserts_unknown_local_coin(db):
    # bảng coins trống — route tự search (FakeAdapter trả bitcoin) rồi render
    client = TestClient(
        _app_with_coin_detail(db, FakeAdapter(), FakeNewsAdapter(configured=False))
    )
    r = client.get("/market/coin/bitcoin")
    assert r.status_code == 200
    assert "Bitcoin" in r.text
    assert 'id="cp-candle-chart"' in r.text  # có OHLC → render chart container
    # nguồn chưa cấu hình + không có tin → thông báo nhẹ nhàng, không trống trơn
    assert "Chưa cấu hình nguồn tin tức" in r.text


def test_route_coin_detail_no_news_but_configured_shows_empty_message(db):
    # nguồn sẵn sàng (CoinTelegraph luôn configured) nhưng không có tin về coin này
    client = TestClient(
        _app_with_coin_detail(db, FakeAdapter(), FakeNewsAdapter(configured=True))
    )
    r = client.get("/market/coin/bitcoin")
    assert r.status_code == 200
    assert "Chưa có tin nào về BTC" in r.text
    assert "Chưa cấu hình nguồn tin tức" not in r.text


def test_route_coin_detail_shows_news_cards(db):
    db.add(Coin(coingecko_id="bitcoin", symbol="btc", name="Bitcoin"))
    db.commit()
    news_adapter = FakeNewsAdapter(
        posts=[
            {
                "title": "Bitcoin vượt mốc mới",
                "source": "Cointelegraph",
                "url": "http://n/1",
                "published_at": "2026-07-13T08:30:00Z",
                "currencies": ["Bitcoin"],
            }
        ]
    )
    client = TestClient(_app_with_coin_detail(db, FakeAdapter(), news_adapter))
    r = client.get("/market/coin/bitcoin?days=7")
    assert r.status_code == 200
    assert "Bitcoin vượt mốc mới" in r.text
    assert "Cointelegraph" in r.text
    assert "13/07/2026 08:30" in r.text  # published_at đã format


def test_route_coin_detail_unknown_coin_404(db):
    client = TestClient(
        _app_with_coin_detail(db, FakeAdapter(), FakeNewsAdapter())
    )
    # FakeAdapter search luôn trả bitcoin → id lạ vẫn không có trong bảng → 404
    r = client.get("/market/coin/khong-ton-tai")
    assert r.status_code == 404


def test_route_coin_detail_invalid_days_falls_back_to_default(db):
    db.add(Coin(coingecko_id="bitcoin", symbol="btc", name="Bitcoin"))
    db.commit()
    client = TestClient(
        _app_with_coin_detail(db, FakeAdapter(), FakeNewsAdapter())
    )
    r = client.get("/market/coin/bitcoin?days=999")
    assert r.status_code == 200
    # nút 30D active (rơi về default), không phải 999
    assert "?days=30" in r.text


# ──────────────────────────── CoinTelegraphAdapter (RSS) ────────────────────────────
def _rss(items):
    """Dựng RSS 2.0 tối giản từ list (title, link, pubDate, description)."""
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link>"
        f"<pubDate>{d}</pubDate><description>{desc}</description></item>"
        for t, u, d, desc in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<rss version="2.0"><channel><title>CT</title>{body}</channel></rss>'
    )


def make_ct_adapter(handler):
    from app.adapters.cointelegraph_adapter import CoinTelegraphAdapter

    return CoinTelegraphAdapter(
        base_url="https://ct.test", transport=httpx.MockTransport(handler)
    )


def test_ct_adapter_single_coin_uses_tag_feed_and_normalizes():
    def handler(request):
        assert request.url.path == "/rss/tag/ethereum"
        return httpx.Response(
            200,
            text=_rss(
                [
                    (
                        "ETH breaks out",
                        "https://ct.test/a1",
                        "Sun, 12 Jul 2026 18:00:00 +0000",
                        "Ether news",
                    )
                ]
            ),
        )

    posts = asyncio.run(make_ct_adapter(handler).get_posts(["Ethereum"], limit=5))
    assert len(posts) == 1
    p = posts[0]
    assert p["title"] == "ETH breaks out"
    assert p["url"] == "https://ct.test/a1"
    assert p["source"] == "Cointelegraph"
    assert p["published_at"] == "2026-07-12T18:00:00+00:00"  # RFC822 → ISO
    assert p["currencies"] == ["Ethereum"]
    assert "_description" not in p  # key nội bộ không lộ ra ngoài


def test_ct_adapter_tag_empty_falls_back_to_general_with_client_filter():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/rss/tag/bitcoin-cash":
            return httpx.Response(404)
        return httpx.Response(
            200,
            text=_rss(
                [
                    (
                        "Bitcoin Cash surges",
                        "https://ct.test/a1",
                        "Sun, 12 Jul 2026 18:00:00 +0000",
                        "",
                    ),
                    (
                        "Solana update",
                        "https://ct.test/a2",
                        "Sun, 12 Jul 2026 17:00:00 +0000",
                        "",
                    ),
                ]
            ),
        )

    posts = asyncio.run(make_ct_adapter(handler).get_posts(["Bitcoin Cash"], limit=5))
    assert calls == ["/rss/tag/bitcoin-cash", "/rss"]
    assert [p["title"] for p in posts] == ["Bitcoin Cash surges"]  # đã lọc client-side


def test_ct_adapter_multi_coin_filters_general_feed_case_insensitive():
    def handler(request):
        assert request.url.path == "/rss"
        return httpx.Response(
            200,
            text=_rss(
                [
                    (
                        "BITCOIN hits ATH",
                        "https://ct.test/a1",
                        "Sun, 12 Jul 2026 18:00:00 +0000",
                        "",
                    ),
                    (
                        "Ripple lawsuit ends",
                        "https://ct.test/a2",
                        "Sun, 12 Jul 2026 17:00:00 +0000",
                        "XRP news about &lt;b&gt;ethereum&lt;/b&gt; too",
                    ),
                    (
                        "Dogecoin memes",
                        "https://ct.test/a3",
                        "Sun, 12 Jul 2026 16:00:00 +0000",
                        "",
                    ),
                ]
            ),
        )

    posts = asyncio.run(
        make_ct_adapter(handler).get_posts(["Bitcoin", "Ethereum"], limit=5)
    )
    titles = [p["title"] for p in posts]
    # match cả title lẫn description, không phân biệt hoa thường
    assert titles == ["BITCOIN hits ATH", "Ripple lawsuit ends"]
    assert posts[1]["currencies"] == ["ethereum"]


def test_ct_adapter_no_filter_returns_general_feed_with_limit():
    def handler(request):
        assert request.url.path == "/rss"
        return httpx.Response(
            200,
            text=_rss(
                [
                    ("A", "https://ct.test/a", "Sun, 12 Jul 2026 18:00:00 +0000", ""),
                    ("B", "https://ct.test/b", "Sun, 12 Jul 2026 17:00:00 +0000", ""),
                ]
            ),
        )

    posts = asyncio.run(make_ct_adapter(handler).get_posts(None, limit=1))
    assert len(posts) == 1  # limit áp dụng
    assert posts[0]["title"] == "A"


def test_ct_adapter_graceful_on_http_error_and_bad_xml():
    def handler_error(request):
        return httpx.Response(500)

    assert asyncio.run(make_ct_adapter(handler_error).get_posts(None)) == []

    def handler_bad_xml(request):
        return httpx.Response(200, text="not xml at all <<<")

    assert asyncio.run(make_ct_adapter(handler_bad_xml).get_posts(None)) == []


def test_ct_adapter_is_configured_always_true():
    from app.adapters.cointelegraph_adapter import CoinTelegraphAdapter

    assert CoinTelegraphAdapter(base_url="https://ct.test").is_configured is True
