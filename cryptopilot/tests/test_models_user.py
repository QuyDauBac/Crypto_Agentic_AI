"""Test User model — chạy trên SQLite in-memory, không đụng DB thật."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.user import User


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_user_defaults_and_persist():
    with _session() as s:
        u = User(email="obi@example.com", hashed_password="fake-hash")
        s.add(u)
        s.commit()
        s.refresh(u)

        assert u.id is not None
        assert u.email == "obi@example.com"
        assert u.is_active is True  # default
        assert u.is_admin is False  # default
        assert u.display_name is None  # nullable
        assert u.created_at is not None  # server_default


def test_email_unique():
    import pytest
    from sqlalchemy.exc import IntegrityError

    with _session() as s:
        s.add(User(email="dup@example.com", hashed_password="h1"))
        s.commit()
        s.add(User(email="dup@example.com", hashed_password="h2"))
        with pytest.raises(IntegrityError):
            s.commit()
