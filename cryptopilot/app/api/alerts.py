"""Router Alerts & Notifications (Phase 5).

GET  /alerts                       → trang quản lý cảnh báo + form đặt
POST /alerts                       → tạo cảnh báo
POST /alerts/{id}/delete           → xoá cảnh báo
GET  /notifications                → trang hộp thông báo
POST /notifications/{id}/read      → đánh dấu đã đọc
POST /notifications/read-all       → đánh dấu tất cả đã đọc
GET  /notifications/unread-count   → JSON {count} cho badge navbar (JS poll)

Mọi route yêu cầu đăng nhập, scope theo user.id.
"""

from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.alert import AlertCreate
from app.services.alert_service import AlertService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService

router = APIRouter(tags=["alerts"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_alert_service(db: Session = Depends(get_db)) -> AlertService:
    return AlertService(db)


def get_notification_service(db: Session = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


# ────────────────────────────── Alerts ──────────────────────────────
@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(
    request: Request,
    error: int | None = None,
    user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    alerts = service.list_alerts(user.id)
    default_threshold = SettingsService(db).get("alert.default_threshold_usd") or ""
    return templates.TemplateResponse(
        request,
        "alerts/index.html",
        {
            "user": user,
            "alerts": alerts,
            "error": error,
            "default_threshold": default_threshold,
        },
    )


@router.post("/alerts")
def create_alert(
    coingecko_id: str = Form(...),
    symbol: str = Form(""),
    name: str = Form(""),
    condition: str = Form(...),
    threshold_price: str = Form(...),
    user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> RedirectResponse:
    try:
        data = AlertCreate(
            coingecko_id=coingecko_id.strip(),
            symbol=symbol.strip(),
            name=name.strip(),
            condition=condition,  # type: ignore[arg-type]  # Pydantic validate Literal
            threshold_price=Decimal(threshold_price),
        )
    except (ValidationError, InvalidOperation, ValueError):
        return RedirectResponse("/alerts?error=1", status_code=303)
    service.create_alert(user.id, data)
    return RedirectResponse("/alerts", status_code=303)


@router.post("/alerts/{alert_id}/delete")
def delete_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> RedirectResponse:
    service.delete_alert(user.id, alert_id)
    return RedirectResponse("/alerts", status_code=303)


# ────────────────────────────── Notifications ──────────────────────────────
@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(
    request: Request,
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> HTMLResponse:
    notifs = service.list_for_user(user.id)
    return templates.TemplateResponse(
        request,
        "notifications/index.html",
        {"user": user, "notifs": notifs, "unread": service.unread_count(user.id)},
    )


@router.post("/notifications/{notif_id}/read")
def mark_read(
    notif_id: int,
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> RedirectResponse:
    service.mark_read(user.id, notif_id)
    return RedirectResponse("/notifications", status_code=303)


@router.post("/notifications/read-all")
def mark_all_read(
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> RedirectResponse:
    service.mark_all_read(user.id)
    return RedirectResponse("/notifications", status_code=303)


@router.get("/notifications/unread-count")
def unread_count(
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> JSONResponse:
    return JSONResponse({"count": service.unread_count(user.id)})
