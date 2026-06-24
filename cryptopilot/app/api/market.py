"""Router market — THIN: chỉ validate input, gọi MarketService, render template/JSON.

Endpoints:
  GET  /market                  → trang demo: ô tìm coin + kết quả + giá
  GET  /market/api/search?q=     → JSON list coin (cho gợi ý/tìm)
  GET  /market/api/prices?ids=   → JSON giá nhiều coin (JS poll để cập nhật "real-time")

Phase 2 để trang này PUBLIC (chỉ là dữ liệu giá công khai) nên chạy độc lập, không phụ
thuộc auth. Khi muốn đưa vào sau đăng nhập, thêm Depends(get_current_user) là đủ.

Khai báo `async def` vì có await gọi CoinGecko (external API). Phần DB (qua service) là
sync nhưng nhẹ, chấp nhận được trong scope đồ án.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.core.database import get_db
from app.schemas.market import CoinResult, PriceSnapshot
from app.services.market_service import MarketService

router = APIRouter(prefix="/market", tags=["market"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
) -> HTMLResponse:
    results: list[CoinResult] = []
    snapshot: PriceSnapshot | None = None
    if q:
        results = await service.search_coins(q)
        ids = [c.coingecko_id for c in results[:15]]  # giới hạn để nhẹ rate limit
        if ids:
            snapshot = await service.get_prices(ids)
    return templates.TemplateResponse(
        request,
        "market/search.html",
        {
            "q": q or "",
            "results": results[:15],
            "prices": snapshot.prices if snapshot else {},
            "stale": snapshot.stale if snapshot else False,
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
