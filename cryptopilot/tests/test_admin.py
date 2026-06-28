"""Tests Phase 6 — Admin, Settings.

- get_current_admin: non-admin → 403, admin → OK
- AdminService: stats đếm đúng; toggle active/admin; chốt không tự khóa/thu quyền mình
- SettingsService: get/set/get_bool/get_float + default khi thiếu row
- run_proactive_agent(enabled=False) → bỏ qua
- Route admin render (dashboard/users/settings) cho admin; chặn non-admin
"""

import asyncio
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from app.api import admin as admin_module
from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.jobs.proactive_agent import run_proactive_agent
from app.models.user import User
from app.schemas.alert import AlertCreate
from app.services.admin_service import AdminService
from app.services.alert_service import AlertService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, email="admin@test.com", hashed_password="x", is_admin=True))
    session.add(User(id=2, email="user@test.com", hashed_password="x"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


# ────────────────────────────── SettingsService ──────────────────────────────
def test_settings_default_when_missing(db):
    svc = SettingsService(db)
    # proactive.enabled mặc định "true" trong DEFAULTS
    assert svc.get_bool("proactive.enabled") is True
    # key không có default → None
    assert svc.get("khong.ton.tai") is None


def test_settings_set_and_get(db):
    svc = SettingsService(db)
    svc.set("alert.default_threshold_usd", "65000")
    assert svc.get("alert.default_threshold_usd") == "65000"
    assert svc.get_float("alert.default_threshold_usd") == pytest.approx(65000.0)
    svc.set("proactive.enabled", "false")
    assert svc.get_bool("proactive.enabled") is False


def test_settings_all_for_admin(db):
    rows = SettingsService(db).all_for_admin()
    keys = {r["key"] for r in rows}
    assert "alert.default_threshold_usd" in keys
    assert "proactive.enabled" in keys


# ────────────────────────────── AdminService ──────────────────────────────
def test_admin_stats(db):
    AlertService(db).create_alert(
        2,
        AlertCreate(
            coingecko_id="bitcoin",
            symbol="btc",
            name="Bitcoin",
            condition="above",  # type: ignore[arg-type]
            threshold_price=Decimal("60000"),
        ),
    )
    NotificationService(db).create(2, "price_alert", "msg")
    stats = AdminService(db).stats()
    assert stats["total_users"] == 2
    assert stats["active_users"] == 2
    assert stats["total_alerts"] == 1
    assert stats["active_alerts"] == 1
    assert stats["total_notifications"] == 1
    assert stats["total_coins"] == 1


def test_admin_toggle_active_and_admin(db):
    svc = AdminService(db)
    admin = db.get(User, 1)
    # khóa user 2
    assert svc.toggle_active(2, admin) is True
    assert db.get(User, 2).is_active is False
    # cấp admin cho user 2
    assert svc.toggle_admin(2, admin) is True
    assert db.get(User, 2).is_admin is True


def test_admin_cannot_toggle_self(db):
    svc = AdminService(db)
    admin = db.get(User, 1)
    # không tự khóa / tự thu quyền mình
    assert svc.toggle_active(1, admin) is False
    assert svc.toggle_admin(1, admin) is False
    assert db.get(User, 1).is_active is True
    assert db.get(User, 1).is_admin is True


# ────────────────────────────── proactive gate ──────────────────────────────
class FakeProactive:
    def __init__(self, users, insight):
        self._users = users
        self._insight = insight

    def users_with_holdings(self):
        return self._users

    async def insight_for_user(self, user):
        return self._insight


def test_proactive_disabled_skips(db):
    user = db.get(User, 1)
    n = asyncio.run(
        run_proactive_agent(
            FakeProactive([user], "x"), NotificationService(db), enabled=False
        )
    )
    assert n == 0
    assert NotificationService(db).list_for_user(1) == []


# ────────────────────────────── Routes ──────────────────────────────
def _build_app(db, user):
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    app = FastAPI()
    static_dir = Path(admin_module.__file__).resolve().parent.parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(admin_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_admin_routes_blocked_for_non_admin(db):
    non_admin = db.get(User, 2)
    app = _build_app(db, non_admin)
    c = TestClient(app)
    assert c.get("/admin", follow_redirects=False).status_code == 403
    assert c.get("/admin/users", follow_redirects=False).status_code == 403
    assert c.get("/admin/settings", follow_redirects=False).status_code == 403


def test_admin_dashboard_renders_for_admin(db):
    admin = db.get(User, 1)
    app = _build_app(db, admin)
    res = TestClient(app).get("/admin")
    assert res.status_code == 200
    assert "Bảng quản trị" in res.text


def test_admin_users_page_and_toggle(db):
    admin = db.get(User, 1)
    app = _build_app(db, admin)
    c = TestClient(app)
    assert c.get("/admin/users").status_code == 200
    res = c.post("/admin/users/2/toggle-active", follow_redirects=False)
    assert res.status_code == 303
    assert db.get(User, 2).is_active is False


def test_admin_settings_save(db):
    admin = db.get(User, 1)
    app = _build_app(db, admin)
    c = TestClient(app)
    res = c.post(
        "/admin/settings",
        data={"alert.default_threshold_usd": "12345"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert SettingsService(db).get("alert.default_threshold_usd") == "12345"
    # checkbox proactive.enabled không gửi → set thành "false"
    assert SettingsService(db).get_bool("proactive.enabled") is False
