"""Routes auth — register / login / logout (server-rendered, JWT qua httpOnly cookie)."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import UserCreate, UserLogin

router = APIRouter(tags=["auth"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _set_auth_cookie(response: Response, user: User) -> None:
    token = create_access_token(user.id)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,  # JS không đọc được → chống XSS đánh cắp token
        samesite="lax",
        secure=False,  # production: đặt True (HTTPS)
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
        path="/",
    )


# ── Register ──
@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse(request, "auth/register.html")


@router.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(""),
    display_name: str = Form(""),
    db: Session = Depends(get_db),
):
    # giữ lại giá trị đã nhập để prefill khi render lại form vì lỗi
    ctx = {"email": email, "display_name": display_name}

    if password != confirm_password:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {**ctx, "error": "Mật khẩu xác nhận không khớp."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        data = UserCreate(
            email=email, password=password, display_name=display_name or None
        )
    except ValidationError:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {**ctx, "error": "Email không hợp lệ hoặc mật khẩu < 6 ký tự."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if db.query(User).filter(User.email == data.email).first():
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {**ctx, "error": "Email đã được đăng ký."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        display_name=data.display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    resp = RedirectResponse("/portfolio", status_code=status.HTTP_303_SEE_OTHER)
    _set_auth_cookie(resp, user)
    return resp


# ── Login ──
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "auth/login.html")


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        data = UserLogin(email=email, password=password)
    except ValidationError:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Email hoặc mật khẩu không đúng.", "email": email},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user = db.query(User).filter(User.email == data.email).first()
    if user is None or not verify_password(data.password, user.hashed_password):
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Email hoặc mật khẩu không đúng.", "email": email},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    resp = RedirectResponse("/portfolio", status_code=status.HTTP_303_SEE_OTHER)
    _set_auth_cookie(resp, user)
    return resp


# ── Logout ──
@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("access_token", path="/")
    return resp
