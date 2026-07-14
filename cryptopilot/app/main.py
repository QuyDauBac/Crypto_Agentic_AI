"""Điểm khởi tạo ứng dụng CryptoPilot.

- Khởi tạo FastAPI, mount static + Jinja2 templates
- Tạo bảng DB lúc startup (lifespan)
- Mount các router: auth, market, portfolio
- Handler 401 → redirect /login (cho auth dạng cookie/server-rendered)
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.services.market_service import MarketService
from app.services.notification_service import NotificationService
from app.services.portfolio_service import PortfolioService

from fastapi import Depends, FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, agent, alerts, auth, deps, market, portfolio, wallet
from app.core.database import Base, SessionLocal, engine, get_db
from app.jobs.scheduler import shutdown_scheduler, start_scheduler

# Chỉ áp dụng khi chạy app thật (uvicorn/python -m), KHÔNG khi pytest import module này
# (test_smoke.py, test_auth.py, test_home.py đều `from app.main import app`) — tránh đổi
# hành vi capture log/stdout của pytest.
if "pytest" not in sys.modules:
    # Không có basicConfig() thì mọi logger.info/warning trong app (jobs, adapters...)
    # rơi vào "root logger không handler" → im lặng, kể cả khi có lỗi thật.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Console Windows mặc định cp1252 — log/print có dấu tiếng Việt hoặc emoji (⚠️...)
    # làm crash tiến trình ngay tại lệnh print/log, không phải lỗi logic bên trong.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        # .reconfigure() chỉ có ở Python 3.7+ trên TextIOWrapper thật — môi trường nào
        # không có (Python cũ, stdout đã bị thay bằng object khác) thì bỏ qua, không chặn app.
        pass

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import models  # noqa: F401  — đăng ký models trước create_all

    Base.metadata.create_all(bind=engine)

    start_scheduler()  # Phase 5: price_check / proactive_agent / refresh_coins
    yield
    shutdown_scheduler()


app = FastAPI(title="CryptoPilot", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth.router)
app.include_router(market.router)
app.include_router(portfolio.router)
app.include_router(agent.router)
app.include_router(alerts.router)
app.include_router(admin.router)
app.include_router(wallet.router)


@app.exception_handler(StarletteHTTPException)
async def auth_redirect_handler(request: Request, exc: StarletteHTTPException):
    """Map lỗi HTTP sang trang thân thiện cho UI server-rendered."""
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if exc.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND):
        db = SessionLocal()
        try:
            user = deps.get_current_user_optional(request, db)
            return templates.TemplateResponse(
                request,
                "error.html",
                {
                    "user": user,
                    "code": exc.status_code,
                    "message": (
                        "Bạn không có quyền truy cập trang này."
                        if exc.status_code == status.HTTP_403_FORBIDDEN
                        else "Không tìm thấy trang bạn yêu cầu."
                    ),
                },
                status_code=exc.status_code,
            )
        finally:
            db.close()
    return await http_exception_handler(request, exc)


# Các coin hiển thị trên ticker Dynamic Island (symbol → hiển thị)
_TICKER_SYMBOLS = ["btc", "eth", "sol", "bnb", "xrp", "ada", "doge", "avax"]


def _format_price(value: float) -> str:
    """Format giá USD cho ticker: $67,240 hoặc $0.62."""
    if value >= 1:
        return f"${value:,.0f}" if value >= 100 else f"${value:,.2f}"
    return f"${value:.2f}"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    user = deps.get_current_user_optional(request, db)

    # User đã đăng nhập → home hub với số liệu thật (Phase 7: Home Hub).
    # Khách chưa đăng nhập → giữ nguyên landing page marketing bên dưới.
    if user is not None:
        market = MarketService(db=db, adapter=CoinGeckoAdapter())
        portfolio_service = PortfolioService(db=db, market_service=market)
        notif_service = NotificationService(db=db)

        dashboard = await portfolio_service.get_dashboard(user.id)
        recent_notifications = notif_service.list_for_user(user.id, limit=5)
        unread_count = notif_service.unread_count(user.id)

        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "user": user,
                "d": dashboard,
                "recent_notifications": recent_notifications,
                "unread_count": unread_count,
            },
        )

    # Lấy giá ticker cho Dynamic Island (có cache + fallback sẵn trong service)
    market_prices: list[dict] = []
    try:
        service = MarketService(db=db, adapter=CoinGeckoAdapter())
        # map symbol → coingecko_id (bỏ symbol nào DB chưa có)
        sym_to_id = {}
        for sym in _TICKER_SYMBOLS:
            cid = service.resolve_symbol(sym)
            if cid:
                sym_to_id[sym] = cid

        if sym_to_id:
            snapshot = await service.get_prices(list(sym_to_id.values()))
            # snapshot.prices: dict[coingecko_id, float]
            # cần % thay đổi — service hiện chỉ trả giá, nên tạm để 0%
            # (nâng cấp sau: dùng get_history hoặc CoinGecko market endpoint có 24h change)
            for sym, cid in sym_to_id.items():
                price = snapshot.prices.get(cid)
                if price is not None:
                    market_prices.append(
                        {
                            "sym": sym.upper(),
                            "price": _format_price(price),
                            "chg": "+0.0%",  # placeholder — xem ghi chú bên dưới
                            "up": True,
                        }
                    )
    except Exception:
        # Ticker lỗi không được làm sập trang chủ — template có fallback JS riêng
        market_prices = []

    return templates.TemplateResponse(
        request,
        "index.html",
        {"user": user, "market_prices": market_prices},
    )


@app.get("/health")
def health():
    return {"status": "ok", "app": "CryptoPilot"}
