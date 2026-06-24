"""Dependencies dùng chung cho route — đọc user hiện tại từ JWT trong cookie."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User


def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    """Trả về User nếu cookie hợp lệ, None nếu không (dùng cho trang công khai)."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    sub = decode_access_token(token)
    if not sub:
        return None
    try:
        user_id = int(sub)
    except ValueError:
        return None
    return db.get(User, user_id)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Bắt buộc đăng nhập. Thiếu/sai token → 401 (handler sẽ redirect /login)."""
    user = get_current_user_optional(request, db)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user
