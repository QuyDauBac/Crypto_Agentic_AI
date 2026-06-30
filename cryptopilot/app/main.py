"""Điểm khởi tạo ứng dụng CryptoPilot.

- Khởi tạo FastAPI, mount static + Jinja2 templates
- Tạo bảng DB lúc startup (lifespan)
- Mount các router: auth, market, portfolio
- Handler 401 → redirect /login (cho auth dạng cookie/server-rendered)
"""
from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.services.market_service import MarketService
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, agent, alerts, auth, deps, market, portfolio
from app.core.database import Base, SessionLocal, engine, get_db
from app.jobs.scheduler import shutdown_scheduler, start_scheduler

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
