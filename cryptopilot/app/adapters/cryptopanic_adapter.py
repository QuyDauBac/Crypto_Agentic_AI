"""CryptoPanic adapter — nguồn tin tức CŨ, KHÔNG còn được inject từ 07/2026.

⚠️ CryptoPanic ngừng free tier từ 04/2026 — file này giữ lại phòng trường hợp quay lại
dùng bản trả phí; nguồn hiện tại là CoinTelegraph RSS (cointelegraph_adapter.py).
Lưu ý nếu kích hoạt lại: NewsService giờ truyền TÊN coin ("Bitcoin") qua `currencies`
theo NewsDataInterface, còn CryptoPanic cần SYMBOL (BTC) — phải map lại trước khi gọi.

CryptoPanic Developer API v2: GET {base}/posts/?auth_token=...&currencies=BTC,ETH
Bọc qua adapter để cô lập shape API ngoài khỏi phần còn lại của app (giống CoinGecko).

Graceful: thiếu token hoặc API lỗi → trả [] thay vì ném, để Agent vẫn trả lời được phần khác.
"""

import logging

import httpx

from app.adapters.news_data import NewsDataInterface
from app.core.config import settings

logger = logging.getLogger(__name__)


class CryptoPanicAdapter(NewsDataInterface):
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # transport injectable để test bằng httpx.MockTransport (giống coingecko_adapter)
        self.base_url = (base_url or settings.CRYPTOPANIC_BASE_URL).rstrip("/")
        self.token = token if token is not None else settings.CRYPTOPANIC_TOKEN
        self._transport = transport

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    async def get_posts(
        self, currencies: list[str] | None = None, limit: int = 5
    ) -> list[dict]:
        """Trả list bài viết đã chuẩn hoá: {title, source, url, published_at, currencies}.

        Thiếu token → trả [] (graceful). Lỗi mạng/parse → log warning + trả [].
        """
        if not self.token:
            logger.info("CryptoPanic: chưa cấu hình token → bỏ qua tin tức")
            return []

        params: dict[str, str] = {"auth_token": self.token, "public": "true"}
        if currencies:
            params["currencies"] = ",".join(c.upper() for c in currencies[:10])

        try:
            async with httpx.AsyncClient(
                timeout=15.0, transport=self._transport
            ) as client:
                resp = await client.get(f"{self.base_url}/posts/", params=params)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.warning("CryptoPanic lỗi: %s", exc)
            return []

        results = payload.get("results", []) if isinstance(payload, dict) else []
        out: list[dict] = []
        for item in results[:limit]:
            src = item.get("source") or {}
            out.append(
                {
                    "title": item.get("title", ""),
                    "source": src.get("title") or src.get("domain") or "unknown",
                    "url": item.get("url", ""),
                    "published_at": item.get("published_at", ""),
                    "currencies": [
                        c.get("code", "") for c in (item.get("currencies") or [])
                    ],
                }
            )
        return out
