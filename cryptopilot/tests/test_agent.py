"""Tests Phase 4 — AI Agent.

Mock Gemini hoàn toàn (FakeGeminiClient) — KHÔNG gọi mạng / SDK thật. Bao gồm:
  - Dispatcher: map tool → service đúng, scope theo user, validate tham số, lỗi → {error}
  - Orchestrator: vòng ReAct nhiều bước (gọi tool → đọc kết quả → trả lời), MAX_STEPS,
    graceful khi chưa cấu hình key / khi client ném lỗi
  - Route /agent/chat: cần auth (401), chạy được khi override dep, persist đúng 2 message
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from app.agent import orchestrator as orch_mod
from app.agent import tools as tools_mod
from app.agent.gemini_client import AgentResponse, AgentToolCall
from app.agent.orchestrator import AgentOrchestrator
from app.agent.tools import ToolContext
from app.api import agent as agent_module
from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.models.message import Message
from app.models.user import User
from app.schemas.market import PricePoint, PriceSnapshot
from app.schemas.transaction import TransactionCreate
from app.services.market_service import _clear_price_cache
from app.services.portfolio_service import PortfolioService


# ──────────────────────────── Fakes & fixtures ────────────────────────────
class FakeMarket:
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


class FakeNews:
    def __init__(self, payload=None):
        self._payload = payload or {"news": [], "note": "trống"}

    async def get_filtered(self, user, limit=5, coingecko_ids=None):
        return self._payload


class FakeGeminiClient:
    """LLMClient giả — phát các AgentResponse đã 'kịch bản hoá' theo thứ tự."""

    def __init__(self, scripted=None, configured=True, raise_exc=False):
        self.scripted = list(scripted or [])
        self._configured = configured
        self.raise_exc = raise_exc
        self.calls = []

    @property
    def is_configured(self):
        return self._configured

    async def generate(self, *, system_instruction, turns, tool_specs):
        # lưu snapshot turns để assert vòng lặp có feed kết quả tool lại
        self.calls.append({"turns": list(turns), "tool_specs": tool_specs})
        if self.raise_exc:
            raise RuntimeError("gemini boom")
        if self.scripted:
            return self.scripted.pop(0)
        return AgentResponse(text="(hết kịch bản)")


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
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


def _tx(coingecko_id, type_, qty, price, symbol="", name=""):
    return TransactionCreate(
        coingecko_id=coingecko_id,
        symbol=symbol or coingecko_id[:3],
        name=name or coingecko_id,
        type=type_,
        quantity=Decimal(str(qty)),
        price=Decimal(str(price)),
        executed_at=datetime(2026, 1, 1),
    )


def _ctx(db, market=None, news=None):
    market = market or FakeMarket()
    portfolio = PortfolioService(db=db, market_service=market)
    return ToolContext(
        user=db.get(User, 1),
        portfolio_service=portfolio,
        market_service=market,
        news_service=news or FakeNews(),
    )


# ──────────────────────────── Dispatcher ────────────────────────────
def test_dispatch_portfolio_summary(db):
    market = FakeMarket(prices={"bitcoin": 300.0})
    ctx = _ctx(db, market)
    ctx.portfolio_service.add_transaction(1, _tx("bitcoin", "buy", 1, 100))

    res = asyncio.run(tools_mod.dispatch("get_portfolio_summary", {}, ctx))
    assert res["total_value_usd"] == pytest.approx(300.0)
    assert res["holdings"][0]["symbol"] == "BIT"  # symbol = coingecko_id[:3] trong _tx
    assert res["holdings"][0]["pnl_pct"] == pytest.approx(200.0)


def test_dispatch_allocation(db):
    market = FakeMarket(prices={"bitcoin": 300.0, "ethereum": 100.0})
    ctx = _ctx(db, market)
    ctx.portfolio_service.add_transaction(1, _tx("bitcoin", "buy", 1, 100))
    ctx.portfolio_service.add_transaction(1, _tx("ethereum", "buy", 1, 100))

    res = asyncio.run(tools_mod.dispatch("get_portfolio_allocation", {}, ctx))
    pct = {r["coingecko_id"]: r["percent"] for r in res["allocation"]}
    assert pct["bitcoin"] == pytest.approx(75.0)
    assert pct["ethereum"] == pytest.approx(25.0)
    # sắp xếp giảm dần → coin lớn nhất đứng đầu
    assert res["allocation"][0]["coingecko_id"] == "bitcoin"


def test_dispatch_coin_price_and_history(db):
    market = FakeMarket(
        prices={"bitcoin": 12345.0},
        history=[{"timestamp": 1, "price": 100.0}, {"timestamp": 2, "price": 130.0}],
    )
    ctx = _ctx(db, market)

    price = asyncio.run(
        tools_mod.dispatch("get_coin_price", {"coingecko_id": "bitcoin"}, ctx)
    )
    assert price["price_usd"] == pytest.approx(12345.0)

    hist = asyncio.run(
        tools_mod.dispatch(
            "get_coin_history", {"coingecko_id": "bitcoin", "days": 30}, ctx
        )
    )
    assert hist["change_pct"] == pytest.approx(30.0)
    assert hist["points_count"] == 2


def test_dispatch_validation_and_unknown(db):
    ctx = _ctx(db)
    assert "error" in asyncio.run(tools_mod.dispatch("get_coin_price", {}, ctx))
    assert "error" in asyncio.run(tools_mod.dispatch("nope", {}, ctx))


def test_dispatch_price_not_found(db):
    ctx = _ctx(db, FakeMarket(prices={}))  # không có giá
    res = asyncio.run(
        tools_mod.dispatch("get_coin_price", {"coingecko_id": "xrp"}, ctx)
    )
    assert "error" in res


# ──────────────────────────── Orchestrator: vòng ReAct ────────────────────────────
def test_orchestrator_react_multi_step(db):
    market = FakeMarket(prices={"bitcoin": 300.0})
    ctx = _ctx(db, market)
    ctx.portfolio_service.add_transaction(1, _tx("bitcoin", "buy", 1, 100))

    # Kịch bản: vòng 1 xin allocation → vòng 2 (đọc kết quả) trả lời text
    client = FakeGeminiClient(
        scripted=[
            AgentResponse(tool_calls=[AgentToolCall("get_portfolio_allocation", {})]),
            AgentResponse(text="Danh mục của bạn tập trung 100% vào BTC."),
        ]
    )
    orch = AgentOrchestrator(client=client, ctx=ctx)
    result = asyncio.run(orch.run(db.get(User, 1), "Tôi có rủi ro không?", []))

    assert "BTC" in result.reply
    assert result.degraded is False
    assert [s.name for s in result.tool_steps] == ["get_portfolio_allocation"]
    assert result.tool_steps[0].ok is True
    # vòng 2 phải thấy 1 turn role=tool (kết quả được feed lại cho Gemini đọc)
    second_turns = client.calls[1]["turns"]
    assert any(t.get("role") == "tool" for t in second_turns)


def test_orchestrator_no_tool_direct_answer(db):
    client = FakeGeminiClient(scripted=[AgentResponse(text="Chào bạn!")])
    orch = AgentOrchestrator(client=client, ctx=_ctx(db))
    result = asyncio.run(orch.run(db.get(User, 1), "hi", []))
    assert result.reply == "Chào bạn!"
    assert result.tool_steps == []


def test_orchestrator_not_configured(db):
    client = FakeGeminiClient(configured=False)
    orch = AgentOrchestrator(client=client, ctx=_ctx(db))
    result = asyncio.run(orch.run(db.get(User, 1), "hi", []))
    assert result.degraded is True
    assert "GEMINI_API_KEY" in result.reply
    assert client.calls == []  # không gọi Gemini khi chưa cấu hình


def test_orchestrator_graceful_on_exception(db):
    client = FakeGeminiClient(raise_exc=True)
    orch = AgentOrchestrator(client=client, ctx=_ctx(db))
    result = asyncio.run(orch.run(db.get(User, 1), "hi", []))
    assert result.degraded is True
    assert "sự cố" in result.reply or "lỗi" in result.reply.lower()


def test_orchestrator_respects_max_steps(db):
    # Client luôn xin gọi tool → phải bị cắt ở MAX_STEPS, không lặp vô hạn
    forever = [
        AgentResponse(tool_calls=[AgentToolCall("get_portfolio_summary", {})])
        for _ in range(orch_mod.MAX_STEPS + 3)
    ]
    client = FakeGeminiClient(scripted=forever)
    orch = AgentOrchestrator(client=client, ctx=_ctx(db))
    result = asyncio.run(orch.run(db.get(User, 1), "loop?", []))
    # MAX_STEPS vòng có tool + 1 lần generate cuối (ép tổng hợp, tool_specs rỗng)
    assert len(client.calls) == orch_mod.MAX_STEPS + 1
    assert client.calls[-1]["tool_specs"] == []
    assert result.degraded is False


# ──────────────────────────── Route /agent/chat ────────────────────────────
def _build_app(db, client=None, user=None, market=None, news=None):
    app = FastAPI()
    static_dir = Path(agent_module.__file__).resolve().parent.parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(agent_module.router)
    app.dependency_overrides[get_db] = lambda: db

    market = market or FakeMarket(prices={"bitcoin": 300.0})
    portfolio = PortfolioService(db=db, market_service=market)

    def _deps():
        return agent_module.AgentDeps(
            db=db,
            portfolio=portfolio,
            market=market,
            news=news or FakeNews(),
            client=client or FakeGeminiClient(scripted=[AgentResponse(text="ok")]),
        )

    app.dependency_overrides[agent_module.get_agent_deps] = _deps
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_route_chat_requires_auth(db):
    app = _build_app(db)
    res = TestClient(app).post(
        "/agent/chat", json={"message": "hi"}, follow_redirects=False
    )
    assert res.status_code == 401


def test_route_chat_runs_and_persists(db):
    user = db.get(User, 1)
    client = FakeGeminiClient(
        scripted=[AgentResponse(text="Xin chào, đây là phân tích.")]
    )
    app = _build_app(db, client=client, user=user)
    res = TestClient(app).post("/agent/chat", json={"message": "danh mục tôi sao rồi?"})
    assert res.status_code == 200
    body = res.json()
    assert body["reply"] == "Xin chào, đây là phân tích."
    assert body["degraded"] is False
    conv_id = body["conversation_id"]

    # persist đúng 2 message (user + assistant), KHÔNG lưu tool call
    msgs = db.query(Message).filter_by(conversation_id=conv_id).all()
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "danh mục tôi sao rồi?"


def test_route_chat_continues_conversation(db):
    user = db.get(User, 1)
    app = _build_app(
        db,
        client=FakeGeminiClient(
            scripted=[AgentResponse(text="1"), AgentResponse(text="2")]
        ),
        user=user,
    )
    c = TestClient(app)
    first = c.post("/agent/chat", json={"message": "lần 1"}).json()
    cid = first["conversation_id"]
    c.post("/agent/chat", json={"message": "lần 2", "conversation_id": cid})

    msgs = db.query(Message).filter_by(conversation_id=cid).all()
    assert len(msgs) == 4  # 2 lượt × (user+assistant) trong CÙNG conversation
