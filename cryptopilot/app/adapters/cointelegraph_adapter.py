"""CoinTelegraph RSS adapter — nguồn tin tức crypto hiện tại (thay CryptoPanic).

Vì sao chọn (07/2026): CryptoPanic ngừng free tier (04/2026); cryptocurrency.cv —
phương án thay thế dự kiến — deployment đã chết (Vercel DEPLOYMENT_DISABLED);
CoinGecko News chỉ có ở gói Pro. CoinTelegraph RSS: free, KHÔNG cần API key,
cập nhật hàng giờ, và có feed riêng theo từng coin qua tag:
    https://cointelegraph.com/rss/tag/{ten-coin-slug}   (vd /rss/tag/ethereum)

Chiến lược lọc theo coin:
  - 1 coin  → gọi thẳng tag feed (lọc phía server, chính xác nhất);
              tag không tồn tại/rỗng → fallback feed tổng + lọc phía client
  - nhiều coin → feed tổng /rss + lọc phía client: match TÊN coin
              (case-insensitive) trong title/description
  - không lọc → feed tổng /rss

Parse RSS 2.0 bằng xml.etree stdlib — không thêm dependency.
Graceful như CryptoPanicAdapter cũ: lỗi mạng/parse → log warning + trả [].
"""

import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

from app.adapters.news_data import NewsDataInterface
from app.core.config import settings

logger = logging.getLogger(__name__)

_SOURCE_NAME = "Cointelegraph"
# UA rõ ràng — một số CDN chặn request không có User-Agent
_HEADERS = {"User-Agent": "CryptoPilot/1.0 (crypto portfolio course project)"}
_TAG_RE = re.compile(r"<[^>]+>")  # bóc HTML trong <description> khi match text


def _slugify(name: str) -> str:
    """'Bitcoin Cash' → 'bitcoin-cash' (format tag của CoinTelegraph)."""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def _to_iso(rfc822: str) -> str:
    """pubDate RFC 822 ('Sun, 12 Jul 2026 18:28:59 +0000') → ISO 8601."""
    try:
        return parsedate_to_datetime(rfc822).isoformat()
    except (TypeError, ValueError):
        return rfc822


def _strip_internal(posts: list[dict]) -> list[dict]:
    """Bỏ key nội bộ _description trước khi trả ra ngoài (shape chuẩn NewsDataInterface)."""
    return [{k: v for k, v in p.items() if k != "_description"} for p in posts]


class CoinTelegraphAdapter(NewsDataInterface):
    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        # transport injectable để test bằng httpx.MockTransport (giống các adapter khác)
        self.base_url = (base_url or settings.COINTELEGRAPH_BASE_URL).rstrip("/")
        self._transport = transport
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        return True  # RSS công khai — không cần token, luôn sẵn sàng

    async def get_posts(
        self, currencies: list[str] | None = None, limit: int = 5
    ) -> list[dict]:
        names = [n for n in (currencies or []) if n and n.strip()]

        if len(names) == 1:
            posts = await self._fetch_feed(f"/rss/tag/{_slugify(names[0])}", names)
            if posts:
                return _strip_internal(posts)[:limit]
            # tag không tồn tại (coin nhỏ) → fallback feed tổng + lọc client
            return self._filter_by_names(await self._fetch_feed("/rss", names), names)[
                :limit
            ]

        posts = await self._fetch_feed("/rss", names)
        if names:
            return self._filter_by_names(posts, names)[:limit]
        return _strip_internal(posts)[:limit]

    # ──────────────────────────── internals ────────────────────────────
    async def _fetch_feed(self, path: str, names: list[str]) -> list[dict]:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport, headers=_HEADERS
            ) as client:
                resp = await client.get(f"{self.base_url}{path}")
                resp.raise_for_status()
                return self._parse_rss(resp.text, names)
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.warning("CoinTelegraph RSS lỗi (%s): %s", path, exc)
            return []

    def _parse_rss(self, xml_text: str, names: list[str]) -> list[dict]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.warning("CoinTelegraph RSS parse lỗi: %s", exc)
            return []

        out: list[dict] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            if not title or not url:
                continue
            out.append(
                {
                    "title": title,
                    "source": _SOURCE_NAME,
                    "url": url,
                    "published_at": _to_iso(item.findtext("pubDate") or ""),
                    "currencies": names,
                    # giữ nội bộ cho bước lọc client-side; không đưa ra ngoài shape chuẩn
                    "_description": _TAG_RE.sub(
                        " ", item.findtext("description") or ""
                    ),
                }
            )
        return out

    @staticmethod
    def _filter_by_names(posts: list[dict], names: list[str]) -> list[dict]:
        """Giữ bài có TÊN coin (case-insensitive) trong title/description."""
        lowered = [n.lower() for n in names]
        matched = []
        for p in posts:
            haystack = f"{p['title']} {p.get('_description', '')}".lower()
            hits = [n for n in lowered if n in haystack]
            if hits:
                p = {k: v for k, v in p.items() if k != "_description"}
                p["currencies"] = hits
                matched.append(p)
        return matched
