"""Test auth — register, login, route được bảo vệ. DB in-memory cô lập."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app import models  # noqa: F401  — đăng ký models cho create_all

# Engine in-memory dùng chung cho mọi connection trong test
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


@pytest.fixture
def client():
    # follow_redirects=False để kiểm tra đúng redirect 303
    return TestClient(app, follow_redirects=False)


def test_register_sets_cookie_and_redirects(client):
    res = client.post(
        "/register",
        data={"email": "a@example.com", "password": "secret123", "display_name": "An"},
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/portfolio"
    assert "access_token" in res.cookies


def test_protected_requires_login(client):
    res = client.get("/portfolio")
    assert res.status_code == 303
    assert res.headers["location"] == "/login"


def test_login_then_access_protected(client):
    client.post("/register", data={"email": "b@example.com", "password": "secret123"})
    # client mới (không cookie) → login lại
    fresh = TestClient(app, follow_redirects=False)
    res = fresh.post("/login", data={"email": "b@example.com", "password": "secret123"})
    assert res.status_code == 303 and res.headers["location"] == "/portfolio"

    fresh2 = TestClient(app, follow_redirects=True)
    fresh2.post("/login", data={"email": "b@example.com", "password": "secret123"})
    page = fresh2.get("/portfolio")
    assert page.status_code == 200
    assert "b@example.com" in page.text


def test_login_wrong_password(client):
    client.post("/register", data={"email": "c@example.com", "password": "secret123"})
    res = client.post("/login", data={"email": "c@example.com", "password": "WRONG"})
    assert res.status_code == 401
    assert "access_token" not in res.cookies


def test_duplicate_email_rejected(client):
    client.post("/register", data={"email": "d@example.com", "password": "secret123"})
    res = client.post(
        "/register", data={"email": "d@example.com", "password": "secret123"}
    )
    assert res.status_code == 400
    assert "đã được đăng ký" in res.text
