"""Điểm khởi tạo ứng dụng CryptoPilot.

- Khởi tạo FastAPI, mount static + Jinja2 templates
- Tạo bảng DB lúc startup (lifespan)
- Chỗ để start/stop APScheduler ở các phase sau (jobs/)
- Route nền tạm: trang chủ + /health
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.database import Base, engine

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Import models để chúng được đăng ký với Base trước khi create_all.
    # (Hiện chưa có model nào — sẽ thêm ở bước tiếp theo: User, Coin, ...)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # TODO (Phase 5): start APScheduler ở đây
    #   from app.jobs.scheduler import start_scheduler
    #   scheduler = start_scheduler()
    yield
    # TODO (Phase 5): scheduler.shutdown()


app = FastAPI(title="CryptoPilot", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # Starlette API mới: request đứng đầu, rồi tên template, rồi context (optional)
    return templates.TemplateResponse(request, "index.html")


@app.get("/health")
def health():
    """Healthcheck đơn giản — xác nhận app chạy."""
    return {"status": "ok", "app": "CryptoPilot"}


# Các router theo feature sẽ include ở các phase sau:
#   from app.api import auth, portfolio, market, alerts, agent
#   app.include_router(auth.router)
