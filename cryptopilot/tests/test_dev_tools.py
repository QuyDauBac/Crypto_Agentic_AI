"""Tests Phase 9 — app/dev_tools/seed_portfolio_history.py (script demo/test cục bộ).

- Không bao giờ ghi đè snapshot thật đã có
- Sinh đúng số ngày, giá trị luôn dương
- Sau khi seed đủ ngày, dashboard mở khóa đúng khung (test tích hợp qua unlocked flag)
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.dev_tools.seed_portfolio_history import _seed_core
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.user import User
from app.services.portfolio_service import PortfolioService


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


class _NoopMarket:
    async def get_prices(
        self, coingecko_ids
    ):  # pragma: no cover - không gọi trong test này
        raise AssertionError("_seed_core không được gọi mạng")


def _portfolio(db):
    return PortfolioService(db=db, market_service=_NoopMarket())


def test_seed_core_fills_exact_day_count(db):
    portfolio = _portfolio(db)
    today = date(2026, 6, 30)
    seeded, skipped = _seed_core(db, portfolio, 1, 10, 1000.0, 800.0, today=today)
    assert seeded == 10
    assert skipped == 0
    rows = db.query(PortfolioSnapshot).filter_by(user_id=1).all()
    assert len(rows) == 10
    dates = {r.snapshot_date for r in rows}
    assert dates == {today - timedelta(days=i) for i in range(10)}


def test_seed_core_never_overwrites_real_snapshot(db):
    today = date(2026, 6, 30)
    real_date = today - timedelta(days=3)
    db.add(
        PortfolioSnapshot(
            user_id=1,
            snapshot_date=real_date,
            total_value=Decimal("42.00"),
            total_cost=Decimal("10.00"),
        )
    )
    db.commit()

    portfolio = _portfolio(db)
    seeded, skipped = _seed_core(db, portfolio, 1, 10, 1000.0, 800.0, today=today)
    assert skipped == 1
    assert seeded == 9

    row = (
        db.query(PortfolioSnapshot).filter_by(user_id=1, snapshot_date=real_date).one()
    )
    assert row.total_value == Decimal("42.00")  # không bị ghi đè


def test_seed_core_values_stay_positive(db):
    portfolio = _portfolio(db)
    today = date(2026, 6, 30)
    # anchor rất nhỏ + seed nhiều ngày để dễ chạm floor nếu logic clamp sai
    _seed_core(db, portfolio, 1, 60, 2.0, 1.0, today=today)
    rows = db.query(PortfolioSnapshot).filter_by(user_id=1).all()
    assert all(r.total_value > 0 for r in rows)


def test_seed_core_reruns_idempotent_on_seeded_days(db):
    """Chạy seed 2 lần với cùng khoảng ngày: lần 2 không tạo thêm dòng (đã seed → coi
    như "đã có dữ liệu", save_snapshot upsert nên không lỗi/trùng)."""
    portfolio = _portfolio(db)
    today = date(2026, 6, 30)
    _seed_core(db, portfolio, 1, 5, 1000.0, 800.0, today=today)
    seeded2, skipped2 = _seed_core(db, portfolio, 1, 5, 1000.0, 800.0, today=today)
    assert seeded2 == 0
    assert skipped2 == 5
    assert db.query(PortfolioSnapshot).filter_by(user_id=1).count() == 5
