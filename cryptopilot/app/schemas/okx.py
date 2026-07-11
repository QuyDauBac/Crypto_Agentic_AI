"""Schemas Phase 8 — OKX wallet connect input + status/sync output.

OKXConnectRequest KHÔNG BAO GIỜ được dùng làm response model (chỉ input) — credentials
không bao giờ đi ngược lại client dưới bất kỳ hình thức nào.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class OKXConnectRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=200)
    api_secret: str = Field(min_length=1, max_length=200)
    passphrase: str = Field(min_length=1, max_length=200)


class OKXStatusView(BaseModel):
    """Trạng thái kết nối — KHÔNG chứa api_key/secret/passphrase dưới bất kỳ dạng nào."""

    is_connected: bool
    last_synced_at: datetime | None = None


class OKXSyncResult(BaseModel):
    imported: int
    total_fills: int
