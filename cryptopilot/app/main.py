"""Điểm khởi tạo ứng dụng CryptoPilot.

- Khởi tạo FastAPI, mount static + Jinja2 templates
- Tạo bảng DB lúc startup (lifespan)
- Mount router auth; route /portfolio được bảo vệ (demo Phase 1)
- Handler 401 → redirect /login (cho auth dạng cookie/server-rendered)
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import auth, deps
from app.core.database import Base, engine, get_db
from app.models.user import User

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import models  # noqa: F401  — đăng ký models trước create_all

    Base.metadata.create_all(bind=engine)

    # TODO (Phase 5): start APScheduler ở đây
    yield
    # TODO (Phase 5): scheduler.shutdown()


app = FastAPI(title="CryptoPilot", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth.router)


@app.exception_handler(StarletteHTTPException)
async def auth_redirect_handler(request: Request, exc: StarletteHTTPException):
    """Route được bảo vệ ném 401 → đưa user về trang đăng nhập."""
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return await http_exception_handler(request, exc)


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    user = deps.get_current_user_optional(request, db)
    return templates.TemplateResponse(request, "index.html", {"user": user})


@app.get("/health")
def health():
    return {"status": "ok", "app": "CryptoPilot"}


# Demo Phase 1: route bảo vệ — chứng minh auth hoạt động end-to-end.
# TODO (Phase 3): chuyển sang app/api/portfolio.py với dashboard danh mục thật.
@app.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request, user: User = Depends(deps.get_current_user)):
    return templates.TemplateResponse(
        request, "portfolio/dashboard.html", {"user": user}
    )
