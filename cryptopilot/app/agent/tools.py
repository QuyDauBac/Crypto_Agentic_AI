"""Tools của AI Agent (Phase 4) — khai báo + dispatcher.

TOOL_SPECS: khai báo provider-agnostic (dict thuần) — KHÔNG phụ thuộc google-genai, để
dispatcher test được mà không cần SDK. GeminiClient sẽ convert spec → types.FunctionDeclaration.

dispatch(): map tên tool Agent gọi → service tương ứng. `user` đến từ SESSION (ToolContext),
KHÔNG từ tham số Gemini → Agent không bao giờ đọc được danh mục user khác, kể cả khi bị "dụ".
"""

from dataclasses import dataclass

from app.models.user import User
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService

# ──────────────────────────── Khai báo tool (cho Gemini đọc) ────────────────────────────
# description viết rõ → Gemini chọn đúng tool. Đây là phần prompt-engineering quan trọng.
TOOL_SPECS: list[dict] = [
    {
        "name": "get_portfolio_summary",
        "description": (
            "Lấy danh mục hiện tại của user: từng coin, số lượng, giá vốn trung bình, "
            "giá hiện tại, giá trị và lãi/lỗ chưa thực hiện, kèm tổng P&L. "
            "Gọi khi user hỏi 'danh mục của tôi', 'tôi đang lãi/lỗ bao nhiêu', 'tôi có gì'."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_portfolio_allocation",
        "description": (
            "Lấy tỷ trọng phần trăm của từng coin trong danh mục, để đánh giá mức độ "
            "tập trung rủi ro. Gọi khi user hỏi về rủi ro, đa dạng hoá, hoặc 'tôi có "
            "đang bỏ trứng một giỏ không'."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_coin_price",
        "description": "Lấy giá USD hiện tại của một coin. Gọi khi user hỏi giá một coin cụ thể.",
        "parameters": {
            "type": "object",
            "properties": {
                "coingecko_id": {
                    "type": "string",
                    "description": "id CoinGecko, vd 'bitcoin', 'ethereum'",
                }
            },
            "required": ["coingecko_id"],
        },
    },
    {
        "name": "get_coin_history",
        "description": (
            "Lấy lịch sử giá của một coin trong N ngày gần nhất, dùng để đánh giá xu "
            "hướng tăng/giảm. Gọi khi user hỏi về biến động, xu hướng, hoặc 'coin X "
            "dạo này thế nào'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "coingecko_id": {
                    "type": "string",
                    "description": "id CoinGecko, vd 'bitcoin'",
                },
                "days": {
                    "type": "integer",
                    "description": "Số ngày, vd 7, 30, 90",
                },
            },
            "required": ["coingecko_id", "days"],
        },
    },
    {
        "name": "get_crypto_news",
        "description": (
            "Lấy tin tức crypto gần đây, lọc theo các coin user đang giữ. Gọi khi user "
            "hỏi về tin tức, có gì mới, hoặc vì sao giá biến động."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Số tin tối đa, mặc định 5",
                }
            },
            "required": [],
        },
    },
]

TOOL_NAMES = {spec["name"] for spec in TOOL_SPECS}


@dataclass
class ToolContext:
    """Bối cảnh thực thi tool — user gắn từ session (KHÔNG từ Gemini)."""

    user: User
    portfolio_service: PortfolioService
    market_service: MarketService
    news_service: NewsService


def _summarize_history(points: list, coingecko_id: str, days: int) -> dict:
    """Nén lịch sử giá thành dict gọn (tránh đốt token với hàng trăm điểm)."""
    if not points:
        return {
            "coingecko_id": coingecko_id,
            "days": days,
            "note": "Không lấy được lịch sử giá.",
        }
    prices = [p.price for p in points]
    first, last = prices[0], prices[-1]
    change_pct = ((last - first) / first * 100) if first else None
    # lấy ~6 điểm mẫu rải đều để Agent thấy hình dạng đường giá
    n = len(prices)
    step = max(1, n // 6)
    sampled = [round(prices[i], 6) for i in range(0, n, step)][:6]
    return {
        "coingecko_id": coingecko_id,
        "days": days,
        "first_price_usd": round(first, 6),
        "last_price_usd": round(last, 6),
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "min_usd": round(min(prices), 6),
        "max_usd": round(max(prices), 6),
        "sampled_prices_usd": sampled,
        "points_count": n,
    }


async def dispatch(name: str, args: dict, ctx: ToolContext) -> dict:
    """Thực thi tool theo tên. Validate tham số, scope theo ctx.user. Lỗi → {'error': ...}."""
    user = ctx.user
    try:
        if name == "get_portfolio_summary":
            return await ctx.portfolio_service.get_summary(user.id)

        if name == "get_portfolio_allocation":
            return await ctx.portfolio_service.get_allocation(user.id)

        if name == "get_coin_price":
            cid = str(args.get("coingecko_id", "")).strip()
            if not cid:
                return {"error": "thiếu coingecko_id"}
            snap = await ctx.market_service.get_prices([cid])
            price = snap.prices.get(cid)
            if price is None:
                return {"error": f"không tìm thấy giá cho '{cid}'"}
            return {"coingecko_id": cid, "price_usd": price, "stale": snap.stale}

        if name == "get_coin_history":
            cid = str(args.get("coingecko_id", "")).strip()
            if not cid:
                return {"error": "thiếu coingecko_id"}
            try:
                days = int(args.get("days", 30))
            except (TypeError, ValueError):
                return {"error": "days phải là số nguyên"}
            days = max(1, min(days, 365))
            points = await ctx.market_service.get_history(cid, days)
            return _summarize_history(points, cid, days)

        if name == "get_crypto_news":
            try:
                limit = int(args.get("limit", 5))
            except (TypeError, ValueError):
                limit = 5
            limit = max(1, min(limit, 15))
            return await ctx.news_service.get_filtered(user, limit=limit)

        return {"error": f"unknown tool: {name}"}
    except Exception as exc:  # noqa: BLE001 — tool lỗi không được làm sập vòng ReAct
        return {"error": f"tool '{name}' lỗi: {exc}"}
