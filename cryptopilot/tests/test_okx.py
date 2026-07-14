"""Tests Phase 8 — OKX wallet integration.

- Encryption: roundtrip Fernet, lỗi rõ ràng khi ENCRYPTION_KEY chưa cấu hình
- OKXAdapter: header ký HMAC đúng field, gọi get_balance/get_fills_history qua MockTransport
- OKXService: connect (thành công/thất bại), disconnect, get_status, sync + dedupe
  (sync 2 lần không tạo trùng transaction), map symbol → coin qua bảng coins local
- Route: /wallet cần auth; connect/disconnect/sync qua form; lỗi hiển thị đúng
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.market_data import MarketDataInterface
from app.adapters.okx_adapter import OKXAdapter, OKXAPIError
from app.api import wallet as wallet_module
from app.api.deps import get_current_user
from app.core import encryption
from app.core.config import settings
from app.core.database import Base, get_db
from app.models.coin import Coin
from app.models.okx_connection import OKXConnection
from app.models.okx_synced_fill import OKXSyncedFill
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.okx import OKXConnectRequest
from app.services.market_service import MarketService
from app.services.okx_service import (
    OKXConnectError,
    OKXNotConnectedError,
    OKXService,
)


# ──────────────────────────── Fixtures ────────────────────────────
@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    """Cấp ENCRYPTION_KEY hợp lệ cho mọi test, phục hồi lại sau mỗi test."""
    from cryptography.fernet import Fernet

    monkeypatch.setattr(settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    yield


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, email="a@test.com", hashed_password="x"))
    session.add(User(id=2, email="b@test.com", hashed_password="x"))
    # seed sẵn Coin để _resolve_coin không cần gọi mạng (search_coins)
    session.add(Coin(coingecko_id="bitcoin", symbol="btc", name="Bitcoin"))
    session.add(Coin(coingecko_id="ethereum", symbol="eth", name="Ethereum"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


class FakeMarketService(MarketService):
    """MarketService không gọi mạng — chỉ dùng cho test (search_coins không cần thiết
    vì coins đã seed sẵn, nhưng khai báo để OKXService khởi tạo bình thường)."""

    def __init__(self, db):
        super().__init__(db=db, adapter=_NullAdapter())


class _NullAdapter(MarketDataInterface):
    async def get_prices(self, coingecko_ids):
        return {}

    async def get_market_history(self, coingecko_id, days=30):
        return []

    async def search_coins(self, query):
        return []

    async def get_coin_list(self):
        return []

    async def get_ohlc(self, coingecko_id, days):
        return []


FILLS_FIXTURE = [
    {
        "tradeId": "trade-1",
        "instId": "BTC-USDT",
        "side": "buy",
        "fillSz": "0.01",
        "fillPx": "60000",
        "ts": "1700000000000",
    },
    {
        "tradeId": "trade-2",
        "instId": "ETH-USDT",
        "side": "sell",
        "fillSz": "1.5",
        "fillPx": "3000",
        "ts": "1700000100000",
    },
    {
        # coin lạ không có trong bảng coins local và search_coins trả rỗng → phải bị bỏ qua
        "tradeId": "trade-3",
        "instId": "ZZZUNKNOWN-USDT",
        "side": "buy",
        "fillSz": "10",
        "fillPx": "1",
        "ts": "1700000200000",
    },
]


class FakeOKXAdapter:
    """Thay OKXAdapter thật trong test service — không gọi mạng OKX."""

    fail_balance = False

    def __init__(self, api_key, api_secret, passphrase, **kw):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase

    async def get_balance(self):
        if FakeOKXAdapter.fail_balance:
            raise OKXAPIError("invalid key")
        return [{"details": [{"ccy": "USDT", "availBal": "100"}]}]

    async def get_fills_history(self, limit=100):
        return FILLS_FIXTURE


# ──────────────────────────── Encryption ────────────────────────────
def test_encryption_roundtrip():
    token = encryption.encrypt("super-secret-value")
    assert token != "super-secret-value"
    assert encryption.decrypt(token) == "super-secret-value"


def test_encryption_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "")
    with pytest.raises(encryption.EncryptionNotConfigured):
        encryption.encrypt("x")


def test_decrypt_wrong_key_raises(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    token = encryption.encrypt("hello")
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(ValueError):
        encryption.decrypt(token)


# ──────────────────────────── OKXAdapter (HMAC signing + HTTP) ────────────────────────────
def test_okx_adapter_signs_and_parses_balance():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["url"] = str(request.url)
        assert request.headers["OK-ACCESS-KEY"] == "key123"
        assert request.headers["OK-ACCESS-PASSPHRASE"] == "pass123"
        assert "OK-ACCESS-SIGN" in request.headers
        assert "OK-ACCESS-TIMESTAMP" in request.headers
        return httpx.Response(
            200, json={"code": "0", "msg": "", "data": [{"details": []}]}
        )

    adapter = OKXAdapter(
        "key123",
        "secret123",
        "pass123",
        base_url="https://okx.test",
        transport=httpx.MockTransport(handler),
    )
    data = asyncio.run(adapter.get_balance())
    assert data == [{"details": []}]
    assert "account/balance" in captured["url"]


def test_okx_adapter_fills_history_sends_spot_instype():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "instType=SPOT" in str(request.url)
        return httpx.Response(200, json={"code": "0", "msg": "", "data": FILLS_FIXTURE})

    adapter = OKXAdapter(
        "k",
        "s",
        "p",
        base_url="https://okx.test",
        transport=httpx.MockTransport(handler),
    )
    data = asyncio.run(adapter.get_fills_history())
    assert len(data) == 3


def test_okx_adapter_raises_on_error_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"code": "50111", "msg": "invalid key", "data": []}
        )

    adapter = OKXAdapter(
        "k",
        "s",
        "p",
        base_url="https://okx.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OKXAPIError):
        asyncio.run(adapter.get_balance())


# ──────────────────────────── OKXService ────────────────────────────
def test_service_connect_success(db, monkeypatch):
    monkeypatch.setattr("app.services.okx_service.OKXAdapter", FakeOKXAdapter)
    FakeOKXAdapter.fail_balance = False
    service = OKXService(db, FakeMarketService(db))
    status = asyncio.run(
        service.connect(
            1, OKXConnectRequest(api_key="k", api_secret="s", passphrase="p")
        )
    )
    assert status.is_connected is True
    conn = db.query(OKXConnection).filter_by(user_id=1).first()
    assert conn is not None
    # credentials phải được mã hóa — không lưu plaintext
    assert conn.api_key_encrypted != "k"
    assert encryption.decrypt(conn.api_key_encrypted) == "k"


def test_service_connect_failure_does_not_save(db, monkeypatch):
    monkeypatch.setattr("app.services.okx_service.OKXAdapter", FakeOKXAdapter)
    FakeOKXAdapter.fail_balance = True
    service = OKXService(db, FakeMarketService(db))
    with pytest.raises(OKXConnectError):
        asyncio.run(
            service.connect(
                1, OKXConnectRequest(api_key="k", api_secret="s", passphrase="p")
            )
        )
    assert db.query(OKXConnection).filter_by(user_id=1).first() is None
    FakeOKXAdapter.fail_balance = False


def test_service_status_and_disconnect(db, monkeypatch):
    monkeypatch.setattr("app.services.okx_service.OKXAdapter", FakeOKXAdapter)
    FakeOKXAdapter.fail_balance = False
    service = OKXService(db, FakeMarketService(db))
    assert service.get_status(1).is_connected is False

    asyncio.run(
        service.connect(
            1, OKXConnectRequest(api_key="k", api_secret="s", passphrase="p")
        )
    )
    assert service.get_status(1).is_connected is True

    assert service.disconnect(1) is True
    assert service.get_status(1).is_connected is False
    assert service.disconnect(1) is False  # đã xóa rồi, gọi lại → False


def test_service_sync_requires_connection(db):
    service = OKXService(db, FakeMarketService(db))
    with pytest.raises(OKXNotConnectedError):
        asyncio.run(service.sync(1))


def test_service_sync_imports_transactions_and_skips_unknown_coin(db, monkeypatch):
    monkeypatch.setattr("app.services.okx_service.OKXAdapter", FakeOKXAdapter)
    FakeOKXAdapter.fail_balance = False
    service = OKXService(db, FakeMarketService(db))
    asyncio.run(
        service.connect(
            1, OKXConnectRequest(api_key="k", api_secret="s", passphrase="p")
        )
    )

    result = asyncio.run(service.sync(1))
    # 3 fills nhưng 1 cái (ZZZUNKNOWN) không map được coin → chỉ import 2
    assert result.total_fills == 3
    assert result.imported == 2

    txs = db.query(Transaction).filter_by(user_id=1).all()
    assert len(txs) == 2
    assert {t.type for t in txs} == {"buy", "sell"}

    conn = db.query(OKXConnection).filter_by(user_id=1).first()
    assert conn.last_synced_at is not None


def test_service_sync_twice_does_not_duplicate(db, monkeypatch):
    monkeypatch.setattr("app.services.okx_service.OKXAdapter", FakeOKXAdapter)
    FakeOKXAdapter.fail_balance = False
    service = OKXService(db, FakeMarketService(db))
    asyncio.run(
        service.connect(
            1, OKXConnectRequest(api_key="k", api_secret="s", passphrase="p")
        )
    )

    first = asyncio.run(service.sync(1))
    second = asyncio.run(service.sync(1))

    assert first.imported == 2
    assert second.imported == 0  # lần 2: cả 2 fill đã sync trước đó → không tạo thêm
    assert db.query(Transaction).filter_by(user_id=1).count() == 2
    assert db.query(OKXSyncedFill).filter_by(user_id=1).count() == 2


def test_service_sync_scoped_per_user(db, monkeypatch):
    """User 2 không thấy/đụng gì tới connection hay transaction của user 1."""
    monkeypatch.setattr("app.services.okx_service.OKXAdapter", FakeOKXAdapter)
    FakeOKXAdapter.fail_balance = False
    service = OKXService(db, FakeMarketService(db))
    asyncio.run(
        service.connect(
            1, OKXConnectRequest(api_key="k", api_secret="s", passphrase="p")
        )
    )
    assert service.get_status(2).is_connected is False
    with pytest.raises(OKXNotConnectedError):
        asyncio.run(service.sync(2))


# ──────────────────────────── Routes ────────────────────────────
def _build_app(db, user=None):
    app = FastAPI()
    static_dir = Path(wallet_module.__file__).resolve().parent.parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(wallet_module.router)
    app.dependency_overrides[get_db] = lambda: db

    def _override_okx_service():
        return OKXService(db, FakeMarketService(db))

    app.dependency_overrides[wallet_module.get_okx_service] = _override_okx_service
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_route_wallet_requires_auth(db):
    app = _build_app(db)
    res = TestClient(app).get("/wallet", follow_redirects=False)
    assert res.status_code == 401


def test_route_wallet_page_renders_connect_form(db):
    user = db.get(User, 1)
    app = _build_app(db, user=user)
    res = TestClient(app).get("/wallet")
    assert res.status_code == 200
    assert "API Key" in res.text


def test_route_connect_then_page_shows_connected(db, monkeypatch):
    monkeypatch.setattr("app.services.okx_service.OKXAdapter", FakeOKXAdapter)
    FakeOKXAdapter.fail_balance = False
    user = db.get(User, 1)
    app = _build_app(db, user=user)
    client = TestClient(app)

    res = client.post(
        "/wallet/connect",
        data={"api_key": "k", "api_secret": "s", "passphrase": "p"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/wallet"

    page = client.get("/wallet")
    assert "Đã kết nối" in page.text


def test_route_connect_failure_redirects_with_error(db, monkeypatch):
    monkeypatch.setattr("app.services.okx_service.OKXAdapter", FakeOKXAdapter)
    FakeOKXAdapter.fail_balance = True
    user = db.get(User, 1)
    app = _build_app(db, user=user)
    res = TestClient(app).post(
        "/wallet/connect",
        data={"api_key": "k", "api_secret": "s", "passphrase": "p"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "error=connect" in res.headers["location"]
    FakeOKXAdapter.fail_balance = False


def test_route_sync_without_connection_redirects_with_error(db):
    user = db.get(User, 1)
    app = _build_app(db, user=user)
    res = TestClient(app).post("/wallet/sync", follow_redirects=False)
    assert res.status_code == 303
    assert "error=not_connected" in res.headers["location"]


def test_route_disconnect(db, monkeypatch):
    monkeypatch.setattr("app.services.okx_service.OKXAdapter", FakeOKXAdapter)
    FakeOKXAdapter.fail_balance = False
    user = db.get(User, 1)
    app = _build_app(db, user=user)
    client = TestClient(app)
    client.post(
        "/wallet/connect", data={"api_key": "k", "api_secret": "s", "passphrase": "p"}
    )
    res = client.post("/wallet/disconnect", follow_redirects=False)
    assert res.status_code == 303
    page = client.get("/wallet")
    assert "API Key" in page.text  # quay lại form connect vì đã disconnect


def test_wallet_status_response_never_exposes_credentials(db, monkeypatch):
    """Đảm bảo response JSON/HTML của trang wallet không rò rỉ key/secret dưới bất kỳ dạng nào."""
    monkeypatch.setattr("app.services.okx_service.OKXAdapter", FakeOKXAdapter)
    FakeOKXAdapter.fail_balance = False
    user = db.get(User, 1)
    app = _build_app(db, user=user)
    client = TestClient(app)
    client.post(
        "/wallet/connect",
        data={"api_key": "super-secret-key-xyz", "api_secret": "s", "passphrase": "p"},
    )
    page = client.get("/wallet")
    assert "super-secret-key-xyz" not in page.text
    conn = db.query(OKXConnection).filter_by(user_id=1).first()
    assert "super-secret-key-xyz" not in json.dumps(
        {"a": conn.api_key_encrypted, "b": conn.api_secret_encrypted}
    )
