"""Tests Phase 5 — Alerts & Notifications.

- AlertService: CRUD scope theo user, evaluate (above/below biên), one-shot trigger
- NotificationService: create / unread_count / mark_read / mark_all_read, scope theo user
- Route: /alerts cần auth; tạo alert; /notifications/unread-count trả count đúng
"""

from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from app.api import alerts as alerts_module
from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.models.user import User
from app.schemas.alert import AlertCreate
from app.services.alert_service import AlertService
from app.services.notification_service import NotificationService


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


def _alert(coingecko_id="bitcoin", condition="above", threshold="65000", symbol="btc"):
    return AlertCreate(
        coingecko_id=coingecko_id,
        symbol=symbol,
        name=coingecko_id,
        condition=condition,  # type: ignore[arg-type]
        threshold_price=Decimal(threshold),
    )


# ────────────────────────────── AlertService ──────────────────────────────
def test_create_and_list_alert(db):
    svc = AlertService(db)
    svc.create_alert(1, _alert())
    alerts = svc.list_alerts(1)
    assert len(alerts) == 1
    assert alerts[0].coin.coingecko_id == "bitcoin"
    assert alerts[0].is_active is True


def test_alert_scope_per_user(db):
    svc = AlertService(db)
    a = svc.create_alert(1, _alert())
    # user 2 không xoá được alert của user 1
    assert svc.delete_alert(2, a.id) is False
    assert svc.delete_alert(1, a.id) is True
    assert svc.list_alerts(1) == []


def test_evaluate_above_below_boundary():
    # above: chạm khi price >= threshold
    assert AlertService.evaluate("above", Decimal("100"), 100.0) is True
    assert AlertService.evaluate("above", Decimal("100"), 99.99) is False
    # below: chạm khi price <= threshold
    assert AlertService.evaluate("below", Decimal("100"), 100.0) is True
    assert AlertService.evaluate("below", Decimal("100"), 100.01) is False


def test_trigger_is_one_shot(db):
    svc = AlertService(db)
    a = svc.create_alert(1, _alert())
    svc.trigger(a)
    assert a.is_active is False
    assert a.triggered_at is not None
    # không còn trong active alerts
    assert svc.get_active_alerts() == []


# ────────────────────────────── NotificationService ──────────────────────────────
def test_notification_create_and_unread(db):
    svc = NotificationService(db)
    svc.create(1, "price_alert", "BTC chạm 65000$", title="BTC")
    svc.create(1, "agent_insight", "Danh mục tập trung")
    assert svc.unread_count(1) == 2
    assert len(svc.list_for_user(1)) == 2


def test_notification_mark_read_scope(db):
    svc = NotificationService(db)
    n = svc.create(1, "price_alert", "msg")
    # user 2 không mark được noti của user 1
    assert svc.mark_read(2, n.id) is False
    assert svc.unread_count(1) == 1
    assert svc.mark_read(1, n.id) is True
    assert svc.unread_count(1) == 0


def test_notification_mark_all_read(db):
    svc = NotificationService(db)
    svc.create(1, "price_alert", "a")
    svc.create(1, "agent_insight", "b")
    svc.create(2, "price_alert", "c")  # của user khác — không bị đụng
    assert svc.mark_all_read(1) == 2
    assert svc.unread_count(1) == 0
    assert svc.unread_count(2) == 1


# ────────────────────────────── Routes ──────────────────────────────
def _build_app(db, user=None):
    app = FastAPI()
    static_dir = Path(alerts_module.__file__).resolve().parent.parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(alerts_module.router)
    app.dependency_overrides[get_db] = lambda: db
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_route_alerts_requires_auth(db):
    app = _build_app(db)
    res = TestClient(app).get("/alerts", follow_redirects=False)
    assert res.status_code == 401


def test_route_create_alert(db):
    user = db.get(User, 1)
    app = _build_app(db, user=user)
    res = TestClient(app).post(
        "/alerts",
        data={
            "coingecko_id": "ethereum",
            "symbol": "eth",
            "name": "Ethereum",
            "condition": "below",
            "threshold_price": "1500",
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert len(AlertService(db).list_alerts(1)) == 1


def test_route_unread_count(db):
    user = db.get(User, 1)
    NotificationService(db).create(1, "price_alert", "msg")
    app = _build_app(db, user=user)
    res = TestClient(app).get("/notifications/unread-count")
    assert res.status_code == 200
    assert res.json()["count"] == 1


def test_route_alerts_page_renders_search_box(db):
    user = db.get(User, 1)
    app = _build_app(db, user=user)
    res = TestClient(app).get("/alerts")
    assert res.status_code == 200
    # ô search coin (chống nhập sai id) phải có mặt
    assert "alert-coin-search" in res.text
    assert "/market/api/search" in res.text


def test_route_notifications_page_renders(db):
    user = db.get(User, 1)
    NotificationService(db).create(1, "agent_insight", "Danh mục tập trung")
    app = _build_app(db, user=user)
    res = TestClient(app).get("/notifications")
    assert res.status_code == 200
    assert "Danh mục tập trung" in res.text
    # script auto-refresh (poll unread-count) phải có mặt
    assert "/notifications/unread-count" in res.text
