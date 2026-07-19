"""Router market — THIN: chỉ validate input, gọi MarketService, render template/JSON.

Endpoints:
  GET  /market                  → trang demo: ô tìm coin + kết quả + giá
  GET  /market/coin/{id}         → trang chi tiết coin: candlestick chart + tin tức
  GET  /market/api/search?q=     → JSON list coin (cho gợi ý/tìm)
  GET  /market/api/prices?ids=   → JSON giá nhiều coin (JS poll để cập nhật "real-time")

Phase 2 để trang này PUBLIC (chỉ là dữ liệu giá công khai) nên chạy độc lập, không phụ
thuộc auth. Khi muốn đưa vào sau đăng nhập, thêm Depends(get_current_user) là đủ.

Khai báo `async def` vì có await gọi CoinGecko (external API). Phần DB (qua service) là
sync nhưng nhẹ, chấp nhận được trong scope đồ án.
"""

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.adapters.cointelegraph_adapter import CoinTelegraphAdapter
from app.api import deps
from app.api.template_filters import register as register_template_filters
from app.core.database import get_db
from app.schemas.market import CoinResult, PriceSnapshot
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/market", tags=["market"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
register_template_filters(templates.env)


def get_market_service(db: Session = Depends(get_db)) -> MarketService:
    """Bind MarketDataInterface → CoinGeckoAdapter MỘT CHỖ duy nhất.

    Đổi provider sau này chỉ sửa đúng dòng adapter ở đây. Test override dependency này
    để cắm fake service.
    """
    return MarketService(db=db, adapter=CoinGeckoAdapter())


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def market_page(
    request: Request,
    q: str | None = Query(default=None, description="Từ khóa tìm coin"),
    service: MarketService = Depends(get_market_service),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user = deps.get_current_user_optional(request, db)
    results: list[CoinResult] = []
    snapshot: PriceSnapshot | None = None
    if q:
        results = await service.search_coins(q)
        ids = [c.coingecko_id for c in results[:15]]  # giới hạn để nhẹ rate limit
        if ids:
            snapshot = await service.get_prices(ids)

    # Chỉ gọi trending/top market cap khi chưa tìm gì — đỡ tốn API call lúc đang search
    trending: list[dict] = []
    top_cap: list[dict] = []
    if not q:
        trending, top_cap = await asyncio.gather(
            service.get_trending(), service.get_top_market_cap(limit=6)
        )

    return templates.TemplateResponse(
        request,
        "market/search.html",
        {
            "user": user,
            "q": q or "",
            "results": results[:15],
            "prices": snapshot.prices if snapshot else {},
            "stale": snapshot.stale if snapshot else False,
            "trending": trending,
            "top_cap": top_cap,
        },
    )


def get_news_service(db: Session = Depends(get_db)) -> NewsService:
    """NewsService cho trang chi tiết coin — bind CoinTelegraphAdapter một chỗ (như market)."""
    market = MarketService(db=db, adapter=CoinGeckoAdapter())
    portfolio = PortfolioService(db=db, market_service=market)
    return NewsService(
        db=db, adapter=CoinTelegraphAdapter(), portfolio_service=portfolio
    )


# Các giá trị days hợp lệ cho nến OHLC (CoinGecko chấp nhận 1/7/14/30/90/180/365/max;
# UI chỉ đưa 5 lựa chọn). Giá trị lạ trên query param → rơi về 30.
_OHLC_DAYS_CHOICES = (1, 7, 30, 90, 365)
_OHLC_DEFAULT_DAYS = 30

# coingecko_id → cặp giao dịch Binance (USDT) cho WebSocket giá live trên trang chi
# tiết coin. Hard-code ~20 coin phổ biến thay vì tra động qua CoinGecko
# /coins/{id}?tickers=true — trade-off cố ý (xem ghi chú trong PR/summary):
#   + đơn giản, không tốn thêm 1 call CoinGecko mỗi lần load trang (rate limit free
#     tier ~30 calls/phút vốn đã eo hẹp), không phụ thuộc CoinGecko trả đúng field
#     tickers/market identifier như kỳ vọng
#   - coin ngoài danh sách này luôn hiện "không có dữ liệu live" dù có thể thực sự
#     đang niêm yết trên Binance — chấp nhận được vì đây là tính năng phụ trợ
#     (nice-to-have), không phải nguồn giá chính (giá chính vẫn luôn là CoinGecko)
BINANCE_PAIRS: dict[str, str] = {
    "bitcoin": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "binancecoin": "BNBUSDT",
    "ripple": "XRPUSDT",
    "solana": "SOLUSDT",
    "cardano": "ADAUSDT",
    "dogecoin": "DOGEUSDT",
    "avalanche-2": "AVAXUSDT",
    "tron": "TRXUSDT",
    "chainlink": "LINKUSDT",
    "polkadot": "DOTUSDT",
    "litecoin": "LTCUSDT",
    "bitcoin-cash": "BCHUSDT",
    "near": "NEARUSDT",
    "uniswap": "UNIUSDT",
    "stellar": "XLMUSDT",
    "internet-computer": "ICPUSDT",
    "aptos": "APTUSDT",
    "filecoin": "FILUSDT",
    "cosmos": "ATOMUSDT",
    "shiba-inu": "SHIBUSDT",
}


def _format_published(raw: str) -> str:
    """ISO 8601 của CryptoPanic → 'dd/mm/yyyy HH:MM' cho card tin tức."""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime(
            "%d/%m/%Y %H:%M"
        )
    except ValueError:
        return raw


@router.get("/coin/{coingecko_id}", response_class=HTMLResponse)
async def coin_detail(
    request: Request,
    coingecko_id: str,
    days: int = Query(default=_OHLC_DEFAULT_DAYS),
    service: MarketService = Depends(get_market_service),
    news_service: NewsService = Depends(get_news_service),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user = deps.get_current_user_optional(request, db)
    if days not in _OHLC_DAYS_CHOICES:
        days = _OHLC_DEFAULT_DAYS

    # Coin chưa có trong bảng local (user gõ URL trực tiếp) → thử search để upsert
    coin = service.get_coin(coingecko_id)
    if coin is None:
        await service.search_coins(coingecko_id)
        coin = service.get_coin(coingecko_id)
    if coin is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy coin")

    snapshot = await service.get_prices([coingecko_id])
    ohlc = await service.get_coin_ohlc(coingecko_id, days)
    market = await service.get_coin_market_data(coingecko_id)
    news = await news_service.get_news_for_coin(coingecko_id, limit=10)
    for n in news:
        n["published_display"] = _format_published(n.get("published_at") or "")

    return templates.TemplateResponse(
        request,
        "market/coin_detail.html",
        {
            "user": user,
            "coin": coin,
            "price": snapshot.prices.get(coingecko_id),
            "stale": snapshot.stale,
            # market: None nếu CoinGecko lỗi/không có dữ liệu — mỗi field template tự
            # hiện "—" (graceful, không phải lỗi to)
            "change_24h_pct": market["change_24h_pct"] if market else None,
            "market_cap": market["market_cap"] if market else None,
            "volume_24h": market["volume_24h"] if market else None,
            "circulating_supply": market["circulating_supply"] if market else None,
            "market_cap_rank": market["market_cap_rank"] if market else None,
            "ath": market["ath"] if market else None,
            "max_supply": market["max_supply"] if market else None,
            "days": days,
            "days_choices": _OHLC_DAYS_CHOICES,
            "ohlc": ohlc,
            "news": news,
            # hỏi adapter (không đọc settings trực tiếp) để test override được;
            # CoinTelegraph RSS không cần key → luôn True, giữ cờ cho adapter tương lai
            "news_configured": news_service.adapter.is_configured,
            # None nếu coin không nằm trong danh sách map — template ẩn WebSocket,
            # hiện "không có dữ liệu live" thay vì cố mở kết nối tới cặp không tồn tại
            "binance_pair": BINANCE_PAIRS.get(coingecko_id),
        },
    )


@router.get("/api/search")
async def api_search(
    q: str = Query(min_length=1),
    service: MarketService = Depends(get_market_service),
) -> list[CoinResult]:
    return await service.search_coins(q)


@router.get("/api/prices")
async def api_prices(
    ids: str = Query(description="Danh sách coingecko_id, cách nhau bằng dấu phẩy"),
    service: MarketService = Depends(get_market_service),
) -> PriceSnapshot:
    coin_ids = [c.strip() for c in ids.split(",") if c.strip()]
    return await service.get_prices(coin_ids)
