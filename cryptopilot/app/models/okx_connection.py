"""Model OKXConnection — lưu credentials OKX API đã mã hóa của user (Phase 8).

Một user chỉ có 1 connection (unique user_id). Ba trường credential (api_key,
api_secret, passphrase) LUÔN lưu dưới dạng mã hóa Fernet (xem app/core/encryption.py) —
KHÔNG BAO GIỜ lưu plaintext, KHÔNG BAO GIỜ trả về qua API response.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OKXConnection(Base):
    __tablename__ = "okx_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True, nullable=False
    )

    # Đã mã hóa Fernet — xem app/core/encryption.py encrypt()/decrypt()
    api_key_encrypted: Mapped[str] = mapped_column(String(500), nullable=False)
    api_secret_encrypted: Mapped[str] = mapped_column(String(500), nullable=False)
    passphrase_encrypted: Mapped[str] = mapped_column(String(500), nullable=False)

    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OKXConnection user_id={self.user_id}>"
