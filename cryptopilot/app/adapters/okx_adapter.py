"""OKXAdapter — bọc toàn bộ logic gọi OKX v5 REST API (Phase 8).

OKX API khác CoinGecko ở chỗ MỌI request private đều cần ký HMAC-SHA256 qua 4 header:
  OK-ACCESS-KEY, OK-ACCESS-SIGN, OK-ACCESS-TIMESTAMP, OK-ACCESS-PASSPHRASE

Công thức sign (theo docs OKX):
  sign = base64( HMAC-SHA256(secret, timestamp + method + request_path + body) )
  timestamp = ISO8601 UTC có mili-giây, ví dụ "2020-12-08T09:08:57.715Z"

Chỉ dùng 2 endpoint (đủ cho mục đích portfolio tracking — không giao dịch):
  GET /api/v5/account/balance        → validate key lúc connect() + xem số dư
  GET /api/v5/trade/fills-history     → lịch sử khớp lệnh SPOT → tạo Transaction

Giống CoinGeckoAdapter: nhận `transport` để inject httpx.MockTransport khi test,
không cần gọi mạng OKX thật.
"""

import base64
import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings

_DEFAULT_TIMEOUT = 10.0


class OKXAPIError(RuntimeError):
    """OKX trả về lỗi (code != '0') — message lấy từ field `msg` của response."""


class OKXAdapter:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.base_url = (base_url or settings.OKX_BASE_URL).rstrip("/")
        self._transport = transport
        self._timeout = timeout

    # ── Ký request theo chuẩn OKX ──
    def _timestamp(self) -> str:
        now = datetime.now(UTC)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    def _sign(
        self, timestamp: str, method: str, request_path: str, body: str = ""
    ) -> str:
        message = f"{timestamp}{method}{request_path}{body}"
        mac = hmac.new(
            self.api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    def _headers(
        self, method: str, request_path: str, body: str = ""
    ) -> dict[str, str]:
        ts = self._timestamp()
        return {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": self._sign(ts, method, request_path, body),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> list[dict]:
        params = params or {}
        query = "&".join(f"{k}={v}" for k, v in params.items())
        request_path = f"{path}?{query}" if query else path
        headers = self._headers("GET", request_path)

        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=self._timeout, transport=self._transport
        ) as client:
            resp = await client.get(request_path, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != "0":
            raise OKXAPIError(data.get("msg") or f"OKX lỗi code={data.get('code')}")
        return data.get("data", [])

    # ── Endpoint: số dư tài khoản (spot) — dùng để validate key lúc connect() ──
    async def get_balance(self) -> list[dict]:
        return await self._get("/api/v5/account/balance")

    # ── Endpoint: lịch sử khớp lệnh SPOT — nguồn tạo Transaction ──
    async def get_fills_history(self, limit: int = 100) -> list[dict]:
        return await self._get(
            "/api/v5/trade/fills-history",
            {"instType": "SPOT", "limit": str(limit)},
        )
