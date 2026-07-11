"""Mã hóa/giải mã credentials nhạy cảm (OKX api_key/secret/passphrase) trước khi lưu DB.

Dùng Fernet (symmetric, AES-128-CBC + HMAC) — đơn giản, đủ an toàn cho use-case này
(không cần public-key crypto). ENCRYPTION_KEY lưu trong .env, KHÔNG commit GitHub.

Nếu ENCRYPTION_KEY chưa cấu hình, raise lỗi rõ ràng CHỈ KHI thực sự dùng tới (encrypt/
decrypt), không phải lúc import module — để không phá app khi chưa cấu hình OKX.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class EncryptionNotConfigured(RuntimeError):
    """ENCRYPTION_KEY chưa được đặt trong .env."""


def _fernet() -> Fernet:
    key = settings.ENCRYPTION_KEY.strip()
    if not key:
        raise EncryptionNotConfigured(
            "Chưa cấu hình ENCRYPTION_KEY trong .env — tạo bằng: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode("utf-8"))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Không giải mã được — ENCRYPTION_KEY sai hoặc dữ liệu hỏng."
        ) from exc
