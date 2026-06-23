"""Tầng database — engine, SessionLocal, Base, dependency get_db().

Quyết định nền: DB truy cập ĐỒNG BỘ (sync SQLAlchemy). Async chỉ áp ở external API.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.core.config import settings

# check_same_thread=False: cần cho SQLite khi FastAPI chạy route sync trong threadpool
connect_args = (
    {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class cho mọi model — import Base này trong app/models/*.py
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: mở session cho mỗi request, đóng khi xong."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
