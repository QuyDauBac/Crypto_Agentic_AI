"""Router portfolio (Phase 3) — dashboard + CRUD transactions.

Mọi route yêu cầu đăng nhập (Depends(get_current_user)) và scope theo user.id — Agent/UI
không bao giờ thấy danh mục user khác.

Async/sync theo 04-architecture.md:
  - GET /portfolio (dashboard)  → async def  (await giá CoinGecko)
  - các route CRUD chỉ đụng DB   → def        (FastAPI chạy trong threadpool)
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.transaction import TransactionCreate
from app.services.market_service import MarketService
from app.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
    return templates.TemplateResponse(
        request, "portfolio/dashboard.html", {"user": user, "d": view}
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
