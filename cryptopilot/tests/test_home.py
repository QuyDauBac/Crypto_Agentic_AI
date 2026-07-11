"""Test Phase 7 — Home Hub.

- Guest (chưa đăng nhập) → vẫn thấy landing page marketing (index.html)
- User đã đăng nhập → thấy home hub (home.html) với số liệu thật (rỗng nếu chưa
  có giao dịch nào) thay vì placeholder cũ.

DB in-memory, cô lập — không đụng DB thật. Portfolio rỗng nên PortfolioService
không gọi mạng lấy giá coin (coin_ids rỗng); phần benchmark BTC gọi get_history
qua MarketService vốn đã tự bắt lỗi mạng (trả về [] nếu lỗi) nên test chạy được
cả khi không có internet.
"""

import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  — đăng ký models cho create_all
from app.core.database import Base, get_db
from app.main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


_email_seq = itertools.count(1)


@pytest.fixture
def guest_client():
    return TestClient(app, follow_redirects=True)


@pytest.fixture
def user_client():
    client = TestClient(app, follow_redirects=True)
    email = f"hub{next(_email_seq)}@example.com"
    res = client.post(
        "/register",
        data={"email": email, "password": "secret123", "display_name": "Obi"},
    )
    assert "access_token" in res.cookies or res.history, "register phải đăng nhập luôn"
    return client


def test_guest_sees_landing_page(guest_client):
    res = guest_client.get("/")
    assert res.status_code == 200
    assert "Create your account" in res.text or "CryptoPilot" in res.text


def test_logged_in_user_sees_home_hub(user_client):
    res = user_client.get("/")
    assert res.status_code == 200
    assert "Chào" in res.text
    assert "Truy cập nhanh" in res.text


def test_home_hub_empty_state_prompts_first_transaction(user_client):
    res = user_client.get("/")
    assert res.status_code == 200
    assert "Thêm giao dịch đầu tiên" in res.text


def test_home_hub_shows_zero_unread_notifications(user_client):
    res = user_client.get("/")
    assert res.status_code == 200
    assert "Chưa có thông báo nào" in res.text
