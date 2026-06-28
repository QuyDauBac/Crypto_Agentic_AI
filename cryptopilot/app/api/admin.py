"""Router Admin (Phase 6) — chỉ admin (Depends get_current_admin).

GET  /admin                        → dashboard thống kê hệ thống
GET  /admin/users                  → danh sách user
POST /admin/users/{id}/toggle-active → khóa/mở tài khoản
POST /admin/users/{id}/toggle-admin  → cấp/thu quyền admin
GET  /admin/settings               → form cấu hình hệ thống
POST /admin/settings               → lưu cấu hình
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.models.user import User
from app.services.admin_service import AdminService
from app.services.settings_service import DEFAULTS, SettingsService

router = APIRouter(prefix="/admin", tags=["admin"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_admin_service(db: Session = Depends(get_db)) -> AdminService:
    return AdminService(db)


def get_settings_service(db: Session = Depends(get_db)) -> SettingsService:
    return SettingsService(db)


# ────────────────────────────── Dashboard ──────────────────────────────
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    admin: User = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "admin/dashboard.html", {"user": admin, "stats": service.stats()}
    )


# ────────────────────────────── Quản lý user ──────────────────────────────
@router.get("/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    admin: User = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/users.html",
        {"user": admin, "users": service.list_users()},
    )


@router.post("/users/{user_id}/toggle-active")
def toggle_active(
    user_id: int,
    admin: User = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> RedirectResponse:
    service.toggle_active(user_id, admin)
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/toggle-admin")
def toggle_admin(
    user_id: int,
    admin: User = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> RedirectResponse:
    service.toggle_admin(user_id, admin)
    return RedirectResponse("/admin/users", status_code=303)


# ────────────────────────────── Cấu hình hệ thống ──────────────────────────────
@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    saved: int | None = None,
    admin: User = Depends(get_current_admin),
    service: SettingsService = Depends(get_settings_service),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/settings.html",
        {"user": admin, "settings": service.all_for_admin(), "saved": saved},
    )


@router.post("/settings")
async def save_settings(
    request: Request,
    admin: User = Depends(get_current_admin),
    service: SettingsService = Depends(get_settings_service),
) -> RedirectResponse:
    form = await request.form()
    for key, spec in DEFAULTS.items():
        if spec["type"] == "bool":
            # checkbox: có trong form = bật
            service.set(key, "true" if key in form else "false")
        elif key in form:
            value = str(form[key]).strip()
            service.set(key, value)
    return RedirectResponse("/admin/settings?saved=1", status_code=303)
