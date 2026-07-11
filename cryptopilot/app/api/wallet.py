"""Router Wallet (Phase 8) — kết nối ví OKX, đồng bộ giao dịch.

GET  /wallet             → trang quản lý kết nối (form connect nếu chưa kết nối,
                            trạng thái + nút Sync/Disconnect nếu đã kết nối)
POST /wallet/connect     → lưu API key (đã validate + mã hóa)
POST /wallet/disconnect  → xóa kết nối
POST /wallet/sync        → đồng bộ giao dịch thủ công

Mọi route yêu cầu đăng nhập, scope theo user.id lấy từ JWT (Depends get_current_user) —
KHÔNG BAO GIỜ nhận user_id từ form/query param.
"""

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
from app.schemas.okx import OKXConnectRequest
from app.services.market_service import MarketService
from app.services.okx_service import OKXConnectError, OKXNotConnectedError, OKXService

router = APIRouter(prefix="/wallet", tags=["wallet"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_okx_service(db: Session = Depends(get_db)) -> OKXService:
    market = MarketService(db=db, adapter=CoinGeckoAdapter())
    return OKXService(db=db, market_service=market)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def wallet_page(
    request: Request,
    error: str | None = None,
    synced: int | None = None,
    user: User = Depends(get_current_user),
    service: OKXService = Depends(get_okx_service),
) -> HTMLResponse:
    status = service.get_status(user.id)
    return templates.TemplateResponse(
        request,
        "wallet/index.html",
        {"user": user, "status": status, "error": error, "synced": synced},
    )


@router.post("/connect")
async def connect(
    request: Request,
    api_key: str = Form(...),
    api_secret: str = Form(...),
    passphrase: str = Form(...),
    user: User = Depends(get_current_user),
    service: OKXService = Depends(get_okx_service),
) -> RedirectResponse:
    try:
        data = OKXConnectRequest(
            api_key=api_key.strip(),
            api_secret=api_secret.strip(),
            passphrase=passphrase.strip(),
        )
        await service.connect(user.id, data)
    except (ValidationError, OKXConnectError):
        return RedirectResponse("/wallet?error=connect", status_code=303)
    return RedirectResponse("/wallet", status_code=303)


@router.post("/disconnect")
def disconnect(
    user: User = Depends(get_current_user),
    service: OKXService = Depends(get_okx_service),
) -> RedirectResponse:
    service.disconnect(user.id)
    return RedirectResponse("/wallet", status_code=303)


@router.post("/sync")
async def sync(
    user: User = Depends(get_current_user),
    service: OKXService = Depends(get_okx_service),
) -> RedirectResponse:
    try:
        result = await service.sync(user.id)
    except OKXNotConnectedError:
        return RedirectResponse("/wallet?error=not_connected", status_code=303)
    except OKXConnectError:
        return RedirectResponse("/wallet?error=sync", status_code=303)
    return RedirectResponse(f"/wallet?synced={result.imported}", status_code=303)
