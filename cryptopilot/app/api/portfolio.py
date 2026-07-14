"""Router portfolio (Phase 3) — dashboard + CRUD transactions.

Mọi route yêu cầu đăng nhập (Depends(get_current_user)) và scope theo user.id — Agent/UI
không bao giờ thấy danh mục user khác.

Async/sync theo 04-architecture.md:
  - GET /portfolio (dashboard)  → async def  (await giá CoinGecko)
  - các route CRUD chỉ đụng DB   → def        (FastAPI chạy trong threadpool)
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.api.deps import get_current_user
from app.api.template_filters import register as register_template_filters
from app.core.database import get_db
from app.models.user import User
from app.schemas.market import PricePoint
from app.schemas.transaction import TransactionCreate
from app.services.market_service import MarketService
from app.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


register_template_filters(templates.env)


# Khung thời gian hiển thị trên biểu đồ "Hiệu suất vs Bitcoin". Khung chỉ unlocked=True
# khi đã có ĐỦ số ngày snapshot thật LIÊN TỤC (không đứt quãng) tương ứng — 7D cần >=7
# ngày liên tục, ..., 1Y cần >=365. Không dùng "có vài điểm nằm trong khung" (dễ mở khóa
# 1Y chỉ với 3 ngày dữ liệu dồn ở cuối, vẽ ra đường gần như phẳng suốt gần 1 năm).
_CHART_WINDOWS: dict[str, int] = {"7D": 7, "30D": 30, "90D": 90, "1Y": 365}


def _normalize_pct(values: list[float]) -> list[float]:
    """Chuẩn hoá 1 chuỗi giá trị thành % thay đổi so với điểm đầu tiên."""
    if not values or values[0] == 0:
        return [0.0 for _ in values]
    base = values[0]
    return [round((v - base) / base * 100, 2) for v in values]


def _ffill(values: list[float | None]) -> list[float]:
    """Forward-fill None (portfolio snapshot theo ngày và điểm giá BTC theo ngày
    thường không khớp mốc thời gian tuyệt đối) để 2 đường trên chart luôn liền mạch."""
    first_known = next((v for v in values if v is not None), 0.0)
    out: list[float] = []
    last = first_known
    for v in values:
        if v is not None:
            last = v
        out.append(last)
    return out


def _continuous_days(value_history: list[tuple[date, float]]) -> int:
    """Số ngày snapshot thật LIÊN TỤC (không đứt quãng), đếm lùi từ ngày gần nhất.

    Job portfolio_snapshot chạy 1 lần/ngày; nếu 1 ngày lỗi/bị skip (CoinGecko hỏng
    hoàn toàn hôm đó) thì chuỗi đứt tại đó — dữ liệu cũ hơn gap KHÔNG được tính vào
    "đã tích lũy", để không mở khóa khung dài hơn thực tế có.
    """
    if not value_history:
        return 0
    dates = sorted({d for d, _ in value_history}, reverse=True)
    streak = 1
    for i in range(1, len(dates)):
        if (dates[i - 1] - dates[i]).days == 1:
            streak += 1
        else:
            break
    return streak


def _build_chart_data(
    value_history: list[tuple[date, float]], btc_history: list[PricePoint]
) -> dict[str, dict]:
    """Đóng gói value_history (danh mục) + btc_history thành 4 khung 7D/30D/90D/1Y.

    Mỗi khung trả {unlocked, days_remaining, labels, portfolio, btc}. Khung
    unlocked=False không có dữ liệu chart (mảng rỗng) — template phân biệt rõ "chưa
    đủ dữ liệu" (unlocked=False) với trạng thái khác, không suy luận qua mảng rỗng.
    Khung unlocked=True: % thay đổi so với điểm đầu khung — "so sánh thô" (không cùng
    mốc thời gian tuyệt đối, chỉ so hình dạng đường xu hướng).
    """
    continuous_days = _continuous_days(value_history)
    btc_by_date = {
        datetime.fromtimestamp(p.timestamp / 1000, tz=timezone.utc).date(): p.price
        for p in btc_history
    }
    chart: dict[str, dict] = {}
    for label, days in _CHART_WINDOWS.items():
        unlocked = continuous_days >= days
        entry: dict = {
            "unlocked": unlocked,
            "days_remaining": max(0, days - continuous_days),
            "labels": [],
            "portfolio": [],
            "btc": [],
        }
        if unlocked:
            cutoff = date.today() - timedelta(days=days)
            window_portfolio = {d: v for d, v in value_history if d >= cutoff}
            window_btc = {d: p for d, p in btc_by_date.items() if d >= cutoff}
            dates = sorted(set(window_portfolio) | set(window_btc))
            entry["labels"] = [d.strftime("%d/%m") for d in dates]
            entry["portfolio"] = _normalize_pct(
                _ffill([window_portfolio.get(d) for d in dates])
            )
            entry["btc"] = _normalize_pct(_ffill([window_btc.get(d) for d in dates]))
        chart[label] = entry
    return chart


def get_portfolio_service(db: Session = Depends(get_db)) -> PortfolioService:
    market = MarketService(db=db, adapter=CoinGeckoAdapter())
    return PortfolioService(db=db, market_service=market)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    service: PortfolioService = Depends(get_portfolio_service),
) -> HTMLResponse:
    view = await service.get_dashboard(user.id)

    # Chỉ fetch lịch sử BTC tới độ dài khung lớn nhất đã unlocked — tránh gọi CoinGecko
    # 365 ngày khi portfolio mới có vài ngày dữ liệu liên tục.
    value_history = service.get_value_history(user.id, max(_CHART_WINDOWS.values()))
    continuous_days = _continuous_days(value_history)
    candidate_days = max(
        (days for days in _CHART_WINDOWS.values() if continuous_days >= days),
        default=0,
    )
    btc_history = (
        await service.market.get_history("bitcoin", candidate_days)
        if candidate_days
        else []
    )
    chart_data = _build_chart_data(value_history, btc_history)
    default_timeframe = next(
        (tf for tf in ("7D", "30D", "90D", "1Y") if chart_data[tf]["unlocked"]), None
    )

    return templates.TemplateResponse(
        request,
        "portfolio/dashboard.html",
        {
            "user": user,
            "d": view,
            "chart_data": chart_data,
            "default_timeframe": default_timeframe,
        },
    )


@router.get("/transactions", response_class=HTMLResponse)
def transactions_page(
    request: Request,
    edit: int | None = None,
    error: int | None = None,
    user: User = Depends(get_current_user),
    service: PortfolioService = Depends(get_portfolio_service),
) -> HTMLResponse:
    txs = service.list_transactions(user.id)
    editing = service.get_transaction(user.id, edit) if edit else None
    return templates.TemplateResponse(
        request,
        "portfolio/transactions.html",
        {"user": user, "txs": txs, "editing": editing, "error": error},
    )


def _parse_form(
    coingecko_id: str,
    symbol: str,
    name: str,
    type_: str,
    quantity: str,
    price: str,
    fee: str,
    note: str,
    executed_at: str,
) -> TransactionCreate:
    """Dựng TransactionCreate từ form; ném ValidationError/ValueError nếu dữ liệu sai."""
    try:
        qty = Decimal(quantity)
        prc = Decimal(price)
        fee_val = Decimal(fee) if fee.strip() else None
    except InvalidOperation as exc:
        raise ValueError("số lượng/giá không hợp lệ") from exc
    return TransactionCreate(
        coingecko_id=coingecko_id.strip(),
        symbol=symbol.strip(),
        name=name.strip(),
        type=type_,  # type: ignore[arg-type]  # Pydantic validate Literal["buy","sell"]
        quantity=qty,
        price=prc,
        fee=fee_val,
        note=note.strip() or None,
        executed_at=datetime.fromisoformat(executed_at),
    )


@router.post("/transactions")
def add_transaction(
    coingecko_id: str = Form(...),
    symbol: str = Form(""),
    name: str = Form(""),
    type: str = Form(...),
    quantity: str = Form(...),
    price: str = Form(...),
    fee: str = Form(""),
    note: str = Form(""),
    executed_at: str = Form(...),
    user: User = Depends(get_current_user),
    service: PortfolioService = Depends(get_portfolio_service),
) -> RedirectResponse:
    try:
        data = _parse_form(
            coingecko_id, symbol, name, type, quantity, price, fee, note, executed_at
        )
    except (ValidationError, ValueError):
        return RedirectResponse("/portfolio/transactions?error=1", status_code=303)
    service.add_transaction(user.id, data)
    return RedirectResponse("/portfolio/transactions", status_code=303)


@router.post("/transactions/{tx_id}/edit")
def edit_transaction(
    tx_id: int,
    coingecko_id: str = Form(...),
    symbol: str = Form(""),
    name: str = Form(""),
    type: str = Form(...),
    quantity: str = Form(...),
    price: str = Form(...),
    fee: str = Form(""),
    note: str = Form(""),
    executed_at: str = Form(...),
    user: User = Depends(get_current_user),
    service: PortfolioService = Depends(get_portfolio_service),
) -> RedirectResponse:
    try:
        data = _parse_form(
            coingecko_id, symbol, name, type, quantity, price, fee, note, executed_at
        )
    except (ValidationError, ValueError):
        return RedirectResponse(
            f"/portfolio/transactions?edit={tx_id}&error=1", status_code=303
        )
    service.update_transaction(user.id, tx_id, data)
    return RedirectResponse("/portfolio/transactions", status_code=303)


@router.post("/transactions/{tx_id}/delete")
def delete_transaction(
    tx_id: int,
    user: User = Depends(get_current_user),
    service: PortfolioService = Depends(get_portfolio_service),
) -> RedirectResponse:
    service.delete_transaction(user.id, tx_id)
    return RedirectResponse("/portfolio/transactions", status_code=303)
