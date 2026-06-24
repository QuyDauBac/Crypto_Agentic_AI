"""Tiện ích bảo mật — hash password (bcrypt trực tiếp) + tạo/giải mã JWT.

Dùng thẳng thư viện `bcrypt` (không qua passlib): gọn, không phụ thuộc lib đã ngừng
bảo trì, không vướng xung đột version. bcrypt chỉ xử lý tối đa 72 byte đầu của mật khẩu
nên ta cắt chủ động để tránh ValueError ở bản bcrypt mới.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

_BCRYPT_MAX_BYTES = 72


def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str | int, expires_minutes: int | None = None) -> str:
    """Tạo JWT với sub = user.id và exp."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.JWT_EXPIRE_MINUTES
    )
    payload = {"sub": str(subject), "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Trả về subject (user_id dạng str) nếu token hợp lệ, None nếu sai/hết hạn."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload.get("sub")
    except JWTError:
        return None
